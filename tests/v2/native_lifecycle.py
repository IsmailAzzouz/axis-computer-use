"""Two homonymous native windows, explicit activation, key cancellation/save guard.

The harness alone reads fixture oracle files and OS key state. AXIS never sees
those oracle values. No force-termination authority is granted.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from .native_harness import NativeHarness


def main():
    import win32api
    import win32gui
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    host = NativeHarness(args.output, [sys.executable])
    sessions, targets, checks, details = [], [], {}, {}
    def oracle(index):
        return json.loads((host.output/f"oracle-{index}.json").read_text(encoding="utf-8"))
    try:
        desktop = host.call("axis.observe")["session_id"]
        for i, x in enumerate((70, 800)):
            launch_args = [str(Path(__file__).resolve().parents[2]/"testbench/native_fixture_v2.py"),
                           "--oracle", str(host.output/f"oracle-{i}.json"), "--x", str(x), "--y", "80"]
            if i == 0: launch_args.append("--save-dialog")
            opened = host.run(desktop, [{"id": "open", "op": "open_app", "args": {"app": sys.executable, "args": launch_args}}])
            assert opened["status"] == "completed", opened
            target = opened["steps"][0]["output"]["target_id"]
            targets.append(target)
            sessions.append(host.call("axis.observe", {"target_id": target})["session_id"])
        listed = host.call("axis.targets")["targets"]
        checks["homonyms_distinct"] = len(targets) == len(set(targets)) == 2 and len({w["title"] for w in listed if w["target_id"] in targets}) == 1
        # Native read-only placement is independent of AXIS's state assertion.
        handle = next(w["handle"] for w in listed if w["target_id"] == targets[1])
        state_results = []
        for op, expected in (("maximize_window", 3), ("minimize_window", 2), ("restore_window", 1)):
            changed = host.run(sessions[1], [{"id": "state", "op": op}])
            actual = win32gui.GetWindowPlacement(handle)[1]
            state_results.append({"op": op, "expected": expected, "actual": actual, "result": changed})
        details["window_states"] = state_results
        checks["window_state_readback"] = all(r["result"]["effects_verified"] and r["actual"] == r["expected"] for r in state_results)
        normal_bounds = win32gui.GetWindowRect(handle)
        minimized = host.run(sessions[1], [{"id": "minimize", "op": "minimize_window"}])
        restored_focus = host.run(sessions[1], [{"id": "restore-focus", "op": "focus", "args": {"method": "caption_click"}}])
        checks["focus_restores_without_maximizing"] = (minimized["effects_verified"] and restored_focus["effects_verified"]
            and win32gui.GetWindowPlacement(handle)[1] == 1 and win32gui.GetWindowRect(handle) == normal_bounds)
        details["restore_focus"] = restored_focus
        # Bring window B forward, then test physical caption activation of A.
        host.run(sessions[1], [{"id": "b", "op": "focus", "args": {"method": "caption_click"}}])
        focused = host.run(sessions[0], [{"id": "a", "op": "focus", "args": {"method": "caption_click"}}])
        details["focus"] = focused
        checks["caption_activation"] = focused["status"] == "completed" and focused["steps"][0]["output"].get("activation_method") == "caption_click"
        typed = host.run(sessions[0], [{"id": "type", "op": "type_text", "args": {
            "at": {"selector": {"automation_id": "101", "role": "Edit"}}, "text": "Only window A"},
            "postcondition": {"kind": "value", "selector": {"automation_id": "101", "role": "Edit"}, "expected": "Only window A"}}])
        checks["correct_homonymous_target"] = typed["status"] == "completed" and oracle(0)["text"] == "Only window A" and oracle(1)["text"] == ""
        held = host.run(sessions[0], [{"id": "hold", "op": "keys", "args": {"keys": ["ctrl"], "hold": 5}, "verification": "dispatch_only"}], **{"async": True})
        deadline = time.monotonic()+2
        while not win32api.GetAsyncKeyState(0x11) & 0x8000 and time.monotonic() < deadline: time.sleep(.01)
        observed_down = bool(win32api.GetAsyncKeyState(0x11) & 0x8000)
        cancelled = host.call("axis.job", {"job_id": held["job_id"], "action": "cancel"})
        cancelled = host.finish(cancelled)
        checks["cancel_releases_held_key"] = observed_down and cancelled["status"] == "cancelled" and not win32api.GetAsyncKeyState(0x11) & 0x8000
        details["cancel"] = cancelled
        closed = host.run(sessions[0], [{"id": "close", "op": "close_window", "timeout": .5}])
        details["save_guard"] = closed
        checks["save_dialog_never_forced"] = closed["status"] != "completed" and oracle(0)["save_prompted"] and not oracle(0)["closed"]
        # Discard only this fixture's test text, via a button observed in its dialog.
        buttons = host.call("axis.observe", {"session_id": sessions[0], "query": {"role": "Button"}})
        discard = [e for e in buttons.get("elements", []) if e["name"].replace("&", "").lower() in ("no", "non")]
        assert len(discard) == 1, "Could not identify the explicit test discard button"
        result = host.run(sessions[0], [{"id": "discard-test", "op": "click", "args": {"at": {"selector": {"name": discard[0]["name"], "role": "Button"}}}, "postcondition": {"kind": "window_closed"}}])
        checks["explicit_test_discard"] = result["status"] == "completed" and oracle(0)["closed"] and not oracle(0)["saved"]
    except Exception as exc:
        details["error"] = str(exc)
    finally:
        cleanup = []
        for i, session in enumerate(sessions):
            if oracle(i)["closed"]: continue
            result = host.run(session, [{"id": "close", "op": "close_window", "timeout": .5}])
            cleanup.append(result)
        details["cleanup"] = cleanup
        checks["all_test_windows_closed"] = len(sessions) == 2 and all(oracle(i)["closed"] for i in range(2))
        host.close()
    required = {"homonyms_distinct", "caption_activation", "correct_homonymous_target", "cancel_releases_held_key",
                "save_dialog_never_forced", "explicit_test_discard", "all_test_windows_closed",
                "window_state_readback", "focus_restores_without_maximizing"}
    passed = set(checks) == required and all(checks.values()) and "error" not in details
    report = {"route": "MCP/TCP/native", "scripted": True, "checks": checks, "details": details, "passed": passed}
    (host.output/"report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "checks": checks, "error": details.get("error")}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
