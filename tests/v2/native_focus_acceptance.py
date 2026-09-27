"""Opt-in two-Excel native activation smoke, not a 100-trial certification.

Actions use MCP/TCP/runner/worker. The independent observer only reads the
foreground HWND; it never supplies hidden application state to the runner.
Only newly launched blank test instances are closed, without forced termination.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform

from .native_harness import NativeHarness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import win32gui
    harness = NativeHarness(args.output, ["excel"])
    root = Path(__file__).resolve().parents[2]
    report = {"certified": False, "scope": "two blank Excel instances; four native focus switches and one physical click",
              "platform": platform.platform(), "route": "MCP/TCP/runtime/Windows worker",
              "images_transmitted": 0, "checks": [], "cleanup": [],
              "source_sha256": {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                                ["cu_suite/v2/platforms/windows.py", "cu_suite/v2/platforms/windows_focus.py", "cu_suite/v2/worker.py"]}}
    created = []
    session = None
    try:
        session = harness.call("axis.observe")["session_id"]
        for _ in range(2):
            result = harness.run(session, [{"id": "open", "op": "open_app", "args": {"app": "excel", "args": ["/x"]}},
                                           {"id": "focus", "op": "focus", "target_from": "open"}])
            # Retain a known launched target even if a later step failed.
            for step in result.get("steps", []):
                if step.get("op") == "open_app" and step.get("output", {}).get("target_id"):
                    created.append(step["output"]["target_id"])
            report["checks"].append({"name": "launch", "result": result,
                                     "passed": result.get("status") == "completed" and result.get("effects_verified") is True})
            if not report["checks"][-1]["passed"]:
                raise RuntimeError("Launch/activation did not verify; not retried")
        targets = {target["target_id"]: target for target in harness.call("axis.targets")["targets"]}
        for target_id in created*2:
            hwnd = targets[target_id]["handle"]
            before = win32gui.GetForegroundWindow()
            result = harness.run(session, [{"id": "focus", "op": "focus", "target_id": target_id}])
            after = win32gui.GetForegroundWindow()
            passed = (before != hwnd and after == hwnd and result.get("status") == "completed"
                      and result.get("effects_verified") is True
                      and result["steps"][0].get("output", {}).get("activation_method") == "native")
            report["checks"].append({"name": "switch", "target_id": target_id, "foreground_before": before,
                                     "foreground_after": after, "result": result, "passed": passed})
            if not passed:
                raise RuntimeError("Focus switch did not verify; no retry or later input")
        observation = harness.call("axis.observe", {"target_id": created[-1],
                         "query": {"role": "ListItem", "name": "Nouveau classeur"}})
        result = harness.run(observation["session_id"], [{"id": "new", "op": "click",
                 "args": {"at": {"selector": {"role": "ListItem", "name": "Nouveau classeur"}}},
                 "postcondition": {"kind": "absent", "selector": {"role": "ListItem", "name": "Nouveau classeur"}}}])
        report["checks"].append({"name": "physical_click", "result": result,
                                 "passed": result.get("status") == "completed" and result.get("effects_verified") is True})
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        for target_id in reversed(created):
            try:
                result = harness.run(session, [{"id": "close", "op": "close_window", "target_id": target_id}])
                report["cleanup"].append({"target_id": target_id, "result": result,
                                          "passed": result.get("status") == "completed" and result.get("effects_verified") is True})
            except Exception as exc:
                # Still close the other known test target and preserve the failure.
                report["cleanup"].append({"target_id": target_id, "passed": False, "error": str(exc)})
        try:
            harness.close()
        except Exception as exc:
            report["host_close_error"] = str(exc)
        report["passed"] = (len(report["checks"]) == 7 and all(c["passed"] for c in report["checks"])
                            and len(report["cleanup"]) == 2 and all(c["passed"] for c in report["cleanup"])
                            and "host_close_error" not in report)
        output = Path(args.output).resolve()/"summary.json"
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": [(c["name"], c["passed"]) for c in report["checks"]],
                          "cleanup": [c["passed"] for c in report["cleanup"]], "summary": str(output)}), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
