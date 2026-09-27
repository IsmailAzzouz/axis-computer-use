"""Bounded read-only sampling process, independent of the physical input worker.

The host selects the source class; no model-supplied code or method dispatch.
Images stay in this process. Only bounded detector summaries cross the pipe.
"""
import importlib
import multiprocessing
import time

from .contracts import AxisError
from .perception import TransitionDetector, _sample
from .worker_channel import WorkerChannel


def _summary(detector):
    return {"sequence": detector.sequence, "active": any(detector.active.values()),
            "samples": detector.samples, "sampled_until": detector.last_time,
            "last_transition_at": detector.events[-1]["timestamp"] if detector.events else None,
            "max_observed_gap": detector.max_observed_gap, "sample_clock": "performance_counter",
            "observation_mode": "continuous"}


def _serve(connection, stop, module, class_name, target, settings, baseline, deadline, input_cancel):
    source = None
    try:
        source = getattr(importlib.import_module(module), class_name)(target)
        detector = TransitionDetector(baseline, on_threshold=settings.get("on_threshold", 30),
            off_threshold=settings.get("off_threshold", 12), max_gap=settings["max_gap"])
        first, requested = True, False
        while not stop.is_set():
            if input_cancel is not None and input_cancel.is_set():
                return
            if time.monotonic() >= deadline:
                raise AxisError("DEADLINE_EXCEEDED", "Continuous observation expired")
            if connection.poll(0):
                # One outstanding request, fixed read-only protocol. Never getattr
                # on messages from the pipe and never expose a dispatch method.
                if connection.recv(deadline=deadline) != "snapshot":
                    raise AxisError("INVALID_REQUEST", "Unknown observation request")
                requested = True
            started = time.perf_counter()
            values = _sample(source.capture(), settings["probes"])
            completed = time.perf_counter()
            if stop.is_set() or (input_cancel is not None and input_cancel.is_set()):
                return
            if time.monotonic() >= deadline:
                raise AxisError("DEADLINE_EXCEEDED", "Continuous capture expired")
            detector.feed(completed, values, started_at=started)
            if first:
                if any(detector.active.values()):
                    raise AxisError("CALIBRATION_UNSTABLE", "Demonstration already started")
                connection.send((True, _summary(detector)), deadline=deadline)
                first = False
            elif requested:
                connection.send((True, _summary(detector)), deadline=deadline)
                requested = False
            stop.wait(min(settings["interval"], max(0, deadline-time.monotonic())))
    except AxisError as exc:
        try:
            connection.send((False, exc.result()), deadline=time.monotonic()+.25)
        except (OSError, ValueError):
            pass
    except (EOFError, OSError, ValueError):
        pass
    except Exception as exc:
        try:
            connection.send((False, {"code": "OBSERVATION_UNAVAILABLE", "message": type(exc).__name__}),
                            deadline=time.monotonic()+.25)
        except (OSError, ValueError):
            pass
    finally:
        try:
            if source is not None:
                source.close()
        finally:
            connection.close()


class TemporalObserver:
    """Internal PAL observation handle; no input methods and no transparent restart."""
    def __init__(self, module, class_name, target, settings, baseline, deadline, *, cancel=None, input_cancel=None):
        self._closed, self._unavailable, self._deadline = False, False, deadline
        self._cancel = cancel
        self._input_cancel = input_cancel
        ctx = multiprocessing.get_context("spawn")
        self._stop = ctx.Event()
        self._connection, child = WorkerChannel.pair()
        self._process = ctx.Process(target=_serve, args=(child, self._stop, module, class_name,
            target, settings, baseline, deadline, input_cancel), daemon=True)
        try:
            self._process.start()
            child.close()
            self.ready = self._receive()
        except BaseException:
            child.close()
            self.close()
            raise

    def _check_cancelled(self):
        if ((self._cancel is not None and self._cancel.is_set())
                or (self._input_cancel is not None and self._input_cancel.is_set())):
            raise AxisError("CANCELLED", "Continuous observation cancelled")

    def _receive(self):
        while True:
            self._check_cancelled()
            if time.monotonic() >= self._deadline:
                raise AxisError("DEADLINE_EXCEEDED", "Continuous observation expired")
            try:
                ok, result = self._connection.recv(deadline=min(self._deadline, time.monotonic()+.05))
                break
            except TimeoutError:
                # Resume the same outstanding pipe receive; no second reader.
                continue
            except (EOFError, OSError, ValueError) as exc:
                raise AxisError("OBSERVATION_LOST", "Continuous observation lost; sequence must not be replayed") from exc
        if not ok:
            raise AxisError(result["code"], result["message"])
        return result

    def snapshot(self):
        if self._unavailable:
            raise AxisError("OBSERVATION_LOST", "Observation already closed")
        self._check_cancelled()
        try:
            # A latched error sent during a long input must be read before trying
            # to write to a process that has already exited.
            if self._connection.poll(0):
                return self._receive()
            self._connection.send("snapshot", deadline=min(self._deadline, time.monotonic()+.25))
            return self._receive()
        except (EOFError, OSError, ValueError) as exc:
            raise AxisError("OBSERVATION_LOST", "Observation checkpoint unavailable; no replay") from exc

    def is_alive(self):
        return self._process is not None and self._process.is_alive()

    def close(self):
        if self._closed:
            return
        self._unavailable = True
        self._stop.set()
        try:
            if self._process.pid is not None:
                self._process.join(.3)
                if self._process.is_alive():
                    # This process has no input ownership. Killing a stuck capture
                    # cannot require a second input writer or an emergency replay.
                    self._process.terminate()
                    self._process.join(1)
                if self._process.is_alive():
                    raise AxisError("OBSERVER_CLEANUP_FAILED", "Observation process did not stop")
            # join() only waits. Explicitly close the Windows process handle and
            # drop the multiprocessing Event's semaphore handles even if callers
            # retain this closed observer for diagnostics.
            self._process.close()
            self._process = None
            self._stop = None
            self._cancel = None
            self._input_cancel = None
            self._closed = True
        finally:
            self._connection.close()
