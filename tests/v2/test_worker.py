import subprocess
import sys
import threading
import time
import pytest
import json
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.worker import SupervisedPlatform
from cu_suite.v2.runtime import Runtime, Policy


def test_public_import_does_not_initialize_native_backend():
    check = subprocess.run([sys.executable, "-c", "import cu_suite,sys; assert 'uiautomation' not in sys.modules; assert 'win32gui' not in sys.modules"], capture_output=True)
    assert check.returncode == 0, check.stderr


def test_resident_worker_reuses_state_and_stops():
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    try:
        pid = worker._process.pid
        assert worker.targets()[0]["target_id"] == "test"
        assert worker.bind("test")["identity"] == "process-start-1"
        assert worker._process.pid == pid
    finally:
        worker.close()
    assert not worker._process.is_alive()


@pytest.mark.parametrize("method", ["stall", "crash"])
def test_worker_failure_is_terminal_and_not_retried(method):
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    started = time.monotonic()
    with pytest.raises(AxisError):
        worker._rpc(method, timeout=.1)
    assert time.monotonic()-started < 1.5
    with pytest.raises(AxisError, match="restart"):
        worker.targets()
    worker.close()


def test_cancellation_does_not_wait_for_worker_rpc_lock():
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    results = []
    thread = threading.Thread(target=lambda: results.append(worker._rpc("cancel_wait")))
    thread.start()
    worker.cancel()
    thread.join(1)
    assert results == ["cancelled"]
    worker.close()


def test_worker_admission_timeout_does_not_kill_or_submit_to_busy_worker():
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    try:
        worker._lock.acquire()
        started = time.monotonic()
        try:
            with pytest.raises(AxisError) as error:
                worker._rpc("crash", timeout=.03)
        finally:
            worker._lock.release()
        assert error.value.code == "WORKER_BUSY"
        assert error.value.dispatch == "not_sent"
        assert time.monotonic()-started < .5
        assert worker._process.is_alive() and not worker._broken
        assert worker.bind("test")["identity"] == "process-start-1"
    finally:
        worker.close()


def test_successful_lease_cleanup_clears_cancellation_for_later_reads():
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    try:
        worker.acquire_lease()
        worker.cancel()
        assert worker._rpc("cancellation_pending")
        worker.release()
        worker.release_lease()
        assert not worker._rpc("cancellation_pending")
        assert worker.bind("test")["identity"] == "process-start-1"
    finally:
        worker.close()


@pytest.mark.parametrize("failure", ["crash", "stall"])
def test_worker_emergency_cleanup_releases_exact_reported_ownership(tmp_path, failure):
    report = tmp_path/"cleanup.jsonl"
    worker = SupervisedPlatform("tests.v2.worker_fixture", "OwnershipFixture")
    try:
        with pytest.raises(AxisError):
            worker._rpc("hold_and_fail", str(report), "success", failure, timeout=.1)
        entries = [json.loads(line) for line in report.read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["held"] == [["key", 17], ["mouse", "left"]]
        assert entries[0]["clipboard"]["sequence"] == 42
        assert worker.cleanup_status()["state"] == "confirmed"
        assert worker._held == [] and worker._clipboard is None
        assert not worker._process.is_alive()
        with pytest.raises(AxisError): worker.acquire_lease()
    finally:
        worker.close()


@pytest.mark.parametrize("behavior", ["fail", "crash", "stall"])
def test_emergency_cleanup_failure_is_not_hidden_or_retried(tmp_path, behavior):
    report = tmp_path/"cleanup.jsonl"
    worker = SupervisedPlatform("tests.v2.worker_fixture", "OwnershipFixture")
    with pytest.raises(AxisError):
        worker._rpc("hold_and_fail", str(report), behavior, "crash", timeout=.1)
    assert worker.cleanup_status()["state"] == "failed"
    assert len(worker._held) == 2 and worker._clipboard is not None
    for operation in (worker.release, worker.release_lease, worker.close):
        with pytest.raises(AxisError) as error: operation()
        assert error.value.code == "CLEANUP_FAILED"
        assert error.value.dispatch == "unknown"
    assert len(report.read_text().splitlines()) == 1


def test_graceful_shutdown_drains_release_notifications_before_emergency_cleanup(tmp_path):
    report = tmp_path/"must-not-exist.jsonl"
    worker = SupervisedPlatform("tests.v2.worker_fixture", "OwnershipFixture")
    assert worker._rpc("hold_and_fail", str(report), "success", "none") == "held"
    worker.close()
    assert not report.exists()
    assert worker._held == [] and worker._clipboard is None
    assert not worker._process.is_alive()


@pytest.mark.parametrize("behavior,state", [("success", "confirmed"), ("fail", "failed")])
def test_runtime_persists_cleanup_outcome_separately_from_unknown_effect(tmp_path, behavior, state):
    worker = SupervisedPlatform("tests.v2.worker_fixture", "OwnershipFixture")
    worker._rpc("configure_failure", str(tmp_path/"cleanup.jsonl"), behavior)
    runtime = Runtime(worker, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"db"))
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "crash",
                          "steps": [{"id": "effect", "op": "focus"}]})
    assert result["status"] == "unknown"
    assert result["cleanup"]["state"] == state
    assert not result["effects_verified"]
    recovered = runtime.call("axis.job", {"idempotency_key": "crash", "action": "result"})
    assert recovered["cleanup"] == result["cleanup"]
    stored = json.loads(runtime._db.execute("SELECT result FROM requests WHERE key='crash'").fetchone()[0])
    assert stored["cleanup"] == result["cleanup"]
    if behavior == "fail":
        assert result["error"]["code"] == "CLEANUP_FAILED"
        with pytest.raises(AxisError): runtime.close()
    else:
        runtime.close()
