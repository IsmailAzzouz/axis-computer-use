"""Real private pipes and controlled stalled transfers; no desktop input."""
import pickle
import threading
import time
import pytest
from cu_suite.v2.worker_channel import WorkerChannel


@pytest.fixture
def pair():
    left, right = WorkerChannel.pair()
    yield left, right
    right.close()
    left.close()


def test_ready_poll_does_not_make_full_receive_unbounded(pair, monkeypatch):
    left, right = pair
    monkeypatch.setattr(left.raw, "poll", lambda _: True)
    assert left.poll(.01)
    start = time.monotonic()
    with pytest.raises(TimeoutError): left.recv(deadline=start+.03)
    assert time.monotonic()-start < .5
    pending = left._pending
    with pytest.raises(TimeoutError): left.recv(deadline=time.monotonic()+.01)
    assert left._pending is pending
    right.send(("ownership", [["key", 17]]))
    assert left.recv(deadline=time.monotonic()+.5) == ("ownership", [["key", 17]])
    assert left._pending is None


def test_backpressure_bounds_send(pair):
    left, _ = pair
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        left.send(b"x"*(16*1024*1024), deadline=started+.03)
    assert time.monotonic()-started < 1
    pending = left._pending
    with pytest.raises(OSError, match="unresolved"):
        left.send("never replay this")
    assert left._pending is pending


def test_large_frame_roundtrip(pair):
    left, right = pair
    value = {"text": "élève 中文", "data": b"x"*(1024*1024)}
    errors = []
    def send():
        try: left.send(value, deadline=time.monotonic()+2)
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert right.recv(deadline=time.monotonic()+2) == value
    finally:
        thread.join(3)
    assert not thread.is_alive() and not errors


def test_clean_eof(pair):
    left, right = pair
    right.close()
    with pytest.raises(EOFError): left.recv(deadline=time.monotonic()+.5)


@pytest.mark.parametrize("data", [b"", b"x", pickle.dumps(True)+b"extra"])
def test_malformed_payload_is_not_clean_end_of_ownership(pair, data):
    left, right = pair
    right.raw.send_bytes(data)
    with pytest.raises(ValueError, match="payload"):
        left.recv(deadline=time.monotonic()+.5)
    with pytest.raises(ValueError, match="invalid"):
        left.recv(deadline=time.monotonic()+.5)


def test_serialized_output_bounded_before_send(pair, monkeypatch):
    from cu_suite.v2 import worker_channel
    left, right = pair
    monkeypatch.setattr(worker_channel, "MAX_FRAME", 32)
    with pytest.raises(ValueError, match="limit"):
        left.send("x"*100)
    assert not right.poll(.01) and left._pending is None


def test_oversized_receive_rejected(pair, monkeypatch):
    from cu_suite.v2 import worker_channel
    left, right = pair
    monkeypatch.setattr(worker_channel, "MAX_FRAME", 32)
    right.raw.send_bytes(b"x"*100)
    with pytest.raises(OSError): left.recv(deadline=time.monotonic()+.5)


def test_failed_thread_start_never_sends_a_frame(pair, monkeypatch):
    left, right = pair
    original = threading.Thread.start
    def start_then_fail(thread):
        original(thread)
        raise RuntimeError("injected launch failure")
    monkeypatch.setattr(threading.Thread, "start", start_then_fail)
    with pytest.raises(RuntimeError): left.send("must not send")
    assert not right.poll(.05) and left._pending is None


def test_repeated_transfers_leave_no_live_io_threads(pair):
    left, right = pair
    for i in range(100):
        left.send({"n": i})
        assert right.recv() == {"n": i}
    for thread in threading.enumerate():
        if thread.name == "axis-worker-io": thread.join(.5)
    assert not any(t.name == "axis-worker-io" for t in threading.enumerate())


def test_stalled_child_large_request_does_not_pin_rpc_caller():
    from cu_suite.v2.worker import SupervisedPlatform
    from cu_suite.v2.contracts import AxisError
    worker = SupervisedPlatform("tests.v2.worker_fixture", "WorkerFixture")
    # Send a blocking read-only fixture operation, without waiting for its reply.
    worker._connection.send(("stall", (), None))
    started = time.monotonic()
    with pytest.raises(AxisError) as error:
        worker._rpc("inspect", b"x"*(16*1024*1024), timeout=.03)
    assert time.monotonic()-started < 1.5
    assert error.value.dispatch == "unknown"
    assert not worker._process.is_alive() and worker._broken
    pending = worker._connection._pending
    assert pending is None or not pending["thread"].is_alive()
    # Interrupted transfer may leave cleanup conservatively unconfirmed.
    try: worker.close()
    except AxisError as cleanup:
        assert cleanup.code == "CLEANUP_FAILED"
