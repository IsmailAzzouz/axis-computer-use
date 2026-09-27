"""Read-only UIA search experiment; never dispatches input or launches an app.

Each search runs in its own supervised diagnostic process. A hung provider is
not retried; only that diagnostic child is stopped. This is not certification.
"""
import argparse
from array import array
import json
import multiprocessing
from pathlib import Path
import time


def search(uia, root, condition, *, cache=None, limit=16, seconds=8, progress=lambda _: None):
    started = time.monotonic()
    report = {"complete": False, "calls": 0, "matches": [], "error": None}
    seen = set()
    try:
        for _ in range(limit):
            if time.monotonic()-started >= seconds:
                raise ValueError("budget_exhausted")
            report["calls"] += 1
            progress(report)
            # TreeScope_Subtree includes the root. Cache only the returned
            # element, never all descendants or an unbounded FindAll array.
            node = (root.FindFirstBuildCache(7, condition, cache) if cache is not None
                    else root.FindFirst(7, condition))
            if time.monotonic()-started >= seconds:
                raise ValueError("budget_exhausted")
            if not node:
                report["complete"] = True
                break
            ancestor = node
            for _ in range(64):
                if not ancestor:
                    raise ValueError("scope_escape")
                if uia.CompareElements(ancestor, root):
                    break
                ancestor = uia.RawViewWalker.GetParentElement(ancestor)
            else:
                raise ValueError("ancestry_limit")
            key = tuple(node.GetRuntimeId())
            if not key or len(key) > 64 or any(type(x) is not int for x in key):
                raise ValueError("invalid_runtime_id")
            if key in seen:
                raise ValueError("exclusion_ignored")
            seen.add(key)
            name = node.CurrentName
            report["matches"].append({"name": name if name in {"Plan", "Starter", "Team", "Business"}
                                      else "[not retained]", "runtime_id": list(key),
                                      "control_type": node.CurrentControlType})
            # RuntimeIdProperty = 30000, SAFEARRAY(I4), not SAFEARRAY(VARIANT).
            exclusion = uia.CreatePropertyCondition(30000, array("i", key))
            condition = uia.CreateAndCondition(condition, uia.CreateNotCondition(exclusion))
        else:
            raise ValueError("budget_exhausted")
    except ValueError as exc:
        # Only our fixed diagnostics, not arbitrary provider exception strings.
        allowed = {"budget_exhausted", "scope_escape", "ancestry_limit", "invalid_runtime_id", "exclusion_ignored"}
        report["error"] = str(exc) if str(exc) in allowed else "ValueError"
    except Exception as exc:
        code = getattr(exc, "hresult", None)
        report["error"] = {"type": type(exc).__name__,
                           "hresult": f"0x{code & 0xffffffff:08X}" if type(code) is int else None}
    report["seconds"] = time.monotonic()-started
    return report


def worker(connection, pid, kind, cached, same_client=False):
    platform = None
    try:
        from cu_suite.v2.platforms.windows import WindowsPlatform
        platform = WindowsPlatform()
        matches = [t for t in platform.targets() if t["pid"] == pid and t.get("owner_target_id") is None
                   and t["native_class"] == "Chrome_WidgetWin_1" and "AXIS" in t["title"]]
        if len(matches) != 1:
            raise ValueError("test_target_not_unique")
        target = matches[0]
        platform._fresh(target)
        connection.send({"target": {k: target[k] for k in ("identity", "handle", "pid")}})
        uia, auto = platform._uia, platform.auto
        root = uia.ElementFromHandle(target["handle"])
        role = auto.ControlType.ListItemControl if kind == "list_items" else auto.ControlType.ComboBoxControl
        condition = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, role)
        if kind == "plan":
            condition = uia.CreateAndCondition(condition, uia.CreatePropertyCondition(auto.PropertyId.NameProperty, "Plan"))
        modes = [("live_before", False), ("raw_cache", True), ("live_after", False)] if same_client else [("search", cached)]
        comparisons = []
        for name, with_cache in modes:
            platform._fresh(target)
            cache = None
            if with_cache:
                cache = uia.CreateCacheRequest()
                cache.TreeScope = 1  # Cache only the matching element.
                cache.TreeFilter = uia.CreateTrueCondition()  # Raw view, no narrower control-view filter.
            handles = sorted(platform._owned_roots(target))
            result = search(uia, root, condition, cache=cache,
                            progress=lambda report: connection.send({"progress": {"mode": name, **report}}))
            comparisons.append({"mode": name, "owned_before": handles,
                                "owned_after": sorted(platform._owned_roots(target)), "result": result})
            connection.send({"comparisons": comparisons})
        platform._fresh(target)
        connection.send({"result": result})
    except Exception as exc:
        connection.send({"error": {"type": type(exc).__name__,
                                   "message": "test_target_not_unique" if str(exc) == "test_target_not_unique" else "diagnostic_failed"}})
    finally:
        if platform is not None:
            platform.close()
        connection.close()


def supervise(pid, kind, cached, checkpoint, *, same_client=False):
    context = multiprocessing.get_context("spawn")
    incoming, outgoing = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(outgoing, pid, kind, cached, same_client))
    record = {"query": kind, "raw_cache": cached, "input_sent": False}
    try:
        process.start()
        outgoing.close()
        deadline = time.monotonic()+(30 if same_client else 15)
        while time.monotonic() < deadline:
            try:
                if incoming.poll(.05):
                    record.update(incoming.recv())
                    checkpoint(record)
                elif not process.is_alive():
                    break
            except (EOFError, BrokenPipeError):
                # Windows may signal a closed pipe from poll(), not recv().
                break
        process.join(.1)
        if process.is_alive():
            record["supervisor_error"] = "diagnostic_timeout"
            process.terminate()  # Only our read-only diagnostic child; no app.
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join(3)
        record["exitcode"] = process.exitcode
        if "result" not in record and "error" not in record:
            record.setdefault("supervisor_error", "diagnostic_no_result")
        return record
    finally:
        incoming.close()
        outgoing.close()
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(3)
        if process.pid is not None and not process.is_alive():
            process.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--same-client", action="store_true", help="Bracket raw-cache with two live searches on the same client")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    with output.open("x", encoding="utf-8") as stream:
        report = {"kind": "native_uia_read_only_search", "pid": args.pid, "input_sent": False, "queries": []}
        def checkpoint(record):
            report["current"] = record
            stream.seek(0)
            json.dump(report, stream, indent=2)
            stream.truncate()
            stream.flush()
        for cached in ((False,) if args.same_client else (False, True)):
            for kind in (("list_items",) if args.same_client else ("list_items", "plan")):
                report["queries"].append(supervise(args.pid, kind, cached, checkpoint, same_client=args.same_client))
                checkpoint({})
        report["finished"] = True
        checkpoint({})
    print(json.dumps({"report": str(output), "input_sent": False}))


if __name__ == "__main__":
    main()
