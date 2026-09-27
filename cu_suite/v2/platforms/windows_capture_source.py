"""Window-scoped read-only source for an independent sampling process."""
from ..contracts import AxisError


class WindowsCaptureSource:
    def __init__(self, target):
        from .windows import WindowsPlatform
        self._reader = WindowsPlatform()
        try:
            self._reader.pump_events()
            current = self._reader._target(target["handle"])
            # HWND generation numbers are worker-local. Match native process
            # birth/HWND and geometry, then retain THIS reader's tracked identity.
            # The runtime must revalidate the input worker's original generation
            # after our ready message and before triggering any demonstration.
            if (current["identity"].rsplit(":", 1)[0] != target["identity"].rsplit(":", 1)[0]
                    or any(current[k] != target[k] for k in ("bounds", "client_origin", "dpi", "native_class"))):
                raise AxisError("STALE_PROFILE", "Observation source no longer matches the authorized window")
            self._target = current
        except BaseException:
            self._reader.close()
            raise

    def capture(self):
        self._reader.pump_events()
        image = self._reader.capture(self._target)
        self._reader.pump_events()
        # Includes identity, geometry, visibility and foreground revalidation;
        # capture must never focus or move this window.
        fresh = self._reader._fresh(self._target, geometry=True)
        if fresh["minimized"] or not fresh["is_active"]:
            raise AxisError("CAPTURE_OCCLUDED", "Observation target ceased to be visible in foreground")
        return image

    def close(self):
        self._reader.close()
