"""Windows native adapter. Imported only in its resident worker process.

No desktop switching, forced focus hacks, shell execution, or implicit retries.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import subprocess
import time
import winreg

import pythoncom
from comtypes import COMError
import win32api
import win32con
import win32event
import win32gui
import win32process
from PIL import ImageGrab

from ..contracts import AxisError


ULONG_PTR = ctypes.c_size_t
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]
class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]
class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ULONG_PTR)]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

KEYS = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "meta": 0x5B,
        "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "space": 0x20,
        "backspace": 8, "delete": 0x2E, "left": 0x25, "up": 0x26,
        "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22}
KEYS.update({f"f{i}": 0x6F+i for i in range(1, 25)})
KEYS.update({chr(i).lower(): i for i in range(65, 91)})
KEYS.update({str(i): 48+i for i in range(10)})
MOUSE = {"left": (2, 4, 1), "right": (8, 16, 2), "middle": (32, 64, 4)}


class WindowsPlatform:
    def __init__(self):
        # The host selects/authorizes the interactive session. Never switch
        # desktops here, even if the current one exposes no usable targets.
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        import uiautomation
        self.auto = uiautomation
        from comtypes.client import CreateObject, GetModule
        core = GetModule("UIAutomationCore.dll")
        self._uia = CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=core.IUIAutomation)
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        self._held = []
        self.cancel = None
        self.ownership_changed = lambda held: None
        self._did_send = False
        self._action_deadline = None
        self._last_cursor = None
        self._mutex = win32event.CreateMutex(None, False, "Local\\AXIS-v2-desktop-input")
        self._owns_lease = False
        self._safety = None
        self._safety_owner = None
        self._ocr = None
        self._subscriptions = {}
        self._clipboard = None
        self.clipboard_changed = lambda lease: None
        from .windows_events import WindowLifetimes
        self._lifetimes = WindowLifetimes()
        self._bindings = {}

    def capabilities(self):
        interactive = bool(win32gui.GetForegroundWindow())
        return {"platform": "windows", "status": "experimental", "interactive": interactive,
                "actions": ["open_app", "focus", "close_window", "terminate_app", "maximize_window", "restore_window", "minimize_window", "click", "type_text", "paste_text", "keys", "move", "hover", "scroll", "drag", "swipe", "set_slider"] if interactive else [],
                "accessibility": interactive, "targeted_accessibility": interactive, "capture": interactive, "ocr": interactive, "subscriptions": interactive,
                "ocr_status": "permission_and_language_checked_on_use", "certified_scenarios": []}

    def acquire_lease(self):
        if self._owns_lease or self._held or self._clipboard:
            raise AxisError("CLEANUP_FAILED", "Previous native input ownership remains unresolved", dispatch="unknown")
        status = win32event.WaitForSingleObject(self._mutex, 0)
        if status not in (win32con.WAIT_OBJECT_0, win32con.WAIT_ABANDONED):
            raise AxisError("DESKTOP_BUSY", "Another AXIS process owns desktop input")
        try:
            if self._safety is None:
                from .windows_safety import desktop_latch
                self._safety = desktop_latch()
            if status == win32con.WAIT_ABANDONED:
                self._safety.arm(os.getpid(), abandoned=True)
                raise AxisError("INPUT_UNRECONCILED", "Previous native owner crashed; operator reconciliation required")
            self._safety_owner = self._safety.arm(os.getpid())
        except BaseException:
            win32event.ReleaseMutex(self._mutex)
            raise
        self._owns_lease = True
        self._last_cursor = None

    def release_lease(self):
        if self._clipboard:
            from .windows_clipboard import restore
            restore(self._clipboard)
            self._clipboard = None
            self.clipboard_changed(None)
        if self._held:
            # Never admit a new owner while an old key/button remains down.
            raise AxisError("CLEANUP_FAILED", "Owned inputs remain held; desktop lease retained", dispatch="unknown")
        if self._owns_lease:
            if self._safety_owner is not None:
                self._safety.clear(self._safety_owner, reason="normal_cleanup")
                self._safety_owner = None
            win32event.ReleaseMutex(self._mutex)
            self._owns_lease = False

    def _identity(self, hwnd):
        if not win32gui.IsWindow(hwnd):
            raise AxisError("TARGET_NOT_FOUND", "Window no longer exists")
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(0x1000, False, pid)
        try:
            birth = str(win32process.GetProcessTimes(handle)["CreationTime"])
        finally:
            handle.Close()
        return f"{hwnd}:{pid}:{birth}:{self._lifetimes.generation(hwnd)}"

    @staticmethod
    def _id(identity):
        return "win:"+hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _owner(self, hwnd):
        owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
        if not owner and win32gui.GetClassName(hwnd) == "#32768":
            thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
            info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
                owner = info.hwndMenuOwner
        return owner

    def _target(self, hwnd):
        identity = self._identity(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        bounds = list(win32gui.GetWindowRect(hwnd))
        origin = list(win32gui.ClientToScreen(hwnd, (0, 0)))
        dpi = user32.GetDpiForWindow(hwnd)
        geometry = hashlib.sha256(json.dumps([identity, bounds, origin, dpi]).encode()).hexdigest()[:24]
        owner = self._owner(hwnd)
        owner_id = self._id(self._identity(owner)) if owner else None
        minimized = bool(win32gui.IsIconic(hwnd))
        target = {"target_id": self._id(identity), "identity": identity, "owner_target_id": owner_id,
                "handle": hwnd, "pid": pid, "title": win32gui.GetWindowText(hwnd), "bounds": bounds,
                "native_class": win32gui.GetClassName(hwnd),
                "launch_candidate": bool(win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_SYSMENU),
                "client_origin": origin, "geometry_id": geometry, "dpi": dpi,
                "is_active": win32gui.GetForegroundWindow() == hwnd, "minimized": minimized,
                "window_state": "minimized" if minimized else "maximized" if user32.IsZoomed(hwnd) else "normal"}
        self._bindings[target["target_id"]] = target
        if len(self._bindings) > 4096:
            self._bindings.pop(next(iter(self._bindings)))
        return target

    def targets(self):
        self.pump_events()
        windows = []
        def visit(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                try:
                    windows.append(self._target(hwnd))
                except (AxisError, win32api.error):
                    pass  # Inaccessible processes are not advertised as bindable.
        win32gui.EnumWindows(visit, None)
        return windows

    def bind(self, target_id):
        self.pump_events()
        known = self._bindings.get(target_id)
        if known is None:
            self.targets()
            known = self._bindings.get(target_id)
        if known is None:
            raise AxisError("TARGET_UNKNOWN", "Unknown target identity; absence is not proven")
        try:
            current = self._target(known["handle"])
        except win32api.error:
            raise AxisError("TARGET_UNAVAILABLE", "Window identity cannot currently be inspected")
        if current["identity"] != known["identity"]:
            raise AxisError("TARGET_NOT_FOUND", "Original window instance no longer exists")
        return current

    def _owned_roots(self, target):
        from .window_ownership import owned_handles
        # Modern file pickers may be brokered in another process. Authority
        # follows the native owner identity, not a same-PID approximation.
        return owned_handles(target, self.targets())

    def _check_user_input(self):
        held = {key if kind == "key" else MOUSE[key][2] for kind, key in self._held}
        if any(win32api.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C, 1, 2, 4) if vk not in held):
            raise AxisError("USER_INPUT_ACTIVE", "User modifier/button is held")
        if self._last_cursor is not None and win32gui.GetCursorPos() != self._last_cursor:
            raise AxisError("USER_INPUT_ACTIVE", "Pointer moved outside AXIS during the plan")

    def _check_action(self):
        """Last check before a new mutation; never used to block cleanup."""
        if self.cancel is not None and self.cancel.is_set():
            raise AxisError("CANCELLED", "Native action cancelled",
                            dispatch="sent" if self._did_send else "not_sent")
        if self._action_deadline is not None and time.monotonic() >= self._action_deadline:
            raise AxisError("DEADLINE_EXCEEDED", "Native action deadline exceeded",
                            dispatch="sent" if self._did_send else "not_sent")

    def _fresh(self, target, *, foreground=False, geometry=False):
        if self._action_deadline is not None:
            self._check_action()
        if foreground and self.cancel is not None and self.cancel.is_set():
            raise AxisError("CANCELLED", "Native action cancelled", dispatch="sent" if self._did_send else "not_sent")
        if foreground:
            self._check_user_input()
        now = self._target(target["handle"])
        if now["identity"] != target["identity"]:
            raise AxisError("STALE_TARGET", "Window process identity changed")
        if geometry and now["geometry_id"] != target["geometry_id"]:
            raise AxisError("STALE_FRAME", "Window geometry changed before dispatch")
        if foreground and not now["is_active"] and win32gui.GetForegroundWindow() not in self._owned_roots(target):
            raise AxisError("FOCUS_LOST", "Authorized target is not foreground")
        if now["minimized"] and foreground:
            raise AxisError("TARGET_NOT_ACTIONABLE", "Target is minimized")
        if self._action_deadline is not None:
            self._check_action()
        return now

    def inspect(self, target, query=None):
        from .windows_accessibility import provider_read, read_controls
        with provider_read((COMError,), "root"):
            deadline = min(time.monotonic()+2., self._action_deadline or float("inf"))
            for attempt in range(3):
                self._fresh(target)
                try:
                    root = self.auto.ControlFromHandle(target["handle"])
                    roots = [root]+[self.auto.ControlFromHandle(hwnd) for hwnd in sorted(self._owned_roots(target)) if hwnd != target["handle"]]
                    epoch = str(root.GetRuntimeId())
                    break
                except COMError as exc:
                    # Do not let a provider failure mask the enclosing action budget.
                    self._check_action()
                    hresult = getattr(exc, "hresult", None)
                    unavailable = type(hresult) is int and (hresult & 0xffffffff) == 0x80040201
                    if (not unavailable or attempt == 2 or
                            (self.cancel is not None and self.cancel.is_set()) or
                            time.monotonic()+.02 >= deadline):
                        raise
                    time.sleep(.02)
        result = read_controls(self.auto, self._uia, roots, query, cancel=self.cancel, provider_errors=(COMError,))
        # Query-specific epoch is re-read with that same query when resolving refs.
        epoch += ":"+":".join(e["native_id"] for e in result["elements"] if e["role"] == "Document")
        self._fresh(target)
        return {**result, "epoch": epoch}

    def capture(self, target):
        now = self._fresh(target, geometry=True)
        l, t, r, b = now["bounds"]
        if (r-l)*(b-t) > 16_000_000:
            raise AxisError("CAPTURE_TOO_LARGE", "Window exceeds the native capture budget")
        if now["minimized"]:
            raise AxisError("CAPTURE_UNAVAILABLE", "Minimized windows cannot be captured")
        if not now["is_active"]:
            raise AxisError("CAPTURE_OCCLUDED", "Foreground target required for screen capture; capture never focuses it")
        return ImageGrab.grab(bbox=tuple(now["bounds"]), all_screens=True)

    def _send(self, events, *, cleanup=False):
        inputs = (INPUT*len(events))(*events)
        if not cleanup:
            self._check_action()
        sent = user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT))
        if not cleanup:
            self._did_send |= bool(sent)
        if sent != len(events):
            raise AxisError("INPUT_REJECTED", "OS rejected or partially accepted input; check session and integrity level",
                            dispatch="unknown" if sent else "not_sent")

    def _key(self, key, up=False):
        self._send([INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2 if up else 0))], cleanup=up)

    def _mouse(self, flags, data=0, *, cleanup=False):
        self._send([INPUT(type=0, mi=MOUSEINPUT(dwFlags=flags, mouseData=data & 0xffffffff))], cleanup=cleanup)

    def _verify_semantic_point(self, target, point, *, hit_test=True):
        if "native_id" not in point:
            return
        from .semantic_point import verify_semantic_point
        verify_semantic_point(point, self.inspect(target, point["query"]))
        if hit_test:
            # A same-window overlay must not receive a click intended for a
            # still-existing control behind it. Text children may be hit directly.
            node = self.auto.ControlFromPoint(point["x"], point["y"])
            for _ in range(32):
                if node is None:
                    break
                if str(node.GetRuntimeId()) == point["native_id"]:
                    return node
                node = node.GetParentControl()
            raise AxisError("TARGET_OCCLUDED", "Accessibility hit test belongs to another element")

    def _point(self, target, point):
        self._fresh(target, foreground=True, geometry=True)
        self._verify_semantic_point(target, point)
        self._fresh(target, foreground=True, geometry=True)
        x, y = point["x"], point["y"]
        l, t, r, b = target["bounds"]
        owner = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)
        if owner not in self._owned_roots(target):
            raise AxisError("TARGET_OCCLUDED", "Another window owns this screen point")
        self._check_action()
        win32api.SetCursorPos((x, y))
        self._did_send = True
        self._last_cursor = (x, y)

    def _hold(self, kind, key):
        self._check_action()
        vk = key if kind == "key" else MOUSE[key][2]
        if win32api.GetAsyncKeyState(vk) & 0x8000:
            raise AxisError("USER_INPUT_ACTIVE", "Requested key/button is already held")
        self._held.append((kind, key))
        self.ownership_changed(list(self._held))
        if kind == "key": self._key(key)
        else: self._mouse(MOUSE[key][0])

    def release(self):
        failures = []
        while self._held:
            kind, key = self._held.pop()
            try:
                if kind == "key": self._key(key, up=True)
                else: self._mouse(MOUSE[key][1], cleanup=True)
            except Exception:
                failures.append((kind, key))
        if failures:
            self._held.extend(failures)
            raise AxisError("CLEANUP_FAILED", "Could not release owned inputs", dispatch="unknown")
        self.ownership_changed(list(self._held))

    @staticmethod
    def emergency_release(held, clipboard_lease=None):
        """Only the keys/buttons reported as owned by the terminated worker."""
        events = []
        for kind, key in held:
            if kind == "key":
                events.append(INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2)))
            else:
                events.append(INPUT(type=0, mi=MOUSEINPUT(dwFlags=MOUSE[key][1])))
        if events:
            inputs = (INPUT*len(events))(*events)
            if user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT)) != len(events):
                raise AxisError("CLEANUP_FAILED", "Emergency release was rejected")
        if clipboard_lease:
            from .windows_clipboard import restore
            restore(clipboard_lease)

    def _keys(self, target, keys, hold=0):
        if any(k.lower() not in KEYS for k in keys) or len(set(k.lower() for k in keys)) != len(keys):
            raise AxisError("INVALID_KEY", "Unsupported or duplicate key")
        try:
            for name in keys:
                self._fresh(target, foreground=True)
                self._hold("key", KEYS[name.lower()])
            stop = time.monotonic()+hold
            while time.monotonic() < stop:
                self._fresh(target, foreground=True)
                time.sleep(min(.02, stop-time.monotonic()))
        finally:
            self.release()

    def _resolve_app(self, app):
        path = shutil.which(app)
        if path:
            return path
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\"+app.removesuffix(".exe")+".exe", 0, winreg.KEY_READ | view) as key:
                        path = winreg.QueryValue(key, None)
                        if os.path.isfile(path): return path
                except OSError:
                    pass
        raise AxisError("APP_NOT_FOUND", "Application not found in PATH or App Paths")

    def dispatch(self, target, op, args, timeout):
        if not self._owns_lease:
            raise AxisError("DESKTOP_BUSY", "Input lease required")
        deadline = time.monotonic()+timeout
        self._action_deadline = deadline
        self._did_send = False
        try:
            self._check_action()
            if op == "open_app":
                existing = {w["target_id"] for w in self.targets()}
                command = [self._resolve_app(args["app"]), *args.get("args", [])]
                self._check_action()
                process = subprocess.Popen(command, shell=False)
                self._did_send = True
                candidate_id, candidate_since = None, None
                while time.monotonic() < deadline:
                    if self.cancel is not None and self.cancel.is_set():
                        raise AxisError("CANCELLED", "Launch wait cancelled; process was started", dispatch="sent")
                    windows = [w for w in self.targets() if w["pid"] == process.pid and w["target_id"] not in existing
                               and w["launch_candidate"] and w["title"] and win32gui.IsWindowEnabled(w["handle"])]
                    if len(windows) > 1:
                        raise AxisError("AMBIGUOUS_TARGET", "Application opened multiple candidate windows", dispatch="sent")
                    if windows:
                        if candidate_id != windows[0]["target_id"]:
                            candidate_id, candidate_since = windows[0]["target_id"], time.monotonic()
                        elif time.monotonic()-candidate_since >= .15:
                            return {"target_id": candidate_id, "process_id": process.pid}
                    else:
                        candidate_id, candidate_since = None, None
                    time.sleep(.05)
                raise AxisError("LAUNCH_UNRESOLVED", "Process started but no uniquely owned window appeared; inspect targets, do not relaunch", dispatch="sent")
            self._fresh(target)
            if op == "focus":
                target = self._fresh(target)
                method = args.get("method", "native")
                if target["minimized"]:
                    self._check_user_input()
                    self._check_action()
                    self._did_send = True
                    user32.ShowWindow(target["handle"], win32con.SW_RESTORE)
                    while True:
                        target = self._fresh(target)
                        if not target["minimized"]:
                            break
                        if time.monotonic() >= deadline:
                            raise AxisError("DEADLINE_EXCEEDED", "Window did not restore before activation")
                        time.sleep(.01)
                if win32gui.GetForegroundWindow() == target["handle"]:
                    return {"activation_method": "restore" if self._did_send else "already_active"}
                if win32gui.GetForegroundWindow() != target["handle"]:
                    if method == "caption_click":
                        from .windows_focus import caption_point
                        self._check_user_input()
                        if target["minimized"]:
                            raise AxisError("ACTIVATION_UNAVAILABLE", "Minimized window has no exposed caption")
                        # Raising this authorized window is a normal part of an
                        # explicit activation request. Do not steal keyboard focus
                        # or attach input queues: the verified caption click below
                        # requests activation through the ordinary physical route.
                        self._check_action()
                        win32gui.SetWindowPos(target["handle"], win32con.HWND_TOP, 0, 0, 0, 0,
                                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                        self._did_send = True  # Z order has changed, even if activation later fails.
                        def belongs(x, y):
                            return user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2) == target["handle"]
                        def hit(x, y):
                            value = ULONG_PTR()
                            ok = user32.SendMessageTimeoutW(target["handle"], 0x84, 0, (x & 0xffff) | ((y & 0xffff) << 16),
                                                             2, 100, ctypes.byref(value))
                            return value.value if ok else None
                        x, y = caption_point(target["bounds"], hit, belongs)
                        self._fresh(target, geometry=True)
                        self._check_user_input()
                        if not belongs(x, y) or hit(x, y) != 2:
                            raise AxisError("TARGET_OCCLUDED", "Caption changed before activation")
                        self._check_action()
                        win32api.SetCursorPos((x, y))
                        self._last_cursor = (x, y)
                        self._hold("mouse", "left")
                        self.release()
                    else:
                        self._check_user_input()
                        # Keep the BOOL: the pywin32 wrapper does not expose it.
                        # A successful request across input queues is asynchronous.
                        self._check_action()
                        accepted = user32.SetForegroundWindow(target["handle"])
                        if not accepted:
                            if win32gui.GetForegroundWindow() != target["handle"]:
                                raise AxisError("FOCUS_DENIED", "Windows denied native activation; use explicit caption_click or activate the window manually")
                        self._did_send = True
                from .windows_focus import await_foreground
                def check_activation():
                    self._fresh(target)
                    self._check_user_input()
                    if self.cancel is not None and self.cancel.is_set():
                        raise AxisError("CANCELLED", "Activation cancelled", dispatch="sent")
                await_foreground(target["handle"], win32gui.GetForegroundWindow, check_activation, deadline)
                return {"activation_method": method}
            if op in ("maximize_window", "restore_window", "minimize_window"):
                self._check_user_input()
                self._check_action()
                self._did_send = True
                # State changes do not promise foreground activation. In particular,
                # restore_window requests normal bounds; focus restores prior state.
                command = {"maximize_window": win32con.SW_SHOWMAXIMIZED,
                           "restore_window": win32con.SW_SHOWNORMAL,
                           "minimize_window": win32con.SW_MINIMIZE}[op]
                user32.ShowWindow(target["handle"], command)
                return {}
            if op == "close_window":
                self._check_action()
                win32gui.PostMessage(target["handle"], win32con.WM_CLOSE, 0, 0)
                self._did_send = True
                return {}
            if op == "terminate_app":
                handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, target["pid"])
                try:
                    self._check_action()
                    win32api.TerminateProcess(handle, 1)
                    self._did_send = True
                finally: handle.Close()
                return {}
            self._fresh(target, foreground=True, geometry=True)
            if op in ("click", "move", "hover", "scroll"):
                self._point(target, args["at"])
                if op == "click":
                    for _ in range(args.get("count", 1)):
                        self._fresh(target, foreground=True, geometry=True)
                        self._verify_semantic_point(target, args["at"])
                        self._hold("mouse", args.get("button", "left"))
                        time.sleep(.03)
                        self.release()
                elif op == "scroll":
                    self._mouse(0x1000 if args.get("axis") == "horizontal" else 0x800, args["amount"]*120)
                elif op == "hover":
                    stop = min(deadline, time.monotonic()+args.get("duration", .4))
                    while time.monotonic() < stop:
                        self._fresh(target, foreground=True)
                        time.sleep(.01)
            elif op == "keys":
                self._keys(target, args["keys"], args.get("hold", 0))
            elif op in ("type_text", "paste_text"):
                if op == "paste_text":
                    # Preflight/snapshot before any click or Ctrl+A: an unsupported
                    # clipboard must not leave a partially modified UI selection.
                    from .windows_clipboard import replace_text
                    self._check_action()
                    self._clipboard = replace_text(args["text"], self._clipboard, check=self._check_action)
                    self.clipboard_changed(self._clipboard)
                if "at" in args:
                    self._point(target, args["at"])
                    self._verify_semantic_point(target, args["at"])
                    self._hold("mouse", "left")
                    self.release()
                if args.get("replace"):
                    self._keys(target, ["ctrl", "a"])
                if op == "paste_text":
                    self._keys(target, ["ctrl", "v"])
                    return {}
                units = args["text"].encode("utf-16-le")
                for offset in range(0, len(units), 128):
                    self._fresh(target, foreground=True)
                    self._check_action()
                    events = []
                    for i in range(offset, min(offset+128, len(units)), 2):
                        code = int.from_bytes(units[i:i+2], "little")
                        events.extend([INPUT(type=1, ki=KEYBDINPUT(wScan=code, dwFlags=4)), INPUT(type=1, ki=KEYBDINPUT(wScan=code, dwFlags=6))])
                    self._send(events)
            elif op in ("drag", "swipe"):
                # Revalidate both endpoints before button down; then at every move.
                self._point(target, args["end"])
                self._point(target, args["start"])
                self._verify_semantic_point(target, args["end"], hit_test=False)
                duration = min(args.get("duration", .4), timeout)
                self._hold("mouse", args.get("button", "left"))
                count = max(2, int(duration/.01))
                next_destination_check = time.monotonic()
                for i in range(1, count+1):
                    if time.monotonic() >= deadline:
                        raise AxisError("DEADLINE_EXCEEDED", "Gesture deadline exceeded")
                    if time.monotonic() >= next_destination_check or i == count:
                        self._verify_semantic_point(target, args["end"], hit_test=False)
                        next_destination_check = time.monotonic()+.1
                    fraction = i/count
                    point = {k: round(args["start"][k]+(args["end"][k]-args["start"][k])*fraction) for k in ("x", "y")}
                    self._point(target, point)
                    time.sleep(duration/count)
                self.release()
            elif op == "set_slider":
                wanted = args["at"].get("native_id")
                if not wanted:
                    raise AxisError("INVALID_LOCATOR", "Slider value requires a semantic locator")
                control = self._verify_semantic_point(target, args["at"])
                pattern = control.GetPattern(self.auto.PatternId.RangeValuePattern) if control else None
                if not pattern or pattern.IsReadOnly:
                    raise AxisError("CAPABILITY_UNAVAILABLE", "Slider has no writable native range")
                if not pattern.Minimum <= args["value"] <= pattern.Maximum:
                    raise AxisError("INVALID_VALUE", "Slider value outside native range")
                self._fresh(target, foreground=True, geometry=True)
                self._check_action()
                self._did_send = True
                pattern.SetValue(args["value"])
            else:
                raise AxisError("CAPABILITY_UNAVAILABLE", "Unsupported native operation")
            return {}
        except AxisError as exc:
            if self._did_send and exc.dispatch == "not_sent":
                exc.dispatch = "sent"
            raise
        finally:
            try:
                self.release()
            finally:
                self._action_deadline = None

    def ocr(self, target, region):
        from .windows_ocr import recognize
        return recognize(self.capture(target), region)

    def events(self, target, since=0):
        from .windows_events import Subscription
        self._fresh(target)
        key = target["target_id"]
        if key not in self._subscriptions:
            for old_key, subscription in list(self._subscriptions.items()):
                try:
                    live = self._id(self._identity(subscription.target["handle"])) == old_key
                except (AxisError, win32api.error):
                    live = False
                if not live:
                    subscription.close()
                    del self._subscriptions[old_key]
            if len(self._subscriptions) >= 32:
                raise AxisError("RESOURCE_LIMIT", "Native subscription limit reached")
            self._subscriptions[key] = Subscription(target)
        return self._subscriptions[key].read(since)

    def pump_events(self):
        win32gui.PumpWaitingMessages()

    def close(self):
        try:
            self.release()
        finally:
            for subscription in self._subscriptions.values():
                subscription.close()
            self._lifetimes.close()
            self.release_lease()
            self._mutex.Close()
            pythoncom.CoUninitialize()
