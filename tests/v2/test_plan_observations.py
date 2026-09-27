"""Targeted readback inside a plan, with ephemeral UI data and durable outcomes."""
import copy
import json

import pytest

from cu_suite.v2.contracts import AxisError, MAX_BYTES
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform


@pytest.fixture
def engine(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path / "journal.db"))
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    yield runtime, pal, session
    runtime.close()


def read_plan(runtime, session, args=None, **options):
    return runtime.call("axis.run", {"session_id": session, "idempotency_key": "read-plan",
        "steps": [{"id": "read", "op": "observe", "args": args or {}}], **options})


def test_query_schema_and_same_call_text_without_native_input(engine):
    runtime, pal, session = engine
    pal.elements.append({**pal.elements[0], "native_id": "other", "role": "Button", "name": "Other"})
    schema = runtime.call("axis.observe", {"scope": "capabilities", "action": "observe"})["action"]["arguments"]
    assert "query" in schema["properties"]
    result = read_plan(runtime, session, {"query": {"role": "Edit"}})
    assert result["status"] == "completed", result
    output = result["steps"][0]["output"]
    assert output["session_id"] == session
    assert output["data_state"] == "available"
    assert [e["name"] for e in output["elements"]] == ["Input"]
    assert output["query"] == {"role": "Edit"} and output["coverage"] == "complete"
    assert not pal.calls


def test_readback_is_immutable_redacted_and_not_in_durable_journal(engine):
    runtime, pal, session = engine
    pal.elements[0]["value"] = "private-interface-value-中文"
    pal.elements.append({**pal.elements[0], "native_id": "password", "sensitive": True})
    first = read_plan(runtime, session)
    output = first["steps"][0]["output"]
    assert output["elements"][0]["value"] == "private-interface-value-中文"
    assert output["elements"][1]["value"] == "[redacted]"
    pal.elements[0]["value"] = "changed after snapshot"
    again = runtime.call("axis.job", {"job_id": first["job_id"], "action": "result"})
    assert again["steps"][0]["output"] == output
    stored = runtime._db.execute("SELECT result FROM requests").fetchone()[0]
    assert "private-interface-value" not in stored and "[redacted]" not in stored
    assert "elements" not in json.loads(stored)["steps"][0]["output"]
    # A returned mutable object must not corrupt future reads.
    output["elements"][0]["value"] = "client corruption"
    assert runtime.call("axis.job", {"job_id": first["job_id"], "action": "result"})["steps"][0]["output"] == again["steps"][0]["output"]


@pytest.mark.parametrize("coverage", ["complete", "truncated"])
def test_empty_query_retains_coverage_not_inferred_absence(engine, coverage):
    runtime, pal, session = engine
    pal.coverage = coverage
    result = read_plan(runtime, session, {"query": {"name": "not present"}})
    assert result["status"] == "completed", result
    output = result["steps"][0]["output"]
    assert output["elements"] == [] and output["coverage"] == coverage


def test_expired_snapshot_is_explicit_and_does_not_reobserve(engine):
    runtime, pal, session = engine
    first = read_plan(runtime, session)
    runtime._observations.clear()
    pal.read_error = AxisError("OBSERVATION_UNAVAILABLE", "Must not read live UI to reconstruct a past result")
    recovered = runtime.call("axis.job", {"job_id": first["job_id"], "action": "result"})
    output = recovered["steps"][0]["output"]
    assert output["data_state"] == "unavailable"
    assert "elements" not in output
    assert recovered["status"] == "completed"  # historical step, not new UI verification


def test_plan_observations_reuse_the_session(engine):
    runtime, pal, session = engine
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "repeat-read",
        "steps": [{"id": "loop", "op": "repeat", "args": {"count": 70,
            "steps": [{"id": "read", "op": "observe"}]}}]})
    assert result["status"] == "completed"
    assert len(runtime._sessions) == 1
    assert runtime._session(session)["target"]["target_id"] == "test"


