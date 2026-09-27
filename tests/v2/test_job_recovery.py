import pytest
import subprocess
import sys
from cu_suite.v2.contracts import AxisError, SCHEMAS, validate
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform
from .test_runtime import click, run


@pytest.mark.parametrize("selector", [{}, {"job_id": "j", "idempotency_key": "k"}])
def test_job_requires_exactly_one_lookup_identity(selector):
    with pytest.raises(AxisError):
        validate(selector, SCHEMAS["axis.job"])


def test_expired_session_does_not_prevent_read_only_key_recovery(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        first = run(runtime, session, [click()], key="lost-response")
        runtime._sessions.clear()
        pal.closed = True
        recovered = runtime.call("axis.job", {"idempotency_key": "lost-response", "action": "result"})
        assert recovered["job_id"] == first["job_id"]
        assert recovered["steps"] == first["steps"]
        assert len(pal.calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("phase,dispatch", [("intention", "unknown"), ("sent", "sent")])
def test_interrupted_job_remains_queryable_without_relaunch(tmp_path, phase, dispatch):
    pal = FakePlatform()
    runtime = Runtime(pal, journal_path=str(tmp_path/"db"))
    try:
        runtime._db.execute("INSERT INTO requests VALUES (?,?,?,NULL)", ("key", "digest", "interrupted"))
        runtime._db.execute("INSERT INTO effects VALUES (?,?,?,?)", ("interrupted", 0, "click", phase))
        runtime._db.commit()
        result = runtime.call("axis.job", {"job_id": "interrupted", "action": "result"})
        assert result["status"] == "unknown"
        assert result["job_id"] == "interrupted"
        assert result["steps"][0]["dispatch"] == dispatch
        assert result["steps"][0]["verification"] == "unobservable"
        cancelled = runtime.call("axis.job", {"idempotency_key": "key", "action": "cancel"})
        assert cancelled["status"] == "unknown"
        assert pal.calls == []
    finally:
        runtime.close()


@pytest.mark.parametrize("phase,dispatch,effect_exists", [("after_intention", "unknown", False),
    ("after_input", "unknown", True), ("after_ack", "sent", True)])
def test_real_process_interruption_recovers_only_durable_evidence(tmp_path, phase, dispatch, effect_exists):
    path, effect = tmp_path/"journal.db", tmp_path/"effect.txt"
    child = subprocess.run([sys.executable, "-m", "tests.v2.interruption_fixture", "--journal", str(path),
                            "--effect", str(effect), "--phase", phase], capture_output=True, timeout=10)
    assert child.returncode == 23, child.stderr
    assert effect.exists() == effect_exists
    pal = FakePlatform()
    runtime = Runtime(pal, journal_path=str(path))
    try:
        result = runtime.call("axis.job", {"idempotency_key": "interrupted-request", "action": "result"})
        assert result["status"] == "unknown"
        assert result["steps"][0]["dispatch"] == dispatch
        assert result["steps"][0]["provenance"] == "durable_effect_journal"
        assert not result["effects_verified"]
        assert pal.calls == []
    finally:
        runtime.close()


def test_first_native_rejection_is_not_partial_execution(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        pal.effect_error = AxisError("FOCUS_DENIED", "No input sent")
        result = run(runtime, session, [{"id": "focus", "op": "focus"}])
        assert result["status"] == "failed"
        assert result["steps"][0]["dispatch"] == "not_sent"
    finally:
        runtime.close()
