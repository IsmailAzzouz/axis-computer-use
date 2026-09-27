"""Bounded WinEvent subscriptions. Events prompt a fresh semantic read; no event
or a dropped event buffer is never proof that a UI remained unchanged."""
import ctypes
from ctypes import wintypes
from collections import deque
import time
import win32gui
from ..contracts import AxisError

CALLBACK = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                             wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, CALLBACK, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL
NAMES = {0x8000: "created", 0x8001: "destroyed", 0x8002: "shown", 0x8003: "hidden",
         0x8005: "focus", 0x800A: "state", 0x800B: "geometry", 0x800C: "name", 0x800E: "value"}


class WindowLifetimes:
    """Invalidate cached HWND generations on native create/destroy events."""
    def __init__(self):
        self.generations, self.sequence = {}, 0
        self.callback = CALLBACK(self._event)
        self.hook = user32.SetWinEventHook(0x8000, 0x8001, None, self.callback, 0, 0, 2)
        if not self.hook:
            raise AxisError("CAPABILITY_UNAVAILABLE", "Window lifetime tracking unavailable")

    def _event(self, hook, event, hwnd, object_id, child_id, thread, timestamp):
        if hwnd and object_id == 0 and child_id == 0:
            self.generations.pop(hwnd, None)

    def generation(self, hwnd):
        if hwnd not in self.generations:
            self.sequence += 1
            self.generations[hwnd] = self.sequence
            if len(self.generations) > 4096:
                self.generations.pop(next(iter(self.generations)))
        return self.generations[hwnd]

    def close(self):
        if self.hook:
            user32.UnhookWinEvent(self.hook)
            self.hook = None


class Subscription:
    def __init__(self, target):
        self.target, self.events, self.sequence = target, deque(maxlen=1024), 0
        self.callback = CALLBACK(self._event)
        self.hook = user32.SetWinEventHook(0x8000, 0x800E, None, self.callback, target["pid"], 0, 2)
        if not self.hook:
            raise AxisError("CAPABILITY_UNAVAILABLE", "Native event subscription rejected")

    def _event(self, hook, event, hwnd, object_id, child_id, thread, timestamp):
        if event not in NAMES or not hwnd:
            return
        try:
            root = win32gui.GetAncestor(hwnd, 2)
            for _ in range(8):
                if root == self.target["handle"]:
                    break
                root = win32gui.GetWindow(root, 4) if root else 0
            else:
                return
            self.sequence += 1
            self.events.append({"cursor": self.sequence, "kind": NAMES[event], "object_id": object_id,
                                "child_id": child_id, "observed_at": time.monotonic()})
        except Exception:
            # A destroyed window may be unresolvable; a later read detects loss.
            return

    def read(self, since=0):
        win32gui.PumpWaitingMessages()
        if since < 0 or since > self.sequence:
            raise AxisError("INVALID_CURSOR", "Invalid native event cursor")
        dropped = bool(self.events and since < self.events[0]["cursor"]-1)
        return {"events": [e for e in self.events if e["cursor"] > since][:64],
                "cursor": min(self.sequence, max(since, self.events[0]["cursor"]-1 if self.events else since)+64),
                "coverage": "dropped" if dropped else "complete", "provenance": "windows_win_event"}

    def close(self):
        if self.hook:
            user32.UnhookWinEvent(self.hook)
            self.hook = None
