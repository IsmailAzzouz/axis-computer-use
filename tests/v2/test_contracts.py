import ast
from pathlib import Path
import pytest

from cu_suite.v2.contracts import ACTION_ARGS, AxisError, SCHEMAS, compile_steps, tool_definitions, validate


@pytest.mark.parametrize("op", list(ACTION_ARGS))
def test_every_operation_rejects_unadvertised_arguments(op):
    schema = next(t["inputSchema"] for t in tool_definitions() if t["name"] == "axis.run")
    request = {"session_id": "s", "idempotency_key": "k", "steps": [{"id": "a", "op": op, "args": {"unadvertised": True}}]}
    with pytest.raises(AxisError):
        validate(request, schema)
    with pytest.raises(AxisError):
        validate(request, SCHEMAS["axis.run"])


@pytest.mark.parametrize("count", [True, False, 0, 3, "1", 1.0])
def test_click_count_cannot_coerce_bool_or_float(count):
    with pytest.raises(AxisError):
        compile_steps([{"id": "a", "op": "click", "verification": "dispatch_only", "args": {"at": {"selector": {"name": "Input"}}, "count": count}}])


@pytest.mark.parametrize("op,args", [
    ("click", {"at": {"selector": {"name": "a"}}}),
    ("type_text", {"text": "a"}),
    ("paste_text", {"text": "a"}),
    ("keys", {"keys": ["enter"]}),
])
def test_effect_verification_is_selected_before_dispatch(op, args):
    with pytest.raises(AxisError):
        compile_steps([{"id": "a", "op": op, "args": args}])


def test_paste_cannot_restore_clipboard_after_unverified_dispatch():
    with pytest.raises(AxisError):
        compile_steps([{"id": "a", "op": "paste_text", "verification": "dispatch_only", "args": {"text": "x"}}])


def test_replay_verification_is_required_before_playback():
    with pytest.raises(AxisError):
        compile_steps([{"id": "watch", "op": "observe"}, {"id": "play", "op": "replay",
                       "args": {"watch_step": "watch"}, "verification": "dispatch_only"}])


@pytest.mark.parametrize("condition", [
    {"kind": "value"}, {"kind": "name"}, {"kind": "name", "expected": True},
    {"kind": "focused", "expected": 1}, {"kind": "enabled", "expected": "true"},
    {"kind": "visible", "expected": "true"}, {"kind": "window_state", "expected": "fullscreen"},
])
def test_invalid_predicate_rejected_before_any_step(condition):
    with pytest.raises(AxisError):
        compile_steps([{"id": "a", "op": "focus"}, {"id": "b", "op": "await",
                       "args": {"condition": {**condition, "selector": {"role": "Edit"}}}}])


def test_core_has_no_os_branch_or_native_import():
    root = Path(__file__).resolve().parents[2]/"cu_suite"/"v2"
    for name in ("runtime.py", "contracts.py", "pal.py", "perception.py", "worker.py"):
        source = (root/name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.startswith(("win32", "ctypes", "uiautomation", "Quartz")) for n in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("win32", "ctypes", "uiautomation", "Quartz"))
        assert "sys.platform" not in source and "platform.system(" not in source


def test_v2_does_not_switch_desktops_or_attach_input_queues():
    root = Path(__file__).resolve().parents[2]/"cu_suite"/"v2"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"SetThreadDesktop", "OpenDesktopW", "SwitchDesktop", "AttachThreadInput"}, path


def test_native_actions_do_not_materialize_unbounded_accessibility_children():
    source = Path(__file__).resolve().parents[2]/"cu_suite/v2/platforms/windows.py"
    assert not any(isinstance(node, ast.Attribute) and node.attr == "GetChildren"
                   for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))))