def test_native_targeted_backend_receives_plan_query(engine):
    runtime, pal, session = engine
    capabilities = pal.capabilities()
    pal.capabilities = lambda: {**capabilities, "targeted_accessibility": True}
    calls = []
    def inspect(target, query=None):
        calls.append(copy.deepcopy(query))
        return {"elements": copy.deepcopy(pal.elements), "coverage": "complete", "epoch": pal.epoch}
    pal.inspect = inspect
    result = read_plan(runtime, session, {"query": {"automation_id": "input"}})
    assert result["status"] == "completed", result
    assert calls == [{"automation_id": "input"}]


def test_invalid_later_query_rejects_plan_before_any_input(engine):
    runtime, pal, session = engine
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "invalid-read",
        "steps": [{"id": "type", "op": "type_text", "args": {"text": "must not send"}, "verification": "dispatch_only"},
                  {"id": "read", "op": "observe", "args": {"query": {"typo": "Input"}}}]})
    assert result["status"] == "failed" and not pal.calls


def test_large_observation_returns_bounded_snapshot_pages(engine):
    runtime, pal, session = engine
    pal.elements = [{**pal.elements[0], "native_id": str(i), "name": f"input-{i}", "value": "文"*300} for i in range(40)]
    result = read_plan(runtime, session)
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_BYTES
    output = result["steps"][0]["output"]
    page = runtime.call("axis.observe", {"session_id": output["session_id"], "cursor": output["cursor"]})
    values = list(page["elements"])
    while page["next_cursor"]:
        page = runtime.call("axis.observe", {"session_id": output["session_id"], "cursor": page["next_cursor"]})
        values.extend(page["elements"])
    assert len(values) == 40


def test_restart_keeps_outcome_but_does_not_fabricate_readback(tmp_path):
    path = str(tmp_path / "journal.db")
    first = Runtime(FakePlatform(), policy=Policy(frozenset({"test"})), journal_path=path)
    try:
        session = first.call("axis.observe", {"target_id": "test"})["session_id"]
        result = read_plan(first, session)
    finally:
        first.close()
    pal = FakePlatform()
    pal.read_error = AxisError("UNEXPECTED_READ", "No fresh observation during recovery")
    second = Runtime(pal, journal_path=path)
    try:
        recovered = second.call("axis.job", {"job_id": result["job_id"], "action": "result"})
        assert recovered["status"] == "completed"
        assert recovered["steps"][0]["output"]["data_state"] == "unavailable"
        assert not pal.calls
    finally:
        second.close()


@pytest.mark.parametrize("prefix", ["json:{job}:0:0", "json:{job}:all:0", "items:{job}:0:elements:0", "itemjson:{job}:0:elements:0:0"])
def test_fragment_source_cannot_change_silently_after_snapshot_eviction(engine, prefix):
    runtime, pal, session = engine
    result = read_plan(runtime, session)
    runtime._observations.clear()
    page = runtime.call("axis.job", {"job_id": result["job_id"], "action": "result", "cursor": prefix.format(job=result["job_id"])})
    assert page["error"]["code"] == "OBSERVATION_EXPIRED"


def test_failed_read_after_sent_input_is_not_an_empty_success(engine):
    runtime, pal, session = engine
    pal.read_error = AxisError("OBSERVATION_UNAVAILABLE", "Provider gone")
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "read-failure",
        "steps": [{"id": "write", "op": "type_text", "args": {"text": "sent"}, "verification": "dispatch_only"},
                  {"id": "read", "op": "observe"}]})
    assert result["status"] == "partial" and not result["effects_verified"]
    assert result["steps"][0]["dispatch"] == "sent" and len(pal.calls) == 1
    assert result["error"]["code"] == "OBSERVATION_UNAVAILABLE"


def test_desktop_tree_step_requires_explicit_window_before_any_launch(engine):
    runtime, pal, session = engine
    desktop = runtime.call("axis.observe", {})["session_id"]
    result = read_plan(runtime, desktop)
    assert result["error"]["code"] == "INVALID_TARGET" and not pal.calls


