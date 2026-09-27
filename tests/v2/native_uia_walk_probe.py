"""Read-only, bounded UIA view comparison on one explicitly selected AXIS test PID.

No actions, focus requests, launches, API application writes or screenshots.
Run in an authorized interactive Windows session; this is diagnostic evidence only.
"""
import argparse
import json
from pathlib import Path
import time


def walk(uia, walker, root, *, limit=512, seconds=8):
    started = time.monotonic()
    report = {"complete": False, "visited": 0, "aliases": 0, "matches": [], "error": None}
    seen = set()
    def inside(node):
        for _ in range(64):
            if not node:
                return False
            if uia.CompareElements(node, root):
                return True
            node = uia.RawViewWalker.GetParentElement(node)
        raise ValueError("ancestry_limit")
    def children(node):
        local = set()
        child = walker.GetFirstChildElement(node)
        while child:
            if not inside(child):
                raise ValueError("scope_escape")
            key = tuple(child.GetRuntimeId())
            if key in local:
                raise ValueError("sibling_cycle")
            local.add(key)
            yield child
            child = walker.GetNextSiblingElement(child)
    try:
        stack = [(iter([root]), frozenset())]
        while stack:
            if report["visited"] >= limit or time.monotonic()-started >= seconds:
                raise ValueError("budget_exhausted")
            iterator, ancestors = stack[-1]
            node = next(iterator, None)
            if node is None:
                stack.pop()
                continue
            key = tuple(node.GetRuntimeId())
            if key in ancestors:
                raise ValueError("ancestor_cycle")
            report["visited"] += 1
            if key in seen:
                report["aliases"] += 1
                continue
            seen.add(key)
            # Only these known test labels are retained; never dump desktop text.
            name = node.CurrentName
            if name in {"Plan", "Starter", "Team", "Business"}:
                report["matches"].append({"name": name, "runtime_id": list(key),
                                          "control_type": node.CurrentControlType})
            if len(stack) >= 32:
                raise ValueError("depth_limit")
            stack.append((children(node), ancestors | {key}))
        report["complete"] = True
    except ValueError as exc:
        report["error"] = str(exc)
    except Exception as exc:
        code = getattr(exc, "hresult", None)
        report["error"] = {"type": type(exc).__name__,
                           "hresult": f"0x{code & 0xffffffff:08X}" if type(code) is int else None}
    report["seconds"] = time.monotonic()-started
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", required=True, help="New output file; never overwrites a prior probe")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    with output.open("x", encoding="utf-8") as stream:
        report = {"kind": "native_uia_read_only_views", "pid": args.pid, "input_sent": False, "views": []}
        def checkpoint():
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=True, indent=2)
            stream.truncate()
            stream.flush()
        checkpoint()
        platform = None
        try:
            from cu_suite.v2.platforms.windows import WindowsPlatform
            from uiautomation.uiautomation import _AutomationClient
            platform = WindowsPlatform()
            targets = platform.targets()
            matches = [t for t in targets if t["pid"] == args.pid and t.get("owner_target_id") is None
                       and t["native_class"] == "Chrome_WidgetWin_1" and "AXIS" in t["title"]]
            if len(matches) != 1:
                raise ValueError("Expected unique AXIS test Edge window")
            target = matches[0]
            report["target"] = {k: target[k] for k in ("identity", "handle", "pid", "target_id", "title")}
            handles = sorted(platform._owned_roots(target))
            report["owned_handles"] = handles
            clients = [("adapter", platform._uia), ("library", _AutomationClient.instance().IUIAutomation)]
            for label, uia in clients:
                for handle in handles:
                    platform._fresh(target)
                    # The element and walker come from this SAME UIA client.
                    root = uia.ElementFromHandle(handle)
                    condition = uia.CreateOrCondition(
                        uia.CreatePropertyCondition(platform.auto.PropertyId.ControlTypeProperty,
                                                    platform.auto.ControlType.ListItemControl),
                        uia.CreatePropertyCondition(platform.auto.PropertyId.NativeWindowHandleProperty, handle))
                    for view, walker in (("raw", uia.RawViewWalker), ("control", uia.ControlViewWalker),
                                         ("filtered_list_items", uia.CreateTreeWalker(condition))):
                        report["views"].append({"client": label, "hwnd": handle, "view": view,
                                                "result": walk(uia, walker, root)})
                        platform._fresh(target)
                        checkpoint()
            report["finished"] = True
        except Exception as exc:
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if platform is not None:
                platform.close()
            checkpoint()
    print(json.dumps({"report": str(output), "finished": report.get("finished", False),
                      "error": report.get("error"), "input_sent": False}))


if __name__ == "__main__":
    main()
