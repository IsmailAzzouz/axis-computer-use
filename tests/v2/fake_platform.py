"""Deterministic contract double, NEVER evidence of native desktop success."""
import copy
from PIL import Image
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.pal_contract import NATIVE_OPERATIONS


class FakePlatform:
    def __init__(self):
        self.window = {"target_id": "test", "identity": "process-start-1", "geometry_id": "geometry-1",
                       "bounds": [-100, 0, 100, 200], "client_origin": [-90, 20], "is_active": True}
        self.elements = [{"native_id": "edit-1", "name": "Input", "role": "Edit", "automation_id": "input",
                          "value": "", "bounds": [-90, 20, 0, 50], "enabled": True, "focused": True}]
        self.coverage, self.epoch = "complete", "document-1"
        self.calls, self.releases, self.closed = [], 0, False
        self.effect_error, self.read_error, self.delay = None, None, 0
        self.image = Image.new("RGB", (200, 200), "black")

    def capabilities(self): return {"actions": sorted(NATIVE_OPERATIONS), "ocr": False, "accessibility": True, "capture": True}
    def targets(self): return [] if self.closed else [copy.deepcopy(self.window)]
    def bind(self, target_id):
        if self.closed or target_id != "test": raise AxisError("TARGET_NOT_FOUND", "No window")
        return copy.deepcopy(self.window)
    def inspect(self, target):
        if self.read_error: raise self.read_error
        return {"elements": copy.deepcopy(self.elements), "coverage": self.coverage, "epoch": self.epoch}
    def capture(self, target): return self.image.copy()
    def dispatch(self, target, op, args, timeout):
        import time
        self.calls.append((op, copy.deepcopy(args)))
        if self.delay: time.sleep(self.delay)
        if self.effect_error: raise self.effect_error
        if op == "type_text": self.elements[0]["value"] = args["text"]
        if op in ("close_window", "terminate_app"): self.closed = True
        if op == "focus": self.window["is_active"] = True
        if op == "open_app": return {"target_id": "test"}
        return {}
    def release(self): self.releases += 1
    def close(self): pass
