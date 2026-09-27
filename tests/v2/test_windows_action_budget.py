"""Execute the actual adapter class with isolated OS doubles, never desktop APIs.

Only class/ctypes declarations are compiled from its source. Module-level WinDLL,
COM initialization and native imports are deliberately not executed. This is
adapter-logic evidence, NOT native Windows qualification.
"""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from cu_suite.v2.contracts import AxisError


@pytest.fixture
def native():
    state = SimpleNamespace(now=100., calls=[], foreground=1, cursor=(0, 0), closed=0)
    target = {"handle": 1, "pid": 7, "target_id": "test", "identity": "process",
              "geometry_id": "g", "bounds": [0, 0, 100, 100], "minimized": False, "is_active": True}
    def effect(name, *args):
        state.calls.append((name, args, state.now))
        return True
    def cursor(point):
        effect("cursor", point)
        state.cursor = point
    def send(count, inputs, size):
        for value in inputs:
            effect("key" if value.type == 1 else "mouse", value.ki.dwFlags if value.type == 1 else value.mi.dwFlags)
        return count
    handle = SimpleNamespace(Close=lambda: setattr(state, "closed", state.closed+1))
    env = {
        "__package__": "cu_suite.v2.platforms", "ctypes": ctypes, "wintypes": wintypes,
        "ULONG_PTR": ctypes.c_size_t, "AxisError": AxisError,
        "time": SimpleNamespace(monotonic=lambda: state.now, sleep=lambda n: setattr(state, "now", state.now+n)),
        "KEYS": {"ctrl": 17, "a": 65}, "MOUSE": {"left": (2, 4, 1)},
        "win32api": SimpleNamespace(GetAsyncKeyState=lambda _: 0, SetCursorPos=cursor,
            OpenProcess=lambda *_: handle, TerminateProcess=lambda *_: effect("terminate")),
        "win32gui": SimpleNamespace(GetForegroundWindow=lambda: state.foreground,
            GetCursorPos=lambda: state.cursor, PostMessage=lambda *_: effect("close")),
        "win32con": SimpleNamespace(WM_CLOSE=16, PROCESS_TERMINATE=1, SW_SHOWMAXIMIZED=3, SW_SHOWNORMAL=1, SW_MINIMIZE=6, SW_RESTORE=9),
        "user32": SimpleNamespace(SendInput=send, GetAncestor=lambda *_: 1, WindowFromPoint=lambda *_: 1,
            ShowWindow=lambda *_: effect("window"), SetForegroundWindow=lambda *_: effect("focus")),
        "subprocess": SimpleNamespace(Popen=lambda *_args, **_kw: (effect("launch") and SimpleNamespace(pid=7))),
    }
    path = Path(__file__).resolve().parents[2]/"cu_suite/v2/platforms/windows.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.ClassDef)], type_ignores=[]), str(path), "exec"), env)
    adapter = env["WindowsPlatform"].__new__(env["WindowsPlatform"])
    adapter._held, adapter._clipboard, adapter._action_deadline = [], None, None
    adapter._did_send, adapter._owns_lease, adapter._last_cursor = False, True, None
    adapter.cancel = threading.Event()
    adapter.ownership_changed = lambda _: None
    adapter.clipboard_changed = lambda _: None
    adapter._target = lambda _: dict(target)
    adapter._owned_roots = lambda _: {1}
    adapter._verify_semantic_point = lambda *_args, **_kw: None
    adapter.targets = lambda: []
    adapter._resolve_app = lambda _: "fixture.exe"
    return adapter, state, target, env


@pytest.mark.parametrize("op,args", [
    ("open_app", {"app": "fixture"}), ("close_window", {}), ("terminate_app", {}),
    ("focus", {}), ("maximize_window", {}), ("keys", {"keys": ["ctrl", "a"]}),
    ("click", {"at": {"x": 5, "y": 5}}), ("type_text", {"text": "hello"}),
])
def test_cancelled_action_sends_nothing(native, op, args):
    adapter, state, target, _ = native
    adapter.cancel.set()
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, op, args, .1)
    assert error.value.code == "CANCELLED" and error.value.dispatch == "not_sent"
    assert not state.calls and adapter._action_deadline is None