def test_target_from_reuses_child_session_not_desktop(engine):
    runtime, pal, session = engine
    runtime.policy = Policy(frozenset({"test"}), frozenset({"fixture"}))
    desktop = runtime.call("axis.observe", {})["session_id"]
    result = runtime.call("axis.run", {"session_id": desktop, "idempotency_key": "launch-read",
        "steps": [{"id": "open", "op": "open_app", "args": {"app": "fixture"}},
                  {"id": "read", "op": "observe", "target_from": "open", "args": {"query": {"role": "Edit"}}},
                  {"id": "read-again", "op": "observe", "target_from": "open"}]})
    assert result["status"] == "completed", result
    first, second = [s["output"] for s in result["steps"] if s["op"] == "observe"]
    assert first["session_id"] == second["session_id"] != desktop
    assert runtime._session(desktop)["target"]["target_id"] == "desktop"


def test_old_v2_observation_descriptor_without_cursor_is_recoverable(engine):
    runtime, pal, session = engine
    result = read_plan(runtime, session)
    job = runtime._jobs[result["job_id"]]
    job.steps[0]["output"].pop("cursor")
    recovered = runtime.call("axis.job", {"job_id": job.job_id, "action": "result"})
    assert recovered["status"] == "completed"
    assert recovered["steps"][0]["output"]["data_state"] == "available"


def test_child_readback_session_refuses_identity_replacement(engine):
    runtime, pal, session = engine
    desktop = runtime.call("axis.observe", {})["session_id"]
    inspect = pal.inspect
    reads = []
    def replaced_after_read(target):
        reads.append(target["identity"])
        result = inspect(target)
        pal.window["identity"] = "replacement-process"
        return result
    pal.inspect = replaced_after_read
    result = runtime.call("axis.run", {"session_id": desktop, "idempotency_key": "identity-read",
        "steps": [{"id": "read", "op": "observe", "target_id": "test"},
                  {"id": "again", "op": "observe", "target_id": "test"}]})
    assert result["status"] == "partial" and result["error"]["code"] == "STALE_TARGET"
    assert reads == ["process-start-1"] and not pal.calls


@pytest.mark.parametrize("step", [
    {"op": "observe"},
    {"op": "repeat", "args": {"count": 1, "steps": [{"id": "child", "op": "observe"}]}},
    {"op": "if", "args": {"condition": {"kind": "exists", "selector": {"name": "Input"}},
                          "then": [{"id": "child", "op": "observe"}]}},
    {"op": "await", "args": {"condition": {"kind": "exists", "selector": {"name": "Input"}}}},
])
def test_local_steps_cannot_ignore_an_explicit_postcondition(engine, step):
    runtime, pal, session = engine
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "local-postcondition",
        "steps": [{**step, "id": "must-verify", "timeout": .02,
                   "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": "never"}}]})
    assert result["status"] in ("failed", "partial") and not result["effects_verified"]
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert result["steps"][-1]["id"] == "must-verify"
    assert result["steps"][-1]["verification"] == "unmet"
    assert not pal.calls


def test_local_postcondition_met_is_verified(engine):
    runtime, pal, session = engine
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "met-local",
        "steps": [{"id": "read", "op": "observe", "postcondition": {
            "kind": "value", "selector": {"name": "Input"}, "expected": ""}}]})
    assert result["status"] == "completed" and result["effects_verified"]
    assert result["steps"][0]["evidence"]["predicate"] == "value"
    assert not pal.calls


def test_local_postcondition_provider_crash_cannot_report_verified_or_leak_details(engine):
    runtime, pal, session = engine
    original = pal.inspect
    reads = []
    def inspect(target):
        reads.append(target)
        if len(reads) == 2:
            raise RuntimeError("sensitive-native-exception-details")
        return original(target)
    pal.inspect = inspect
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "broken-local",
        "steps": [{"id": "read", "op": "observe", "postcondition": {
            "kind": "value", "selector": {"name": "Input"}, "expected": ""}}]})
    assert result["status"] == "failed" and not result["effects_verified"]
    assert result["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert result["steps"][0]["verification"] == "unobservable"
    assert "sensitive-native-exception-details" not in json.dumps(result)
