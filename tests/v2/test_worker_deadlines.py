"""Worker admission and IPC deadline accounting, without desktop access."""
import threading
import time
import json
from types import SimpleNamespace

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2 import worker as module


class Connection:
    def __init__(self):
        self.sent = []

    def send(self, value, **kwargs): self.sent.append(value)
    def poll(self, timeout): return True
    def recv(self, **kwargs): return True, {"ack": True}


def supervisor(monkeypatch, delay):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    class Lock:
        def acquire(self, timeout):
            self.timeout = timeout
            clock.now += delay
            return True
        def release(self): pass
    obj = module.SupervisedPlatform.__new__(module.SupervisedPlatform)
    obj._timeout, obj._broken, obj._closing = 10, False, False
    obj._lock, obj._connection = Lock(), Connection()
    return obj, clock


def test_dispatch_lock_admission_cannot_use_response_grace(monkeypatch):
    worker, _ = supervisor(monkeypatch, delay=.2)
    with pytest.raises(AxisError) as error:
        worker.dispatch({}, "focus", {}, .1)
    assert error.value.code == "WORKER_BUSY" and error.value.dispatch == "not_sent"
    assert worker._lock.timeout == pytest.approx(.1)
    assert worker._connection.sent == []
    assert not worker._broken


def test_dispatch_sends_original_absolute_deadline_after_lock_wait(monkeypatch):
    worker, _ = supervisor(monkeypatch, delay=.04)
    assert worker.dispatch({}, "focus", {}, .1) == {"ack": True}
    method, args, deadline = worker._connection.sent[0]
    assert method == "dispatch" and args == ({}, "focus", {})
    assert deadline == pytest.approx(100.1)


@pytest.mark.parametrize("cancelled,elapsed", [(False, .2), (True, .01), (False, .04)])
def test_worker_checks_deadline_and_cancellation_after_ipc(monkeypatch, cancelled, elapsed):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    class Adapter:
        def __init__(self): self.calls = []
        def dispatch(self, *args):
            self.calls.append(args)
            return {"ack": True}
        def close(self): pass
    adapter = Adapter()
    monkeypatch.setattr(module.importlib, "import_module", lambda _: SimpleNamespace(Adapter=lambda: adapter))
    class Pipe(Connection):
        def __init__(self):
            super().__init__()
            self.messages = iter([("dispatch", ({}, "focus", {}), 100.1), ("_shutdown", (), None)])
        def recv(self):
            clock.now += elapsed
            return next(self.messages)
        def close(self): pass
    pipe, cancel = Pipe(), threading.Event()
    if cancelled: cancel.set()
    module._serve(pipe, "fixture", "Adapter", cancel)
    ok, result = pipe.sent[1]
    if cancelled or elapsed >= .1:
        assert not ok and not adapter.calls
        assert result["code"] == ("CANCELLED" if cancelled else "DEADLINE_EXCEEDED")
        assert result["dispatch"] == "not_sent"
    else:
        assert ok and adapter.calls[0][-1] == pytest.approx(.06)


def test_ownership_notifications_cannot_extend_reply_deadline(monkeypatch):
    worker, clock = supervisor(monkeypatch, delay=0)
    stopped = []
    worker._stop = lambda: stopped.append(True)
    def ownership(**kwargs):
        clock.now += .2
        return "ownership", [["key", 17]]
    worker._connection.recv = ownership
    # A continually readable notification stream still needs a hard deadline.
    with pytest.raises(AxisError) as error:
        worker.dispatch({}, "focus", {}, .1)
    assert error.value.dispatch == "unknown" and error.value.code == "EFFECT_UNKNOWN"
    assert stopped == [True] and len(worker._connection.sent) == 1


