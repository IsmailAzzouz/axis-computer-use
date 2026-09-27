"""Job outcome/ownership fault boundaries; effects are simulated, not native."""
import json
import sqlite3
import threading

import pytest

from cu_suite.v2.contracts import AxisError, MAX_BYTES
from cu_suite.v2.runtime import Runtime, Policy
from .fake_platform import FakePlatform


@pytest.fixture
def state(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal"))
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    request = {"session_id": session, "idempotency_key": "effect", "steps": [{"id": "focus", "op": "focus"}]}
    yield runtime, pal, request
    runtime.close()


@pytest.mark.parametrize("fault", ["oversized", "unencodable"])
def test_result_delivery_fault_keeps_unknown_and_recoverable_job(state, monkeypatch, fault):
    runtime, pal, request = state
    original = runtime._run
    def run(**kwargs):
        result = original(**kwargs)
        result["fault"] = "x"*MAX_BYTES if fault == "oversized" else float("nan")
        return result
    monkeypatch.setattr(runtime, "_run", run)
    failed_reply = runtime.call("axis.run", request)
    assert failed_reply["status"] == "unknown"
    assert failed_reply["error"]["dispatch"] == "unknown"
    recovered = runtime.call("axis.job", {"idempotency_key": "effect", "action": "result"})
    assert recovered["status"] == "completed" and recovered["effects_verified"]
    assert failed_reply["job_id"] == recovered["job_id"]
    assert len(pal.calls) == 1


@pytest.mark.parametrize("error", [ValueError("private native content"), AxisError("INVALID_CURSOR", "private internal result")], ids=["unexpected", "typed"])
def test_run_result_lookup_error_does_not_erase_submitted_job(state, monkeypatch, error):
    runtime, pal, request = state
    original = runtime._job
    monkeypatch.setattr(runtime, "_job", lambda *a, **k: (_ for _ in ()).throw(error))
    result = runtime.call("axis.run", request)
    assert result["status"] == "unknown" and result["error"]["dispatch"] == "unknown"
    assert result["error"]["code"] == "RESULT_UNAVAILABLE"
    assert "private" not in json.dumps(result)
    monkeypatch.setattr(runtime, "_job", original)
    recovered = runtime.call("axis.job", {"idempotency_key": "effect", "action": "result"})
    assert recovered["job_id"] == result["job_id"] and recovered["effects_verified"]
    assert runtime.call("axis.run", request)["job_id"] == result["job_id"]
    assert len(pal.calls) == 1


def test_root_response_preserves_explicit_unknown_native_error(state):
    runtime, pal, request = state
    pal.capabilities = lambda: (_ for _ in ()).throw(AxisError("EFFECT_UNKNOWN", "Worker state unresolved", dispatch="unknown"))
    result = runtime.call("axis.run", request)
    assert result["status"] == "unknown"
    assert result["error"]["dispatch"] == "unknown" and not pal.calls


def test_sent_ack_is_not_overwritten_when_its_journal_write_fails(state):
    runtime, pal, request = state
    original = runtime._journal
    def journal(job, ordinal, step, phase):
        if phase == "sent":
            raise OSError("disk fault")
        return original(job, ordinal, step, phase)
    runtime._journal = journal
    result = runtime.call("axis.run", request)
    assert result["status"] == "unknown" and not result["effects_verified"]
    assert result["steps"][0]["dispatch"] == "sent"
    assert result["error"]["code"] == "JOURNAL_FAILED"
    assert runtime.call("axis.run", request)["steps"][0]["dispatch"] == "sent"
    assert len(pal.calls) == 1


def test_cleanup_snapshot_precedes_local_lease_release_and_is_immutable(state):
    runtime, pal, request = state
    locked = []
    snapshot = {"state": "confirmed", "owned_input_count": 0, "clipboard_pending": False}
    def cleanup_status():
        locked.append(runtime._input.locked())
        return snapshot
    pal.cleanup_status = cleanup_status
    result = runtime.call("axis.run", request)
    assert locked == [True]
    snapshot["state"] = "pending"
    recovered = runtime.call("axis.job", {"idempotency_key": "effect"})
    assert result["cleanup"]["state"] == recovered["cleanup"]["state"] == "confirmed"


def test_rejected_job_does_not_report_another_jobs_cleanup(state):
    runtime, pal, request = state
    entered, finish = threading.Event(), threading.Event()
    checks = []
    def dispatch(*args):
        entered.set()
        assert finish.wait(2)
        return {}
    pal.dispatch = dispatch
    pal.cleanup_status = lambda: checks.append(True) or {"state": "confirmed"}
    first = runtime.call("axis.run", {**request, "async": True})
    try:
        assert entered.wait(1)
        rejected = runtime.call("axis.run", {**request, "idempotency_key": "other"})
        assert rejected["error"]["code"] == "DESKTOP_BUSY"
        assert rejected["cleanup"]["state"] == "not_required"
        assert checks == []
    finally:
        finish.set()
        assert runtime._jobs[first["job_id"]].done.wait(1)


def test_finished_job_cannot_clear_next_owners_cancellation_route(state):
    runtime, pal, request = state
    class HandoffLock:
        def __init__(self): self.lock = threading.Lock()
        def acquire(self, **kwargs): return self.lock.acquire(**kwargs)
        def release(self):
            self.before = runtime._active_job
            self.lock.release()
            # Deterministic context switch: a newly admitted owner publishes here.
            runtime._active_job = "next-owner"
    lease = HandoffLock()
    runtime._input = lease
    runtime.call("axis.run", request)
    try:
        assert lease.before is None
        assert runtime._active_job == "next-owner"
    finally:
        runtime._active_job = None


def test_executor_start_failure_is_terminal_without_effect_or_shutdown_hang(state, monkeypatch):
    runtime, pal, request = state
    monkeypatch.setattr(threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("No threads")))
    result = runtime.call("axis.run", request)
    job = next(iter(runtime._jobs.values()))
    try:
        assert job.done.is_set()
        assert result["job_id"] == job.job_id
        assert result["status"] == "failed" and result["error"]["dispatch"] == "not_sent"
        assert result["error"]["code"] == "EXECUTOR_UNAVAILABLE" and not pal.calls
        stored = json.loads(runtime._db.execute("SELECT result FROM requests").fetchone()[0])
        assert stored["status"] == "failed"
    finally:
        # Old broken implementation left an accepted phantom job; no native work
        # exists in this test, so prevent fixture shutdown waiting for it.
        job.done.set()


