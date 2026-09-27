from array import array
from types import SimpleNamespace as NS
import pytest

from .native_uia_search_probe import search


class Node:
    def __init__(self, number, name="Starter", parent=None):
        self.number, self.parent = number, parent
        self.CurrentName, self.CurrentControlType = name, 50007
    def GetRuntimeId(self):
        return (42, self.number)


class UIA:
    RawViewWalker = NS(GetParentElement=lambda node: node.parent)
    def CompareElements(self, a, b): return a is b
    def CreateAndCondition(self, a, b): return lambda node: a(node) and b(node)
    def CreateNotCondition(self, condition): return lambda node: not condition(node)
    def CreatePropertyCondition(self, prop, value):
        assert prop == 30000 and isinstance(value, array) and value.typecode == "i"
        return lambda node: tuple(value) == node.GetRuntimeId()


def fixture(names=("Starter", "Team", "Business")):
    root = Node(0)
    nodes = [Node(i+1, name, root) for i, name in enumerate(names)]
    def find(scope, condition):
        assert scope == 7
        return next((node for node in nodes if condition(node)), None)
    root.FindFirst = find
    return UIA(), root, nodes


def test_exclusions_are_typed_and_only_null_proves_completion():
    uia, root, _ = fixture()
    result = search(uia, root, lambda _: True)
    assert result["complete"] and result["calls"] == 4
    assert [m["name"] for m in result["matches"]] == ["Starter", "Team", "Business"]


def test_cache_path_does_not_call_plain_find():
    uia, root, _ = fixture()
    find, cache = root.FindFirst, object()
    def cached(scope, condition, request):
        assert request is cache
        return find(scope, condition)
    root.FindFirstBuildCache = cached
    root.FindFirst = lambda *_: (_ for _ in ()).throw(AssertionError("plain path"))
    assert search(uia, root, lambda _: True, cache=cache)["complete"]


def test_duplicate_or_scope_escape_is_not_exhaustion():
    uia, root, nodes = fixture()
    root.FindFirst = lambda *_: nodes[0]
    result = search(uia, root, lambda _: True)
    assert not result["complete"] and result["error"] == "exclusion_ignored"
    nodes[0].parent = None
    result = search(uia, root, lambda _: True)
    assert not result["matches"] and result["error"] == "scope_escape"


def test_budget_is_not_complete_even_if_all_items_seen():
    uia, root, _ = fixture()
    result = search(uia, root, lambda _: True, limit=3)
    assert not result["complete"] and result["error"] == "budget_exhausted"
    assert len(result["matches"]) == 3


def test_names_and_provider_errors_are_redacted():
    uia, root, _ = fixture(("private",))
    assert search(uia, root, lambda _: True)["matches"][0]["name"] == "[not retained]"
    root.FindFirst = lambda *_: (_ for _ in ()).throw(ValueError("private"))
    result = search(uia, root, lambda _: True)
    assert not result["complete"] and result["error"] == "ValueError"


def test_late_null_reply_does_not_claim_completion(monkeypatch):
    from . import native_uia_search_probe as module
    clock = [0.]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    uia, root, _ = fixture()
    def late(*_):
        clock[0] = 9.
        return None
    root.FindFirst = late
    result = search(uia, root, lambda _: True, seconds=8)
    assert not result["complete"] and result["error"] == "budget_exhausted"


def test_ancestry_cycle_does_not_expose_name():
    uia, root, nodes = fixture()
    nodes[0].parent = nodes[0]
    result = search(uia, root, lambda _: True)
    assert not result["complete"] and result["error"] == "ancestry_limit"
    assert not result["matches"]


def test_invalid_runtime_id_is_rejected():
    uia, root, nodes = fixture()
    nodes[0].GetRuntimeId = lambda: ()
    result = search(uia, root, lambda _: True)
    assert not result["complete"] and result["error"] == "invalid_runtime_id"


def test_native_com_error_keeps_only_type_and_hresult():
    class COMError(Exception):
        hresult = -2147220991
    uia, root, _ = fixture()
    root.FindFirst = lambda *_: (_ for _ in ()).throw(COMError("private UI text"))
    result = search(uia, root, lambda _: True)
    assert not result["complete"] and result["calls"] == 1
    assert result["error"] == {"type": "COMError", "hresult": "0x80040201"}


@pytest.mark.parametrize("failure", [EOFError, BrokenPipeError])
def test_supervisor_keeps_terminal_error_when_windows_poll_reports_closed_pipe(monkeypatch, failure):
    from . import native_uia_search_probe as module
    messages = [{"error": {"type": "ValueError", "message": "test_target_not_unique"}}]
    closed = []
    def poll(_):
        if messages:
            return True
        raise failure()
    incoming = NS(poll=poll, recv=lambda: messages.pop(0), close=lambda: closed.append("incoming"))
    outgoing = NS(close=lambda: closed.append("outgoing"))
    process = NS(start=lambda: None, pid=123, join=lambda _: None, is_alive=lambda: False,
                 exitcode=0, close=lambda: closed.append("process"))
    context = NS(Pipe=lambda **_: (incoming, outgoing), Process=lambda **_: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _: context)
    result = module.supervise(123, "list_items", False, lambda _: None)
    assert result["error"]["message"] == "test_target_not_unique"
    assert result["exitcode"] == 0 and "supervisor_error" not in result
    assert {"incoming", "outgoing", "process"} <= set(closed)
