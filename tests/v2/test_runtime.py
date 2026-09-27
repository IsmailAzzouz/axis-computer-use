import json
import threading
import time
import pytest

from cu_suite.v2.contracts import AxisError, MAX_BYTES, compile_steps, tool_definitions
from cu_suite.v2.runtime import Runtime, Policy
from .fake_platform import FakePlatform


@pytest.fixture
def setup(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"}), frozenset({"fixture"})), journal_path=str(tmp_path/"journal.db"))
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    yield runtime, pal, session
    runtime.close()


def run(runtime, session, steps, key="key", **kwargs):
    return runtime.call("axis.run", {"session_id": session, "steps": steps, "idempotency_key": key, **kwargs})


def click(**kwargs):
    return {"id": "click", "op": "click", "args": {"at": {"selector": {"name": "Input"}}}, "verification": "dispatch_only", **kwargs}


def test_six_tools():
    assert {x["name"] for x in tool_definitions()} == {"axis.help", "axis.targets", "axis.observe", "axis.run", "axis.job", "axis.capture"}
    assert all(x["inputSchema"]["additionalProperties"] is False for x in tool_definitions())


@pytest.mark.parametrize("patch", [
    {"op": "eval"}, {"args": {"x": 10, "y": 20}}, {"args": {"at": {"point": {"space": "frame", "x": 2, "y": 3}}}},
    {"args": {"at": {"selector": {}}}}, {"args": {"at": {"ref": "x", "selector": {"name": "a"}}}},
    {"target_from": "future"}, {"target_from": "future", "target_id": "test"},
    {"args": {"at": {"point": {"space": "desktop", "x": float("nan"), "y": 3}}}},
])
def test_invalid_plan_has_no_effect(setup, patch):
    runtime, pal, session = setup
    result = run(runtime, session, [click(), {**click(id="bad"), **patch}])
    assert result["status"] == "failed"
    assert not pal.calls


def test_type_verified_and_not_persisted_in_journal(setup):
    runtime, pal, session = setup
    text = "élève 中文 😀"
    result = run(runtime, session, [{"id": "type", "op": "type_text", "args": {"text": text},
        "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": text}}])
    assert result["status"] == "completed" and result["effects_verified"]
    assert pal.elements[0]["value"] == text
    assert text not in str(runtime._db.execute("SELECT * FROM requests").fetchall())


def test_dispatch_only_never_proves_effect(setup):
    runtime, pal, session = setup
    result = run(runtime, session, [click()])
    assert result["status"] == "completed"
    assert not result["effects_verified"]
    assert result["steps"][0]["verification"] == "unobservable"