def test_executor_raising_after_thread_start_cannot_dispatch(state, monkeypatch):
    runtime, pal, request = state
    original = threading.Thread.start
    threads = []
    def start(thread):
        original(thread)
        threads.append(thread)
        raise RuntimeError("Fault after OS thread start")
    monkeypatch.setattr(threading.Thread, "start", start)
    result = runtime.call("axis.run", request)
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert result["status"] == "failed" and result["error"]["dispatch"] == "not_sent"
    assert not pal.calls


def test_cleanup_metadata_does_not_persist_adapter_clipboard_content(state):
    runtime, pal, request = state
    pal.cleanup_status = lambda: {"state": "confirmed", "clipboard_data": "sensitive contents"}
    result = runtime.call("axis.run", request)
    assert result["cleanup"] == {"state": "confirmed"}
    assert "sensitive contents" not in str(runtime._db.execute("SELECT * FROM requests").fetchall())


@pytest.mark.parametrize("metadata", [[], {"state": "confirmed", "owned_input_count": 1}, {"state": "confirmed", "clipboard_pending": True}])
def test_unreconciled_cleanup_cannot_confirm_job(state, metadata):
    runtime, pal, request = state
    pal.cleanup_status = lambda: metadata
    result = runtime.call("axis.run", request)
    assert result["status"] == "unknown" and not result["effects_verified"]
    assert result["cleanup"]["state"] == "unknown"
    refused = runtime.call("axis.run", {**request, "idempotency_key": "new"})
    assert refused["error"]["code"] == "INPUT_UNRECONCILED"
    assert refused["error"]["dispatch"] == "not_sent"
    assert len(pal.calls) == 1
    assert runtime.call("axis.job", {"idempotency_key": "effect", "action": "result"})["status"] == "unknown"


def test_invalid_field_diagnostics_obey_the_same_text_budget(state):
    runtime, pal, request = state
    response = runtime.call("axis.run", {**request, "invalid"*5000: True})
    assert response["status"] == "failed" and response["error"]["dispatch"] == "not_sent"
    assert response["error"]["truncated"] and len(json.dumps(response).encode()) <= MAX_BYTES
    assert not pal.calls


