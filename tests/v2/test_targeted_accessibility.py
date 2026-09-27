from types import SimpleNamespace as NS
import pytest
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.windows_accessibility import MAX_EDIT_TEXT_UNITS, read_controls
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform
from .test_runtime import click, run


class Element:
    def __init__(self, name, role="Pane", children=()):
        self.Name, self.ControlTypeName = name, role+"Control"
        self.children, self.parent = list(children), None
        self.AutomationId = name
        self.IsPassword, self.IsEnabled, self.IsOffscreen, self.HasKeyboardFocus = False, True, False, False
        self.BoundingRectangle = NS(left=0, top=0, right=20, bottom=20)
        self.Element = self
        self.CurrentNativeWindowHandle = id(self)
        for child in children: child.parent = self
    def GetRuntimeId(self): return (id(self),)
    def GetPattern(self, _): return None
    def FindFirst(self, scope, condition):
        assert scope == 1
        return self if condition(self) else None


class UIA:
    RawViewWalker = NS(GetParentElement=lambda e: e.parent)
    def CompareElements(self, a, b): return a is b
    def CreateTrueCondition(self): return lambda element: True
    def CreatePropertyCondition(self, prop, value): return lambda e: getattr(e, prop) == value
    def CreateAndCondition(self, a, b): return lambda e: a(e) and b(e)
    def CreateOrCondition(self, a, b): return lambda e: a(e) or b(e)
    def CreateTreeWalker(self, condition):
        def visible_children(parent):
            for child in parent.children:
                if condition(child): yield child
                else: yield from visible_children(child)
        def first(parent): return next(visible_children(parent), None)
        def sibling(node):
            parent = node.parent
            while parent and not condition(parent): parent = parent.parent
            # In the real filtered tree a nonmatching authorized root is still
            # the boundary used by GetFirstChildElement.
            if parent is None:
                parent = node.parent
                while parent and parent.parent: parent = parent.parent
            siblings = list(visible_children(parent)) if parent else []
            index = siblings.index(node)+1
            return siblings[index] if index < len(siblings) else None
        return NS(GetFirstChildElement=first, GetNextSiblingElement=sibling)


AUTO = NS(PropertyId=NS(NameProperty="Name", ControlTypeProperty="ControlTypeName", AutomationIdProperty="AutomationId", NativeWindowHandleProperty="CurrentNativeWindowHandle", RuntimeIdProperty="runtime_id"),
          ControlType=NS(EditControl="EditControl", PaneControl="PaneControl"),
          Control=NS(CreateControlFromElement=lambda e: e), PatternId=NS(ValuePattern=1, RangeValuePattern=2, TextPattern=3, SelectionItemPattern=4))


def test_native_filter_walks_nested_matches_and_does_not_materialize_nonmatches():
    root = Element("root", children=[Element("large", children=[Element(str(i)) for i in range(1000)]),
                                    Element("edit", "Edit", [Element("nested", "Edit")]), Element("last", "Edit")])
    result = read_controls(AUTO, UIA(), [root], {"role": "Edit"}, limit=10)
    assert result["coverage"] == "complete"
    assert [e["name"] for e in result["elements"]] == ["edit", "nested", "last"]


def test_native_filter_truncation_is_not_successful_absence():
    root = Element("root", children=[Element(str(i), "Edit") for i in range(20)])
    result = read_controls(AUTO, UIA(), [root], {"role": "Edit"}, limit=5)
    assert result["coverage"] == "truncated"
    assert len(result["elements"]) == 5


def test_native_provider_failure_is_not_an_empty_tree():
    root = Element("root")
    root.FindFirst = lambda *_: (_ for _ in ()).throw(RuntimeError("provider lost"))
    with pytest.raises(RuntimeError): read_controls(AUTO, UIA(), [root])


def test_filtered_walker_cannot_leak_fields_from_another_window():
    allowed = Element("authorized", children=[Element("safe", "Edit")])
    foreign = Element("foreign", children=[Element("secret", "Edit")])
    Element("desktop", children=[allowed, foreign])
    # A filtered walk skips both nonmatching window ancestors.
    result = read_controls(AUTO, UIA(), [allowed], {"role": "Edit"})
    assert [e["name"] for e in result["elements"]] == ["safe"]
    assert result["coverage"] == "complete"


def test_unknown_role_and_cancel_are_explicit():
    root = Element("root")
    with pytest.raises(AxisError, match="Unknown native"):
        read_controls(AUTO, UIA(), [root], {"role": "Invented"})
    with pytest.raises(AxisError, match="cancelled"):
        read_controls(AUTO, UIA(), [root], cancel=NS(is_set=lambda: True))


