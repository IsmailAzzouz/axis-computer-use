"""Process-level fault injection backend, deliberately unrelated to desktop APIs."""
import time
from .fake_platform import FakePlatform


class WorkerFixture(FakePlatform):
    def acquire_lease(self): pass

    def release_lease(self): pass

    def cancellation_pending(self): return self.cancel.is_set()

    def runtime_origin(self):
        import cu_suite.v2.worker
        return cu_suite.v2.worker.__file__

    def stall(self):
        time.sleep(2)

    def crash(self):
        import os
        os._exit(17)

    def cancel_wait(self):
        if not self.cancel.wait(2):
            raise RuntimeError("Cancellation not delivered")
        return "cancelled"

    @staticmethod
    def emergency_release(held, clipboard_lease=None):
        if held:
            raise RuntimeError("This fixture must never hold native input")


class DeadlineFixture(WorkerFixture):
    def dispatch(self, target, op, args, timeout):
        super().dispatch(target, op, args, timeout)
        return {"remaining": timeout}

    def dispatch_count(self): return len(self.calls)


class OwnershipFixture(WorkerFixture):
    """Reports simulated ownership; its cleanup never invokes OS input APIs."""
    def queued_ownership(self, report, ready):
        from pathlib import Path
        self.hold_and_fail(report, "success", "none")
        Path(ready).touch()  # Signal only after both ownership reports are queued.
        time.sleep(5)

    def configure_failure(self, report, behavior):
        self._failure = (report, behavior)

    def dispatch(self, *args):
        if hasattr(self, "_failure"):
            return self.hold_and_fail(*self._failure)
        return super().dispatch(*args)

    def hold_and_fail(self, report, behavior="success", failure="crash"):
        self._test_held = [("key", 17), ("mouse", "left")]
        self._test_clipboard = {"report": report, "behavior": behavior, "sequence": 42}
        self.ownership_changed(self._test_held)
        self.clipboard_changed(self._test_clipboard)
        if failure == "crash": self.crash()
        if failure == "stall": time.sleep(5)
        return "held"

    def close(self):
        self.ownership_changed([])
        self.clipboard_changed(None)

    @staticmethod
    def emergency_release(held, clipboard_lease=None):
        import json
        import os
        from pathlib import Path
        report = Path(clipboard_lease["report"])
        with report.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"held": held, "clipboard": clipboard_lease})+"\n")
        behavior = clipboard_lease["behavior"]
        if behavior == "fail": raise RuntimeError("Simulated key-up failure")
        if behavior == "crash": os._exit(29)
        if behavior == "stall": time.sleep(5)
