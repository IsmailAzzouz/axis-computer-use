"""Regressions at safety boundaries, not assertions about implementation text."""
import threading
import time
import pytest
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform
from .test_runtime import click, run


@pytest.fixture
def state(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"db"))
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    yield runtime, pal, session
    runtime.close()


def test_known_unsupported_later_action_prevents_all_effects(state):
    runtime, pal, session = state
    pal.capabilities = lambda: {"actions": ["click"], "ocr": False}
    result = run(runtime, session, [click(), {"id": "focus", "op": "focus"}])
    assert result["error"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert pal.calls == []


def test_known_denied_target_prevents_earlier_effect(state):
    runtime, pal, session = state
    result = run(runtime, session, [click(), click(id="foreign", target_id="unapproved")])
    assert result["error"]["code"] == "POLICY_DENIED"
    assert pal.calls == []


def test_truncated_tree_does_not_prove_selector_unique(state):
    runtime, pal, session = state
    pal.coverage = "truncated"
    result = run(runtime, session, [click()])
    assert result["error"]["code"] == "OBSERVATION_INCOMPLETE"
    assert pal.calls == []


def test_negative_reference_index_cannot_target_last_element(state):
    runtime, pal, session = state
    observed = runtime.call("axis.observe", {"session_id": session})
    result = run(runtime, session, [click(args={"at": {"ref": observed["observation_id"]+":-1"}})])
    assert result["error"]["code"] == "STALE_REFERENCE"
    assert pal.calls == []


def test_mutation_revalidates_session_identity(state):
    runtime, pal, session = state
    pal.window["identity"] = "replacement-process"
    result = run(runtime, session, [click()])
    assert result["error"]["code"] == "STALE_TARGET"
    assert pal.calls == []


def test_result_not_terminal_until_cleanup_and_journal_finish(state):
    runtime, pal, session = state
    entered, finish = threading.Event(), threading.Event()
    def release():
        entered.set()
        assert finish.wait(2)
    pal.release = release
    try:
        response = run(runtime, session, [click()], **{"async": True})
        assert entered.wait(1)
        status = runtime.call("axis.job", {"job_id": response["job_id"], "action": "result"})
        assert status["status"] in ("accepted", "running", "finalizing")
        assert not status["effects_verified"]
    finally:
        finish.set()
    assert runtime._jobs[response["job_id"]].done.wait(1)


def test_invalid_native_key_is_rejected_before_prior_mutation(state):
    runtime, pal, session = state
    result = run(runtime, session, [click(), {"id": "bad", "op": "keys", "args": {"keys": ["not-a-key"]}, "verification": "dispatch_only"}])
    assert result["status"] == "failed"
    assert pal.calls == []


@pytest.mark.parametrize("kind,expected", [("value", ""), ("focused", True), ("enabled", True), ("visible", True)])
def test_property_predicate_requires_unique_complete_coverage(state, kind, expected):
    runtime, pal, session = state
    pal.coverage = "truncated"
    result = run(runtime, session, [{"id": "check", "op": "await", "args": {
        "condition": {"kind": kind, "selector": {"name": "Input"}, "expected": expected}}}])
    assert result["error"]["code"] == "OBSERVATION_INCOMPLETE"
    assert not result["effects_verified"]


@pytest.mark.parametrize("op", ["open_app", "focus"])
def test_after_dispatch_binding_failure_keeps_sent_step(state, op):
    runtime, pal, session = state
    runtime.policy = Policy(frozenset({"test"}), frozenset({"fixture"}))
    native_dispatch = pal.dispatch
    def dispatch(*args):
        output = native_dispatch(*args)
        pal.closed = True
        return output
    pal.dispatch = dispatch
    step = {"id": "effect", "op": op}
    if op == "open_app":
        step["args"] = {"app": "fixture"}
    result = run(runtime, session, [step])
    assert result["status"] == "partial"
    assert result["error"]["dispatch"] == "sent"
    assert result["steps"][0]["dispatch"] == "sent"
    assert result["steps"][0]["verification"] == "unobservable"
    again = run(runtime, session, [step])
    assert again["job_id"] == result["job_id"]
    assert len(pal.calls) == 1


def test_failed_native_lease_does_not_release_other_owners_inputs(state):
    runtime, pal, session = state
    pal.acquire_lease = lambda: (_ for _ in ()).throw(AxisError("DESKTOP_BUSY", "Owned elsewhere"))
    result = run(runtime, session, [click()])
    assert result["error"]["code"] == "DESKTOP_BUSY"
    assert pal.releases == 0


def test_release_failure_still_attempts_lease_cleanup(state):
    runtime, pal, session = state
    cleaned = []
    pal.release = lambda: (_ for _ in ()).throw(AxisError("CLEANUP_FAILED", "key up failed"))
    pal.release_lease = lambda: cleaned.append(True)
    result = run(runtime, session, [click()])
    assert result["status"] == "unknown"
    assert cleaned == [True]


@pytest.mark.parametrize("op,expected", [("maximize_window", "maximized"), ("minimize_window", "minimized"), ("restore_window", "normal")])
def test_window_state_requires_actual_readback(state, op, expected):
    runtime, pal, session = state
    pal.window["window_state"] = "normal" if expected != "normal" else "maximized"
    result = run(runtime, session, [{"id": "state", "op": op, "timeout": .05}])
    assert result["status"] == "partial"
    assert result["error"]["dispatch"] == "sent"
    assert not result["effects_verified"]
    assert len(pal.calls) == 1


@pytest.mark.parametrize("op,expected", [("maximize_window", "maximized"), ("minimize_window", "minimized"), ("restore_window", "normal")])
def test_window_state_verification_accepts_delayed_transition(state, op, expected):
    runtime, pal, session = state
    native_bind = pal.bind
    reads = []
    def bind(target_id):
        value = native_bind(target_id)
        if pal.calls:
            reads.append(True)
            value["window_state"] = expected if len(reads) >= 2 else "transitioning"
        return value
    pal.bind = bind
    result = run(runtime, session, [{"id": "state", "op": op}])
    assert result["status"] == "completed"
    assert result["effects_verified"]
    assert len(reads) >= 2
    assert result["steps"][0]["output"]["window_state"] == expected


def test_missing_window_state_is_not_success(state):
    runtime, pal, session = state
    result = run(runtime, session, [{"id": "state", "op": "restore_window"}])
    assert result["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert not result["effects_verified"]


def test_presence_does_not_prove_visibility(state):
    runtime, pal, session = state
    pal.elements[0]["visible"] = False
    result = run(runtime, session, [{"id": "visible", "op": "await", "args": {
        "timeout": .05, "condition": {"kind": "visible", "selector": {"name": "Input"}}}}])
    assert result["status"] == "failed"
    assert not result["effects_verified"]


def test_window_state_predicate_has_no_accessibility_dependency(state):
    runtime, pal, session = state
    pal.window["window_state"] = "minimized"
    pal.read_error = AxisError("OBSERVATION_UNAVAILABLE", "No accessibility")
    result = run(runtime, session, [{"id": "state", "op": "await", "args": {
        "condition": {"kind": "window_state", "expected": "minimized"}}}])
    assert result["effects_verified"]


def test_missing_capture_in_later_step_prevents_earlier_click(state):
    runtime, pal, session = state
    capabilities = pal.capabilities()
    pal.capabilities = lambda: {**capabilities, "capture": False}
    result = run(runtime, session, [click(), {"id": "settle", "op": "await_visual", "args": {"require_change": False}}])
    assert result["error"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert not pal.calls


def test_missing_accessibility_prevents_earlier_nonsemantic_focus(state):
    runtime, pal, session = state
    capabilities = pal.capabilities()
    pal.capabilities = lambda: {**capabilities, "accessibility": False}
    result = run(runtime, session, [{"id": "focus", "op": "focus"}, click()])
    assert result["error"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert not pal.calls


def test_semantic_locator_preserves_revalidation_context_for_native_worker(state):
    runtime, pal, session = state
    run(runtime, session, [click()])
    point = pal.calls[0][1]["at"]
    assert point["resolved_bounds"] == pal.elements[0]["bounds"]
    assert point["query"] == {"name": "Input"}
    assert point["native_id"] == "edit-1"
