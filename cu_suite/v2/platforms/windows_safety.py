"""Windows operator-only quarantine control. Never injects input."""
import hashlib
import os
from pathlib import Path

import win32api
import win32con
import win32event
import win32service
import win32ts

from ..contracts import AxisError
from ..safety_latch import SafetyLatch

MUTEX_NAME = "Local\\AXIS-v2-desktop-input"


def desktop_latch():
    base = os.environ.get("LOCALAPPDATA")
    if not base or not Path(base).is_absolute():
        raise AxisError("SAFETY_STORE_UNAVAILABLE", "Local application data path unavailable; input disabled")
    desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
    name = win32service.GetUserObjectInformation(desktop, win32con.UOI_NAME)
    session = win32ts.ProcessIdToSessionId(os.getpid())
    scope = hashlib.sha256(f"{session}:{name}".encode()).hexdigest()
    return SafetyLatch(Path(base)/"AXIS"/"v2"/"desktop-safety.sqlite3", scope)


def operator_safety(owner=None, *, inputs_released=False, clipboard_reviewed=False):
    latch = desktop_latch()
    if owner is None:
        return latch.status()
    if not inputs_released or not clipboard_reviewed:
        raise AxisError("RECONCILIATION_REQUIRED", "Operator must confirm released inputs and reviewed clipboard")
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    acquired = False
    try:
        state = win32event.WaitForSingleObject(mutex, 0)
        acquired = state in (win32con.WAIT_OBJECT_0, win32con.WAIT_ABANDONED)
        if not acquired:
            raise AxisError("DESKTOP_BUSY", "A native input owner is still active; do not clear its quarantine")
        if any(win32api.GetAsyncKeyState(key) & 0x8000 for key in range(1, 256)):
            raise AxisError("USER_INPUT_ACTIVE", "Release all keys/buttons before reconciliation")
        latch.clear(owner, reason="operator_acknowledged")
        return {**latch.status(), "reconciled_owner": owner, "effects_replayed": False}
    finally:
        if acquired: win32event.ReleaseMutex(mutex)
        mutex.Close()