@pytest.mark.parametrize("phase", ["request", "sent", "terminal"])
def test_failed_commit_is_rolled_back_and_prevents_further_admission(state, phase):
    runtime, pal, request = state
    connection = runtime._db
    class CommitFault:
        rollbacks = 0
        def execute(self, sql, parameters=()):
            self.last = (sql, parameters)
            return connection.execute(sql, parameters)
        def commit(self):
            sql, parameters = self.last
            match = ((phase == "request" and sql.startswith("INSERT INTO requests")) or
                     (phase == "sent" and "effects" in sql and parameters[-1] == "sent") or
                     (phase == "terminal" and sql.startswith("UPDATE requests")))
            if match:
                raise sqlite3.OperationalError("Injected commit failure")
            return connection.commit()
        def rollback(self):
            self.rollbacks += 1
            return connection.rollback()
        def __getattr__(self, name): return getattr(connection, name)
    proxy = CommitFault()
    runtime._db = proxy
    result = runtime.call("axis.run", request)
    assert proxy.rollbacks == 1
    if phase == "request":
        assert result["status"] == "failed" and result["error"]["dispatch"] == "not_sent"
        assert not pal.calls and not runtime._jobs
        assert connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    else:
        assert result["status"] == "unknown" and result["steps"][0]["dispatch"] == "sent"
        assert connection.execute("SELECT result FROM requests").fetchone()[0] is None
        assert len(pal.calls) == 1
        assert runtime.call("axis.run", request)["job_id"] == result["job_id"]
    blocked = runtime.call("axis.run", {**request, "idempotency_key": "later"})
    assert blocked["error"]["code"] == "JOURNAL_UNAVAILABLE"
    assert blocked["error"]["dispatch"] == "not_sent"
    assert len(pal.calls) == (0 if phase == "request" else 1)


def test_delayed_cancel_signal_cannot_cross_owner_handoff(state):
    runtime, pal, request = state
    cancelling, continue_cancel, releasing = threading.Event(), threading.Event(), threading.Event()
    signalled = []
    pal.release = releasing.set
    def cancel():
        cancelling.set()
        assert continue_cancel.wait(2)
        signalled.append(runtime._active_job)
    pal.cancel = cancel
    first = runtime.call("axis.run", {**request, "async": True,
                         "steps": [{"id": "wait", "op": "await", "args": {"condition": {"kind": "exists", "selector": {"name": "missing"}}}}]})
    # Wait for this job to own inputs using a bounded observation, not a sleep guess.
    import time
    deadline = time.monotonic()+1
    while runtime._active_job != first["job_id"] and time.monotonic() < deadline:
        time.sleep(.001)
    assert runtime._active_job == first["job_id"]
    canceller = threading.Thread(target=lambda: runtime.call("axis.job", {"job_id": first["job_id"], "action": "cancel"}))
    canceller.start()
    try:
        assert cancelling.wait(1) and releasing.wait(1)
        second = runtime.call("axis.run", {**request, "idempotency_key": "second"})
        assert second["error"]["code"] == "DESKTOP_BUSY"
        assert not pal.calls
    finally:
        continue_cancel.set()
        canceller.join(1)
        assert runtime._jobs[first["job_id"]].done.wait(1)
    assert signalled == [first["job_id"]]


def test_call_validated_before_close_cannot_later_admit_input(state, monkeypatch):
    from cu_suite.v2 import runtime as module
    runtime, pal, request = state
    entered, resume = threading.Event(), threading.Event()
    original = module.compile_steps
    def compile(steps):
        original(steps)
        entered.set()
        assert resume.wait(2)
    monkeypatch.setattr(module, "compile_steps", compile)
    replies = []
    caller = threading.Thread(target=lambda: replies.append(runtime.call("axis.run", request)))
    caller.start()
    try:
        assert entered.wait(1)
        runtime.close()
    finally:
        resume.set()
        caller.join(1)
    assert not caller.is_alive()
    assert replies[0]["error"]["code"] == "RUNTIME_CLOSED"
    assert replies[0]["error"]["dispatch"] == "not_sent"
    assert not pal.calls and not runtime._jobs
