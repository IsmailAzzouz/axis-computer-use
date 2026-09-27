"""Persistent native worker with bounded RPC; never retries a timed-out effect."""
from __future__ import annotations

import importlib
import multiprocessing
import threading
import time

from .contracts import AxisError
from .worker_channel import WorkerChannel


def _serve(connection, module, class_name, cancel):
    adapter = None
    try:
        adapter = getattr(importlib.import_module(module), class_name)()
        adapter.cancel = cancel
        adapter.ownership_changed = lambda held: connection.send(("ownership", held))
        adapter.clipboard_changed = lambda lease: connection.send(("clipboard", lease))
        connection.send((True, "ready"))
        while True:
            if hasattr(adapter, "pump_events"):
                adapter.pump_events()
            if not connection.poll(.02):
                continue
            method, args, execution_deadline = connection.recv()
            if method == "_shutdown":
                closing, adapter = adapter, None
                try:
                    closing.close()
                    connection.send((True, "closed"))
                except Exception:
                    connection.send((False, {"code": "CLEANUP_FAILED", "message": "Native shutdown cleanup failed", "dispatch": "unknown"}))
                return
            try:
                if method == "dispatch":
                    # The host and its local worker share monotonic time. IPC
                    # and lock waits consume the original action budget.
                    if cancel.is_set():
                        raise AxisError("CANCELLED", "Action cancelled before native dispatch")
                    remaining = execution_deadline-time.monotonic()
                    if remaining <= 0:
                        raise AxisError("DEADLINE_EXCEEDED", "Action expired before native dispatch")
                    args = (*args, remaining)
                connection.send((True, getattr(adapter, method)(*args)))
            except AxisError as exc:
                connection.send((False, exc.result()))
            except Exception as exc:
                connection.send((False, {"code": "NATIVE_ERROR", "message": type(exc).__name__,
                                         "dispatch": "unknown" if method == "dispatch" else "not_sent"}))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            connection.send((False, {"code": "WORKER_START_FAILED", "message": type(exc).__name__}))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        try:
            if adapter: adapter.close()
        finally:
            connection.close()


def _cleanup(module, class_name, held, clipboard_lease, connection):
    try:
        getattr(importlib.import_module(module), class_name).emergency_release(held, clipboard_lease)
        connection.send(True)
    except Exception:
        connection.send(False)
    finally:
        connection.close()


