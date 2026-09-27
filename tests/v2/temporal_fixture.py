"""Pixel-only synthetic scene for spawned observation tests, no desktop APIs."""
from pathlib import Path
import os
import time

from PIL import Image

from cu_suite.v2.contracts import AxisError


class SceneSource:
    def __init__(self, target):
        self.marker = Path(target["marker"])
        self.fault = target.get("fault")
        self.failed = False

    def capture(self):
        if not self.marker.exists():
            return Image.new("RGB", (20, 20), "black")
        elapsed = time.perf_counter()-float(self.marker.read_text())
        if not self.failed:
            self.failed = True
            if self.fault == "gap": time.sleep(.35)
            if self.fault == "crash": os._exit(31)
            if self.fault == "hang": time.sleep(10)
            if self.fault == "moved": raise AxisError("STALE_PROFILE", "Synthetic target moved")
        on = .10 <= elapsed < .60 or .90 <= elapsed < 1.40
        return Image.new("RGB", (20, 20), "red" if on else "black")

    def close(self):
        pass
