"""Portable selection predicates: unknown is neither selected nor unselected."""
import copy

import pytest

from cu_suite.v2.contracts import AxisError, SCHEMAS, compile_steps, tool_definitions, validate
from cu_suite.v2.perception import tree_diff
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform


@pytest.mark.parametrize("selected", [True, False])
def test_selection_predicate_in_every_public_contract(selected):
    steps = [{"id": "check", "op": "await", "args": {"condition": {
        "kind": "selected", "selector": {"name": "Input"}, "expected": selected}}}]
    args = {"session_id": "s", "idempotency_key": "k", "steps": steps}
    validate(args, SCHEMAS["axis.run"])
    validate(args, next(t["inputSchema"] for t in tool_definitions() if t["name"] == "axis.run"))
    assert compile_steps(steps) == 1


@pytest.mark.parametrize("expected", [None, 0, 1, "true", "false"])
def test_selection_expectation_is_strict_boolean(expected):
    with pytest.raises(AxisError):
        compile_steps([{"id": "check", "op": "await", "args": {"condition": {
            "kind": "selected", "selector": {"name": "Input"}, "expected": expected}}}])


@pytest.mark.parametrize("selected", [True, False, None, 0, 1, "false"])
@pytest.mark.parametrize("expected", [True, False])
def test_selection_runtime_preserves_three_way_state(tmp_path, selected, expected):
    platform = FakePlatform()
    platform.elements[0]["selected"] = selected
    runtime = Runtime(platform, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"selection.db"))
    try:
        target = runtime._bind("test")
        condition = {"kind": "selected", "selector": {"name": "Input"}, "expected": expected}
        if type(selected) is bool:
            assert runtime._predicate(target, condition) is (selected is expected)
        else:
            with pytest.raises(AxisError) as failure:
                runtime._predicate(target, condition)
            assert failure.value.code == "UNOBSERVABLE"
        assert platform.calls == []
    finally:
        runtime.close()


def test_selection_state_changes_are_in_semantic_diff():
    before = {"target_id": "t", "identity": "i", "epoch": "e", "coverage": "complete",
              "elements": [{"native_id": "item", "selected": False}]}
    after = copy.deepcopy(before)
    after["elements"][0]["selected"] = True
    assert tree_diff(before, after)["changed"] == [{"native_id": "item", "fields": ["selected"]}]
    after["elements"][0]["selected"] = None
    assert tree_diff(before, after)["changed"] == [{"native_id": "item", "fields": ["selected"]}]