class SupervisedPlatform:
    def __init__(self, module, class_name, timeout=10, *, observer_factory=None):
        self._observer_factory = observer_factory
        self._timeout, self._broken, self._lock = timeout, False, threading.Lock()
        self._stopped, self._closing, self._cleanup_state = False, False, "not_required"
        ctx = multiprocessing.get_context("spawn")
        self._module, self._class_name, self._held = module, class_name, []
        self._clipboard = None
        self._cancel = ctx.Event()
        self._connection, child = WorkerChannel.pair()
        self._process = ctx.Process(target=_serve, args=(child, module, class_name, self._cancel), daemon=True)
        self._process.start()
        child.close()
        startup_deadline = time.monotonic()+timeout
        try:
            ok, result = self._connection.recv(deadline=startup_deadline)
        except (EOFError, OSError, ValueError):
            self._stop()
            raise AxisError("WORKER_TIMEOUT", "Native worker failed to start")
        if not ok:
            self._stop()
            raise AxisError(result["code"], result["message"])

    def _stop(self):
        if self._stopped:
            return  # Never retry emergency key/clipboard writes after a failed helper.
        self._stopped = True
        self._broken = True
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(1)
        if self._process.is_alive():
            self._connection.close()
            self._cleanup_state = "failed"
            return  # A second process must not race a still-running input worker.
        # An expired ACK budget may leave ownership reports unread in the pipe.
        # Only drain after the worker has exited: no writer can append forever,
        # and a partial final frame cannot wait on a live, stalled producer.
        ownership_complete = True
        drain_deadline = time.monotonic()+1
        try:
            for _ in range(1024):
                try:
                    # recv translates a closed peer into EOF consistently;
                    # poll may itself raise on a closed Windows pipe.
                    kind, value = self._connection.recv(deadline=drain_deadline)
                except EOFError:
                    break
                if kind == "ownership":
                    self._held = value
                elif kind == "clipboard":
                    self._clipboard = value
            else:
                ownership_complete = False
        except (OSError, ValueError, TypeError):
            ownership_complete = False
        finally:
            self._connection.close()
        if not ownership_complete:
            self._cleanup_state = "failed"
        elif not self._held and self._clipboard is None and self._cleanup_state == "pending":
            self._cleanup_state = "confirmed"
        if self._held or self._clipboard:
            self._cleanup_state = "failed"
            ctx = multiprocessing.get_context("spawn")
            parent, child = WorkerChannel.pair()
            recovery = ctx.Process(target=_cleanup, args=(self._module, self._class_name, self._held, self._clipboard, child), daemon=True)
            recovered, started = False, False
            try:
                recovery.start()
                started = True
                child.close()
                recovered = parent.recv(deadline=time.monotonic()+3) is True
            except (EOFError, OSError, ValueError):
                recovered = False
            finally:
                child.close()
                if started:
                    recovery.join(.5)
                    if recovery.is_alive():
                        recovery.terminate()
                        recovery.join(1)
                    recovered = recovered and not recovery.is_alive()
                parent.close()
            if recovered:
                self._held = []
                self._clipboard = None
                self._cleanup_state = "confirmed" if ownership_complete else "failed"

    def cleanup_status(self):
        return {"state": self._cleanup_state, "owned_input_count": len(self._held),
                "clipboard_pending": self._clipboard is not None}

    def _assert_cleanup(self):
        if self._held or self._clipboard or self._cleanup_state == "failed":
            raise AxisError("CLEANUP_FAILED", "Native ownership could not be reconciled; this worker remains unavailable", dispatch="unknown")

    def _rpc(self, method, *args, timeout=None, execution_deadline=None):
        duration = self._timeout if timeout is None else timeout
        deadline = time.monotonic()+duration
        admission_deadline = deadline
        if execution_deadline is not None:
            admission_deadline = min(deadline, execution_deadline)
            # Grace is only for an ACK/cleanup after submission, never admission.
            deadline = min(deadline, execution_deadline+.5)
        if not self._lock.acquire(timeout=max(0, admission_deadline-time.monotonic())):
            raise AxisError("WORKER_BUSY", "Worker admission deadline expired; request was not submitted")
        try:
            if self._broken:
                raise AxisError("WORKER_UNAVAILABLE", "Worker lost; host restart and effect reconciliation required")
            if self._closing and method != "_shutdown":
                raise AxisError("WORKER_UNAVAILABLE", "Worker is closing")
            if time.monotonic() >= admission_deadline:
                raise AxisError("WORKER_BUSY", "Worker admission deadline expired; request was not submitted")
            try:
                self._connection.send((method, args, execution_deadline), deadline=deadline)
                while True:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0 or not self._connection.poll(remaining):
                        self._stop()
                        raise AxisError("EFFECT_UNKNOWN" if method == "dispatch" else "WORKER_TIMEOUT",
                                        "Native worker timed out; not retried", dispatch="unknown" if method == "dispatch" else "not_sent")
                    ok, result = self._connection.recv(deadline=deadline)
                    if ok == "ownership":
                        self._held = result
                        if result: self._cleanup_state = "pending"
                        continue
                    if ok == "clipboard":
                        self._clipboard = result
                        if result is not None: self._cleanup_state = "pending"
                        continue
                    break
                if not ok:
                    raise AxisError(result["code"], result["message"], dispatch=result.get("dispatch", "not_sent"))
                return result
            except (EOFError, OSError, ValueError):
                self._stop()
                raise AxisError("EFFECT_UNKNOWN", "Native worker connection lost", dispatch="unknown")
        finally:
            self._lock.release()

    def targets(self): return self._rpc("targets")
    def capabilities(self):
        result = self._rpc("capabilities")
        return {**result, "temporal_capture": bool(self._observer_factory and result.get("capture"))}

    def open_observer(self, target, settings, baseline, deadline, *, cancel=None):
        if self._observer_factory is None:
            raise AxisError("CAPABILITY_UNAVAILABLE", "Independent temporal capture unavailable")
        from .temporal_worker import TemporalObserver
        return TemporalObserver(*self._observer_factory, target, settings, baseline, deadline,
                                cancel=cancel, input_cancel=self._cancel)
    def bind(self, target_id): return self._rpc("bind", target_id)
    def inspect(self, target, query=None):
        return self._rpc("inspect", target, query) if query else self._rpc("inspect", target)
    def capture(self, target): return self._rpc("capture", target)
    def ocr(self, target, region): return self._rpc("ocr", target, region)
    def events(self, target, since=0): return self._rpc("events", target, since)
    def acquire_lease(self):
        self._cancel.clear()
        return self._rpc("acquire_lease")
    def release_lease(self):
        if self._broken:
            self._assert_cleanup()
            return
        result = self._rpc("release_lease")
        self._cancel.clear()  # Subsequent read-only observations are not cancelled jobs.
        self._assert_cleanup()
        self._cleanup_state = "confirmed"
        return result
    def dispatch(self, target, op, args, timeout):
        return self._rpc("dispatch", target, op, args, timeout=timeout+.5,
                         execution_deadline=time.monotonic()+timeout)
    def cancel(self): self._cancel.set()
    def release(self):
        if self._broken:
            self._assert_cleanup()
            return
        return self._rpc("release")

    def close(self):
        if not self._broken:
            self._closing = True
            try:
                # Drain ownership notifications until the native cleanup ACK.
                self._rpc("_shutdown", timeout=2)
                self._assert_cleanup()
                self._cleanup_state = "confirmed"
                self._process.join(.5)
            finally:
                self._stop()
        self._assert_cleanup()