@pytest.mark.parametrize("op", ["open_app", "close_window", "terminate_app", "focus", "maximize_window", "move", "set_slider"])
def test_slow_preparation_cannot_send_late_mutation(native, op):
    adapter, state, target, env = native
    def delay(value):
        state.now += .2
        return value
    args = {}
    if op == "open_app":
        adapter._resolve_app = lambda _: delay("fixture.exe")
        args = {"app": "fixture"}
    elif op == "terminate_app":
        original = env["win32api"].OpenProcess
        env["win32api"].OpenProcess = lambda *a: delay(original(*a))
    elif op in ("focus", "maximize_window"):
        state.foreground = 2
        adapter._check_user_input = lambda: delay(None)
    elif op == "move":
        adapter._owned_roots = lambda _: delay({1})
        args = {"at": {"x": 5, "y": 5}}
    elif op == "set_slider":
        pattern = SimpleNamespace(IsReadOnly=False, Minimum=0, Maximum=100, SetValue=lambda _: state.calls.append("slider"))
        adapter._verify_semantic_point = lambda *_args: SimpleNamespace(GetPattern=lambda _: delay(pattern))
        adapter.auto = SimpleNamespace(PatternId=SimpleNamespace(RangeValuePattern=1))
        args = {"at": {"native_id": "slider"}, "value": 50}
    else:
        adapter._target = lambda _: delay(dict(target))
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, op, args, .1)
    assert error.value.code == "DEADLINE_EXCEEDED" and error.value.dispatch == "not_sent"
    assert not state.calls and adapter._action_deadline is None
    if op == "terminate_app": assert state.closed == 1


def test_second_click_expires_but_first_button_is_released(native):
    adapter, state, target, _ = native
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, "click", {"at": {"x": 5, "y": 5}, "count": 2}, .02)
    assert error.value.code == "DEADLINE_EXCEEDED" and error.value.dispatch == "sent"
    assert [args[0] for name, args, _ in state.calls if name == "mouse"] == [2, 4]
    assert not adapter._held


@pytest.mark.parametrize("cancelled", [False, True])
def test_cleanup_allowed_after_deadline_or_cancel_without_claiming_new_action(native, cancelled):
    adapter, state, _, _ = native
    adapter._action_deadline = 99.
    if cancelled: adapter.cancel.set()
    adapter._held = [("key", 17), ("mouse", "left")]
    adapter.release()
    assert [(name, args[0]) for name, args, _ in state.calls] == [("mouse", 4), ("key", 2)]
    assert not adapter._held and not adapter._did_send


def test_pointer_movement_remains_sent_if_button_later_expires(native):
    adapter, state, target, _ = native
    checks = []
    def semantic(*_args, **_kw):
        checks.append(True)
        if len(checks) == 2: state.now += .2
    adapter._verify_semantic_point = semantic
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, "click", {"at": {"x": 5, "y": 5}}, .1)
    assert error.value.dispatch == "sent" and error.value.code == "DEADLINE_EXCEEDED"
    assert [name for name, _, _ in state.calls] == ["cursor"]


def test_key_hold_stops_at_budget_and_releases(native):
    adapter, state, target, _ = native
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, "keys", {"keys": ["ctrl"], "hold": 5}, .1)
    assert error.value.code == "DEADLINE_EXCEEDED" and error.value.dispatch == "sent"
    assert state.now < 100.2 and not adapter._held
    assert [args[0] for name, args, _ in state.calls if name == "key"] == [0, 2]


def test_expired_ownership_notification_prevents_key_down(native):
    adapter, state, target, _ = native
    def report(held):
        if held: state.now += .2
    adapter.ownership_changed = report
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, "keys", {"keys": ["ctrl"]}, .1)
    assert error.value.code == "DEADLINE_EXCEEDED" and error.value.dispatch == "not_sent"
    # Reservation is conservatively released; no down event reached SendInput.
    assert [args[0] for name, args, _ in state.calls if name == "key"] == [2]
    assert not adapter._held and adapter._action_deadline is None


def test_cancellation_between_text_batches_prevents_further_typing(native):
    adapter, state, target, env = native
    original = env["user32"].SendInput
    calls = []
    def send(count, inputs, size):
        calls.append(count)
        result = original(count, inputs, size)
        adapter.cancel.set()
        return result
    env["user32"].SendInput = send
    with pytest.raises(AxisError) as error:
        adapter.dispatch(target, "type_text", {"text": "x"*200}, 1)
    assert error.value.code == "CANCELLED" and error.value.dispatch == "sent"
    assert calls == [128]  # One 64-code-unit down/up batch; no remaining batches.


def test_failed_key_release_keeps_ownership_after_timeout(native):
    adapter, _, _, env = native
    adapter._action_deadline = 99.
    adapter._held = [("key", 17)]
    env["user32"].SendInput = lambda *_: 0
    with pytest.raises(AxisError) as error:
        adapter.release()
    assert error.value.code == "CLEANUP_FAILED" and error.value.dispatch == "unknown"
    assert adapter._held == [("key", 17)]