def test_query_scope_is_retained_for_refs_and_diff(tmp_path):
    pal = FakePlatform()
    pal.coverage = "truncated"
    calls = []
    original_inspect = pal.inspect
    def inspect(target, query=None):
        calls.append(query)
        raw = original_inspect(target)
        if query:
            raw = {**raw, "elements": Runtime._matches(raw["elements"], query), "coverage": "complete"}
        return raw
    original_capabilities = pal.capabilities
    pal.capabilities = lambda: {**original_capabilities(), "targeted_accessibility": True}
    pal.inspect = inspect
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal"))
    try:
        query = {"role": "Edit"}
        observation = runtime.call("axis.observe", {"target_id": "test", "query": query})
        session = observation["session_id"]
        assert observation["coverage"] == "complete"
        result = run(runtime, session, [click(args={"at": {"ref": observation["elements"][0]["ref"]}})])
        assert result["status"] == "completed" and calls[-1] == query
        changed_scope = runtime.call("axis.observe", {"session_id": session, "scope": "diff", "since": observation["observation_id"]})
        assert changed_scope["error"]["code"] == "INVALID_SCOPE"
    finally:
        runtime.close()


@pytest.mark.parametrize("text", ["", "élève 中文 😀", "line1\r\nline2\r\n", "x"*MAX_EDIT_TEXT_UNITS])
def test_text_only_edit_exposes_exact_bounded_value(text):
    node = Element("CellEdit", "Edit")
    lengths = []
    def get_text(length):
        lengths.append(length)
        return text
    node.GetPattern = lambda kind: NS(DocumentRange=NS(GetText=get_text)) if kind == 3 else None
    item = read_controls(AUTO, UIA(), [node])["elements"][0]
    assert item["value"] == text
    assert item["value_source"] == "uia_text_pattern"
    assert lengths == [MAX_EDIT_TEXT_UNITS + 1]


@pytest.mark.parametrize("text", ["x"*(MAX_EDIT_TEXT_UNITS+1), "😀"*(MAX_EDIT_TEXT_UNITS//2+1)])
def test_text_prefix_is_not_accepted_as_complete_value(text):
    node = Element("CellEdit", "Edit")
    node.GetPattern = lambda kind: NS(DocumentRange=NS(GetText=lambda _: text)) if kind == 3 else None
    with pytest.raises(AxisError) as failure:
        read_controls(AUTO, UIA(), [node])
    assert failure.value.code == "OBSERVATION_INCOMPLETE"


@pytest.mark.parametrize("kind,value", [(1, ""), (1, "authoritative"), (2, 42)])
def test_native_value_patterns_take_priority_over_text(kind, value):
    node = Element("input", "Edit")
    def pattern(requested):
        assert requested != 3
        return NS(Value=value) if requested == kind else None
    node.GetPattern = pattern
    item = read_controls(AUTO, UIA(), [node])["elements"][0]
    assert item["value"] == value and "value_source" not in item


def test_password_never_reads_text_and_non_edit_does_not_request_it():
    password = Element("secret", "Edit")
    password.IsPassword = True
    password.GetPattern = lambda _: pytest.fail("Password pattern accessed")
    assert read_controls(AUTO, UIA(), [password])["elements"][0]["value"] == "[redacted]"
    node = Element("document", "Pane")
    def pattern(kind):
        assert kind != 3
        return None
    node.GetPattern = pattern
    assert read_controls(AUTO, UIA(), [node])["elements"][0]["value"] is None


def test_text_provider_failure_is_not_an_empty_value():
    node = Element("CellEdit", "Edit")
    def broken(_):
        raise RuntimeError("Provider vanished")
    node.GetPattern = lambda kind: NS(DocumentRange=NS(GetText=broken)) if kind == 3 else None
    with pytest.raises(RuntimeError, match="Provider vanished"):
        read_controls(AUTO, UIA(), [node])


@pytest.mark.parametrize("selected", [True, False])
def test_native_selection_is_read_not_inferred_from_focus(selected):
    node = Element("item")
    node.HasKeyboardFocus = not selected
    node.GetPattern = lambda kind: NS(IsSelected=selected) if kind == 4 else None
    item = read_controls(AUTO, UIA(), [node])["elements"][0]
    assert item["selected"] is selected
    assert item["focused"] is not selected


def test_absent_selection_pattern_is_unknown_not_false():
    assert read_controls(AUTO, UIA(), [Element("plain")])["elements"][0]["selected"] is None


@pytest.mark.parametrize("selected", [None, 0, 1, "true", "false"])
def test_invalid_native_selection_state_fails_observation(selected):
    node = Element("item")
    node.GetPattern = lambda kind: NS(IsSelected=selected) if kind == 4 else None
    with pytest.raises(AxisError) as failure:
        read_controls(AUTO, UIA(), [node])
    assert failure.value.code == "OBSERVATION_UNAVAILABLE"
