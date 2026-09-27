"""Cyclic walkers recover only through exhaustive bounded raw-tree search."""
from array import array
from types import SimpleNamespace as NS

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.windows_accessibility import read_controls
from .test_targeted_accessibility import AUTO, Element, UIA


class CyclicFilteredUIA(UIA):
    def __init__(self, root):
        self.root = root
        self.filtered_calls = self.search_calls = 0
        self.search_hook = None
        self.cache = None
        self.nodes = [root, *root.children]
        for index, node in enumerate(self.nodes):
            node.GetRuntimeId = lambda index=index: (42, index)
        def find(scope, condition, cache):
            self.search_calls += 1
            assert scope == 7 and cache is self.cache
            assert cache.TreeScope == 1 and cache.TreeFilter(None) is True
            if self.search_hook:
                return self.search_hook(condition)
            return next((node for node in self.nodes if condition(node)), None)
        root.FindFirstBuildCache = find

    def CreateCacheRequest(self):
        self.cache = NS()
        return self.cache

    def CreateNotCondition(self, condition):
        return lambda node: not condition(node)

    def CreatePropertyCondition(self, prop, value):
        if prop == "runtime_id":
            assert isinstance(value, array) and value.typecode == "i" and value.itemsize == 4
            return lambda node: tuple(value) == node.GetRuntimeId()
        return super().CreatePropertyCondition(prop, value)

    def CreateTreeWalker(self, condition):
        original = super().CreateTreeWalker(condition)
        def next_filtered(node):
            self.filtered_calls += 1
            return original.GetNextSiblingElement(node) or self.root.children[0]
        return NS(GetFirstChildElement=original.GetFirstChildElement,
                  GetNextSiblingElement=next_filtered)


def fixture():
    root = Element("popup", children=[Element("Starter", "Edit"), Element("Team", "Edit"), Element("Business", "Edit")])
    return root, CyclicFilteredUIA(root)


def test_cycle_recovers_only_after_exhausting_raw_search_with_typed_exclusions():
    root, uia = fixture()
    result = read_controls(AUTO, uia, [root], {"role": "Edit"})
    assert result["coverage"] == "complete"
    assert [node["name"] for node in result["elements"]] == ["Starter", "Team", "Business"]
    assert uia.filtered_calls == 3 and uia.search_calls == 4


def test_provider_ignoring_exclusions_is_an_error_not_exhaustion():
    root, uia = fixture()
    uia.search_hook = lambda _: root.children[0]
    with pytest.raises(AxisError, match="cycle"):
        read_controls(AUTO, uia, [root], {"role": "Edit"})
    assert uia.search_calls == 2


def test_recovery_does_not_reset_node_budget_or_claim_completion_at_exact_limit():
    root, uia = fixture()
    result = read_controls(AUTO, uia, [root], {"role": "Edit"}, limit=4)
    assert result["coverage"] == "truncated"
    assert [item["name"] for item in result["elements"]] == ["Starter"]
    assert uia.search_calls == 1


def test_read_error_does_not_start_recovery():
    root, uia = fixture()
    root.FindFirst = lambda *_: (_ for _ in ()).throw(RuntimeError("provider failed"))
    with pytest.raises(RuntimeError):
        read_controls(AUTO, uia, [root], {"role": "Edit"})
    assert uia.search_calls == 0


def test_ordinary_filtered_walk_does_not_require_search_api():
    root, _ = fixture()
    assert read_controls(AUTO, UIA(), [root], {"role": "Edit"})["coverage"] == "complete"


def test_recovery_does_not_reset_elapsed_deadline(monkeypatch):
    from cu_suite.v2.platforms import windows_accessibility as module
    root, uia = fixture()
    monkeypatch.setattr(module.time, "monotonic", lambda: 10. if uia.filtered_calls >= 3 else 0.)
    result = read_controls(AUTO, uia, [root], {"role": "Edit"}, seconds=1)
    assert result["coverage"] == "truncated"
    assert result["elements"] == [] and uia.search_calls == 0


def test_recovery_preserves_completed_roots_without_duplicate_partial_results():
    root, uia = fixture()
    stable = Element("stable", "Edit")
    result = read_controls(AUTO, uia, [stable, root], {"role": "Edit"})
    assert result["coverage"] == "complete"
    assert [item["name"] for item in result["elements"]] == ["stable", "Starter", "Team", "Business"]


def test_search_rejects_scope_escape_before_foreign_fields():
    root, uia = fixture()
    foreign = Element("private", "Edit")
    foreign.GetPattern = lambda *_: pytest.fail("Foreign value read")
    uia.search_hook = lambda _: foreign
    with pytest.raises(AxisError, match="escaped"):
        read_controls(AUTO, uia, [root], {"role": "Edit"})


def test_missing_known_matches_is_not_successful_absence_or_uniqueness():
    root, uia = fixture()
    uia.search_hook = lambda _: None
    with pytest.raises(AxisError, match="contradicted"):
        read_controls(AUTO, uia, [root], {"role": "Edit"})


def test_null_return_after_deadline_is_truncated(monkeypatch):
    from cu_suite.v2.platforms import windows_accessibility as module
    root, uia = fixture()
    monkeypatch.setattr(module.time, "monotonic", lambda: 9. if uia.search_calls >= 4 else 0.)
    result = read_controls(AUTO, uia, [root], {"role": "Edit"}, seconds=8)
    assert result["coverage"] == "truncated" and len(result["elements"]) == 3


def test_cancel_during_search_never_returns_complete():
    root, uia = fixture()
    cancel = NS(is_set=lambda: uia.search_calls >= 1)
    with pytest.raises(AxisError, match="cancelled"):
        read_controls(AUTO, uia, [root], {"role": "Edit"}, cancel=cancel)
    assert uia.search_calls == 1


def test_search_com_failure_is_sanitized_and_not_retried():
    from .test_uia_provider_diagnostics import FakeCOMError
    root, uia = fixture()
    uia.search_hook = lambda _: (_ for _ in ()).throw(FakeCOMError())
    with pytest.raises(AxisError, match="search failed.*0x80040201") as caught:
        read_controls(AUTO, uia, [root], {"role": "Edit"}, provider_errors=(FakeCOMError,))
    assert "SECRET" not in str(caught.value) and uia.search_calls == 1


@pytest.mark.parametrize("identity", [(), (True,), (2**31,), (-2**31-1,), (1,)*65])
def test_invalid_runtime_identity_cannot_make_an_exclusion(identity):
    root, uia = fixture()
    original = root.children[0].GetRuntimeId
    root.children[0].GetRuntimeId = lambda: identity if uia.search_calls else original()
    with pytest.raises(AxisError, match="runtime identity"):
        read_controls(AUTO, uia, [root], {"role": "Edit"})