@pytest.mark.parametrize("reason", ["expired", "cancelled"])
def test_real_spawn_rejects_ineligible_dispatch_and_remains_usable(reason):
    worker = module.SupervisedPlatform("tests.v2.worker_fixture", "DeadlineFixture")
    try:
        if reason == "cancelled": worker.cancel()
        # Inject at the IPC boundary, after supervisor admission. An expired
        # message must be rejected by the child even if already in its pipe.
        deadline = time.monotonic() + (-1 if reason == "expired" else 2)
        worker._connection.send(("dispatch", ({}, "focus", {}), deadline))
        assert worker._connection.poll(2)
        ok, error = worker._connection.recv()
        assert not ok and error["dispatch"] == "not_sent"
        assert error["code"] == ("DEADLINE_EXCEEDED" if reason == "expired" else "CANCELLED")
        assert worker._rpc("dispatch_count") == 0
        worker.release_lease()
        result = worker.dispatch({"target_id": "test"}, "focus", {}, .5)
        assert 0 < result["remaining"] <= .5
        assert worker._rpc("dispatch_count") == 1
    finally:
        worker.close()


def test_real_dispatch_lock_wait_has_no_ack_grace():
    worker = module.SupervisedPlatform("tests.v2.worker_fixture", "DeadlineFixture")
    try:
        worker._lock.acquire()
        started = time.monotonic()
        try:
            with pytest.raises(AxisError) as error:
                worker.dispatch({}, "focus", {}, .03)
        finally:
            worker._lock.release()
        assert error.value.code == "WORKER_BUSY" and error.value.dispatch == "not_sent"
        assert time.monotonic()-started < .3
        assert worker._rpc("dispatch_count") == 0
        assert worker._process.is_alive() and not worker._broken
    finally:
        worker.close()


def test_stop_drains_unread_ownership_before_emergency_cleanup(tmp_path):
    report, ready = tmp_path / "cleanup.jsonl", tmp_path / "ready"
    worker = module.SupervisedPlatform("tests.v2.worker_fixture", "OwnershipFixture")
    try:
        worker._connection.send(("queued_ownership", (str(report), str(ready)), None))
        until = time.monotonic()+3
        while not ready.exists() and time.monotonic() < until:
            time.sleep(.005)
        assert ready.exists()
        assert worker._held == [] and worker._clipboard is None
        worker._stop()
        recorded = [json.loads(line) for line in report.read_text().splitlines()]
        assert len(recorded) == 1
        assert recorded[0]["held"] == [["key", 17], ["mouse", "left"]]
        assert recorded[0]["clipboard"]["sequence"] == 42
        assert worker.cleanup_status()["state"] == "confirmed"
        assert not worker._process.is_alive()
        worker._stop()
        assert len(report.read_text().splitlines()) == 1
    finally:
        worker.close()


@pytest.mark.parametrize("failure", ["partial-frame", "excess-backlog"])
def test_incomplete_ownership_drain_never_claims_cleanup_confirmed(failure):
    obj = module.SupervisedPlatform.__new__(module.SupervisedPlatform)
    obj._stopped, obj._broken = False, False
    obj._held, obj._clipboard, obj._cleanup_state = [], None, "not_required"
    obj._process = SimpleNamespace(is_alive=lambda: False, join=lambda _: None)
    class Pipe:
        count = 0
        def recv(self, **kwargs):
            self.count += 1
            if failure == "partial-frame": raise OSError("truncated IPC frame")
            return True, {}
        def close(self): pass
    obj._connection = Pipe()
    obj._stop()
    assert obj.cleanup_status()["state"] == "failed"
    assert obj._connection.count <= 1024
    with pytest.raises(AxisError, match="reconciled"):
        obj.release()


def test_unread_release_report_resolves_pending_cleanup():
    obj = module.SupervisedPlatform.__new__(module.SupervisedPlatform)
    obj._stopped, obj._broken = False, False
    obj._held, obj._clipboard, obj._cleanup_state = [["key", 17]], None, "pending"
    obj._process = SimpleNamespace(is_alive=lambda: False, join=lambda _: None)
    class Pipe:
        count = 0
        def recv(self, **kwargs):
            self.count += 1
            if self.count == 1: return "ownership", []
            raise EOFError
        def close(self): pass
    obj._connection = Pipe()
    obj._stop()
    assert obj.cleanup_status()["state"] == "confirmed" and not obj._held
    obj.release()