def test_idempotency_suppresses_repeat(setup):
    runtime, pal, session = setup
    first = run(runtime, session, [click()])
    again = run(runtime, session, [click()])
    assert first["job_id"] == again["job_id"]
    assert len(pal.calls) == 1
    assert run(runtime, session, [click(id="different")])["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_unknown_dispatch_not_retried(setup):
    runtime, pal, session = setup
    pal.effect_error = AxisError("EFFECT_UNKNOWN", "Lost ack", dispatch="unknown")
    result = run(runtime, session, [click(), click(id="second")])
    assert result["status"] == "unknown"
    assert result["steps"][0]["dispatch"] == "unknown"
    run(runtime, session, [click(), click(id="second")])
    assert len(pal.calls) == 1
    assert pal.releases == 1


def test_unknown_request_survives_restart(tmp_path):
    path = str(tmp_path/"journal.db")
    pal = FakePlatform()
    policy = Policy(frozenset({"test"}))
    first = Runtime(pal, policy=policy, journal_path=path)
    session = first.call("axis.observe", {"target_id": "test"})["session_id"]
    result = run(first, session, [click()])
    first._db.execute("UPDATE requests SET result=NULL")
    first._db.commit()
    first.close()
    second = Runtime(pal, policy=policy, journal_path=path)
    session = second.call("axis.observe", {"target_id": "test"})["session_id"]
    recovered = run(second, session, [click()])
    assert recovered["status"] == "unknown" and recovered["job_id"] == result["job_id"]
    assert len(pal.calls) == 1
    second.close()


def test_refs_are_contextual_and_revalidated(setup):
    runtime, pal, session = setup
    obs = runtime.call("axis.observe", {"session_id": session})
    ref = obs["elements"][0]["ref"]
    pal.epoch = "different-document"
    result = run(runtime, session, [click(args={"at": {"ref": ref}})])
    assert result["error"]["code"] == "STALE_REFERENCE"
    assert not pal.calls


def test_duplicate_labels_do_not_select_arbitrary_element(setup):
    runtime, pal, session = setup
    pal.elements.append({**pal.elements[0], "native_id": "edit-2"})
    result = run(runtime, session, [click()])
    assert result["error"]["code"] == "AMBIGUOUS_TARGET"
    assert not pal.calls


def test_frame_transform_and_staleness(setup):
    runtime, pal, session = setup
    frame = runtime.call("axis.capture", {"session_id": session, "region": [10, 20, 50, 60]})
    step = click(args={"at": {"point": {"space": "frame", "frame_id": frame["frame_id"], "x": 5, "y": 7}}})
    result = run(runtime, session, [step])
    assert result["status"] == "completed"
    assert pal.calls[0][1]["at"] == {"x": -85, "y": 27}
    pal.window["geometry_id"] = "changed"
    result = run(runtime, session, [step], key="new")
    assert result["error"]["code"] == "STALE_FRAME"


def test_cross_session_frame_rejected(setup):
    runtime, pal, session = setup
    frame = runtime.call("axis.capture", {"session_id": session})
    other = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    result = run(runtime, other, [click(args={"at": {"point": {"space": "frame", "frame_id": frame["frame_id"], "x": 5, "y": 7}}})])
    assert result["error"]["code"] == "STALE_FRAME"


@pytest.mark.parametrize("coverage,code", [("truncated", "OBSERVATION_INCOMPLETE"), ("unavailable", "OBSERVATION_UNAVAILABLE")])
def test_absence_requires_coverage(setup, coverage, code):
    runtime, pal, session = setup
    pal.coverage = coverage
    result = run(runtime, session, [{"id": "wait", "op": "await", "args": {"condition": {"kind": "absent", "selector": {"name": "Missing"}}}}])
    assert result["error"]["code"] == code


def test_failed_inspection_not_successful_absence(setup):
    runtime, pal, session = setup
    pal.read_error = AxisError("WORKER_TIMEOUT", "failed")
    result = run(runtime, session, [{"id": "wait", "op": "await", "args": {"condition": {"kind": "absent", "selector": {"name": "Missing"}}}}])
    assert result["error"]["code"] == "WORKER_TIMEOUT"


def test_wait_timeout_is_failure(setup):
    runtime, pal, session = setup
    result = run(runtime, session, [{"id": "wait", "op": "await", "args": {"timeout": .02, "condition": {"kind": "exists", "selector": {"name": "Missing"}}}}])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"


def test_cancel_and_exclusive_input(setup):
    runtime, pal, session = setup
    steps = [{"id": "wait", "op": "await", "args": {"condition": {"kind": "exists", "selector": {"name": "Missing"}}}}]
    first = run(runtime, session, steps, **{"async": True})
    limit = time.monotonic()+1
    while runtime._jobs[first["job_id"]].status == "accepted" and time.monotonic() < limit: time.sleep(.001)
    blocked = run(runtime, session, [click()], key="second")
    assert blocked["error"]["code"] == "DESKTOP_BUSY"
    runtime.call("axis.job", {"job_id": first["job_id"], "action": "cancel"})
    assert runtime._jobs[first["job_id"]].done.wait(1)
    assert runtime.call("axis.job", {"job_id": first["job_id"]})["status"] == "cancelled"
    assert not pal.calls


def test_host_permissions_not_model_arguments(setup):
    runtime, pal, session = setup
    assert runtime.call("axis.run", {"session_id": session, "idempotency_key": "a", "steps": [click()], "disable_security": True})["status"] == "failed"
    result = run(runtime, session, [{"id": "kill", "op": "terminate_app"}])
    assert result["error"]["code"] == "POLICY_DENIED"
    assert not pal.calls


def test_open_output_can_target_next_action(setup):
    runtime, pal, _ = setup
    session = runtime.call("axis.observe", {})["session_id"]
    result = run(runtime, session, [{"id": "launch", "op": "open_app", "args": {"app": "fixture"}}, {"id": "focus", "op": "focus", "target_from": "launch"}])
    assert result["status"] == "completed" and result["effects_verified"]


def test_journal_failure_prevents_dispatch(setup):
    runtime, pal, session = setup
    runtime._journal = lambda *args: (_ for _ in ()).throw(OSError("disk full"))
    result = run(runtime, session, [click()])
    assert result["status"] == "unknown"
    assert not pal.calls


def test_budget_compiler_counts_repeats():
    with pytest.raises(AxisError):
        compile_steps([{"id": "loop", "op": "repeat", "args": {"count": 256, "steps": [click(), click(id="two")]}}])


def test_readonly_default(tmp_path):
    runtime = Runtime(FakePlatform(), journal_path=str(tmp_path/"r.db"))
    assert runtime.call("axis.targets")["targets"] == []
    assert runtime.call("axis.observe", {"target_id": "test"})["error"]["code"] == "POLICY_DENIED"
    runtime.close()


def test_observation_pagination_is_immutable(setup):
    runtime, pal, session = setup
    pal.elements = [{**pal.elements[0], "native_id": str(i), "name": "name"*100} for i in range(100)]
    first = runtime.call("axis.observe", {"session_id": session})
    assert len(json.dumps(first).encode()) <= MAX_BYTES
    assert first["next_cursor"]
    pal.elements = []
    next_page = runtime.call("axis.observe", {"session_id": session, "cursor": first["next_cursor"]})
    assert next_page["elements"]


def test_sensitive_observation_redacted(setup):
    runtime, pal, session = setup
    pal.elements[0].update(sensitive=True, value="password", name="secret-name")
    result = runtime.call("axis.observe", {"session_id": session})
    assert "password" not in json.dumps(result) and "secret-name" not in json.dumps(result)
