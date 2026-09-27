"""Smoke driver contracts; these tests are not native Excel evidence."""
import json
from types import SimpleNamespace

import pytest

from cu_suite.v2.contracts import compile_steps
from .native_excel_smoke import FORMULA_BAR, SmokeFailed, require_element, require_job, selection_checks, selection_steps, write_steps
from .native_harness import NativeHarness


def test_excel_plan_verifies_edit_buffer_then_committed_cell_without_dispatch_only():
    steps = write_steps()
    assert compile_steps(steps) == 8
    for edit, commit in zip(steps[::2], steps[1::2]):
        assert edit["postcondition"]["selector"] == FORMULA_BAR
        assert edit["postcondition"]["expected"] == edit["args"]["text"]
        assert commit["postcondition"]["selector"] == edit["args"]["at"]["selector"]
        assert "verification" not in edit and "verification" not in commit
    assert steps[-2]["args"]["text"] == "=A2*B1"
    assert steps[-1]["postcondition"]["expected"] == "42"


def test_range_plan_checks_members_and_neighbours_without_claiming_global_completeness():
    assert compile_steps(selection_steps()) == 10
    checks = {s["args"]["condition"]["selector"]["automation_id"]: s["args"]["condition"]["expected"] for s in selection_checks()}
    assert checks == {"A1": True, "A2": True, "B1": True, "B2": True, "C1": False, "C2": False, "A3": False, "B3": False}
    assert all(s.get("verification") != "dispatch_only" for s in selection_steps())


@pytest.mark.parametrize("result", [
    {}, {"status": "completed", "effects_verified": False},
    {"status": "unknown", "effects_verified": True},
    {"status": "completed", "effects_verified": True, "next_cursor": "more"},
])
def test_driver_never_accepts_incomplete_or_unverified_job(result):
    with pytest.raises(SmokeFailed):
        require_job(result)


@pytest.mark.parametrize("coverage,elements,cursor", [
    ("truncated", [{"name": "Input"}], None), ("complete", [], None),
    ("complete", [{"name": "Input"}, {"name": "Input"}], None),
    ("complete", [{"name": "Input"}], "more"),
])
def test_profile_requires_unique_complete_observation(coverage, elements, cursor):
    with pytest.raises(SmokeFailed):
        require_element({"coverage": coverage, "elements": elements, "next_cursor": cursor}, {"name": "Input"})


def test_harness_persists_original_key_before_call_even_when_reply_is_lost(tmp_path):
    host = NativeHarness.__new__(NativeHarness)
    host.output, host.trace = tmp_path, []
    def fail(request):
        saved = json.loads((tmp_path/"trace.jsonl").read_text())
        assert saved["event"] == "request" and saved["request"] == request
        raise RuntimeError("reply lost")
    host.mcp = SimpleNamespace(handle_request=fail)
    with pytest.raises(RuntimeError, match="reply lost"):
        host.call("axis.run", {"idempotency_key": "original-key"})
    assert not host.trace
    assert json.loads((tmp_path/"trace.jsonl").read_text())["request"]["params"]["arguments"]["idempotency_key"] == "original-key"


def test_harness_preserves_schema_error_without_job_status(tmp_path):
    host = NativeHarness.__new__(NativeHarness)
    host.output, host.trace = tmp_path, []
    error = {"error": {"code": "INVALID_REQUEST", "dispatch": "not_sent"}}
    host.mcp = SimpleNamespace(handle_request=lambda _: {"result": {"structuredContent": error}})
    assert host.finish(host.call("axis.run", {})) == error
    assert [json.loads(line)["event"] for line in (tmp_path/"trace.jsonl").read_text().splitlines()] == ["request", "response"]
