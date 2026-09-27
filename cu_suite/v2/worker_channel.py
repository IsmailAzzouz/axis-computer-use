"""Bounded waits for private pipe I/O, including complete frame transfer.

One outstanding operation per channel. Timeout keeps its result for ownership
draining after worker exit. Pickle stays private to trusted local processes.
"""
import io
import multiprocessing
import pickle
import threading
import time

MAX_FRAME = 64 * 1024 * 1024


class _LimitedBuffer(io.BytesIO):
    def write(self, data):
        if self.tell()+len(data) > MAX_FRAME:
            raise ValueError("Worker frame exceeds limit")
        return super().write(data)


class WorkerChannel:
    def __init__(self, connection):
        self.raw = connection
        self._pending = None
        self._invalid = False

    @staticmethod
    def pair():
        left, right = multiprocessing.get_context("spawn").Pipe()
        return WorkerChannel(left), WorkerChannel(right)

    def poll(self, timeout=0):
        if self._pending is not None:
            return self._pending["done"].wait(timeout)
        return self.raw.poll(timeout)

    def _finish(self, deadline):
        pending = self._pending
        if not pending["done"].wait(max(0, deadline-time.monotonic())):
            raise TimeoutError("Worker frame deadline exceeded")
        self._pending = None
        if "error" in pending:
            raise pending["error"]
        return pending.get("value")

    def _io(self, operation, callback, deadline):
        if self._pending is not None:
            previous = self._pending["operation"]
            value = self._finish(deadline)
            if previous == operation:
                return value  # Resume same receive; don't lose a consumed frame.
        if time.monotonic() >= deadline:
            raise TimeoutError("Worker frame deadline exceeded")
        pending = {"operation": operation, "done": threading.Event()}
        launch_decided, launch_allowed = threading.Event(), False
        def perform():
            try:
                launch_decided.wait()
                if launch_allowed:
                    pending["value"] = callback()
            except BaseException as exc:
                pending["error"] = exc
            finally:
                pending["done"].set()
        thread = threading.Thread(target=perform, daemon=True, name="axis-worker-io")
        pending["thread"] = thread
        self._pending = pending
        try:
            thread.start()
        except BaseException:
            launch_decided.set()
            self._pending = None
            raise
        launch_allowed = True
        launch_decided.set()
        return self._finish(deadline)

    def send(self, value, *, deadline=None):
        deadline = time.monotonic()+10 if deadline is None else deadline
        if self._pending is not None:
            raise OSError("Previous worker transfer remains unresolved")
        buffer = _LimitedBuffer()
        pickle.Pickler(buffer, protocol=5).dump(value)
        data = buffer.getvalue()
        self._io("send", lambda: self.raw.send_bytes(data), deadline)

    def recv(self, *, deadline=None):
        deadline = time.monotonic()+10 if deadline is None else deadline
        if self._invalid:
            raise ValueError("Worker receive stream is invalid")
        data = self._io("recv", lambda: self.raw.recv_bytes(MAX_FRAME), deadline)
        try:
            stream = io.BytesIO(data)
            value = pickle.Unpickler(stream).load()
            if stream.read(1):
                raise ValueError("Trailing worker frame data")
            return value
        except Exception as exc:
            self._invalid = True
            raise ValueError("Invalid worker frame payload") from exc

    def close(self):
        self.raw.close()
        if self._pending is not None:
            self._pending["thread"].join(.1)
