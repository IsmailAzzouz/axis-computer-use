"""Opt-in native Excel text/formula persistence smoke, not 100-trial certification.

Only a new /x Excel instance and a new output workbook are touched. No COM object
model authoring, browser state, shell keystrokes, forced closure or input retries.
UI labels below are an explicit French Excel profile, validated before use.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from .native_harness import NativeHarness
from .verify_excel_workbook import verify

TEXT = "élève 中文 😀"
FORMULA_BAR = {"role": "Edit", "automation_id": "FormulaBar"}
NEW = {"role": "ListItem", "name": "Nouveau classeur"}
FILENAME = {"role": "Edit", "name": "Nom de fichier :"}
NAME_BOX = {"role": "Edit", "name": "Zone Nom"}
CELLS = (("A1", TEXT, TEXT), ("A2", "21", "21"), ("B1", "2", "2"), ("B2", "=A2*B1", "42"))
STAGES = ("launch", "new", "editor", "cells", "write_commit", "save_dialog", "save", "persisted", "close", "reopen", "reread", "close_reopened")


def cell(address):
    return {"role": "DataItem", "automation_id": address}


def value(selector, expected):
    return {"kind": "value", "selector": selector, "expected": expected}


def selection_checks():
    # Membership proof on known cells, plus independent exact saved range oracle.
    return [{"id": "selected_"+address, "op": "await", "args": {"condition": {
        "kind": "selected", "selector": cell(address), "expected": wanted}}}
        for address, wanted in [("A1", True), ("A2", True), ("B1", True), ("B2", True),
                                ("C1", False), ("C2", False), ("A3", False), ("B3", False)]]


def selection_steps():
    return [
        {"id": "range", "op": "type_text", "args": {"at": {"selector": NAME_BOX}, "text": "A1:B2", "replace": True},
         "postcondition": value(NAME_BOX, "A1:B2")},
        {"id": "select", "op": "keys", "args": {"keys": ["enter"]},
         "postcondition": {"kind": "selected", "selector": cell("B2"), "expected": True}},
        *selection_checks(),
    ]


def write_steps():
    steps = []
    for address, text, committed in CELLS:
        steps.extend([
            {"id": "write_"+address, "op": "type_text", "args": {"at": {"selector": cell(address)}, "text": text},
             "postcondition": value(FORMULA_BAR, text)},
            {"id": "commit_"+address, "op": "keys", "args": {"keys": ["enter"]},
             "postcondition": value(cell(address), committed)},
        ])
    return steps


class SmokeFailed(RuntimeError):
    pass


def require_job(result):
    if result.get("status") != "completed" or result.get("effects_verified") is not True or result.get("next_cursor"):
        raise SmokeFailed("Plan not completely verified; preserve result and original key, no retry")
    return result


def require_element(result, selector):
    if result.get("coverage") != "complete" or result.get("next_cursor"):
        raise SmokeFailed("Observation incomplete")
    matches = [e for e in result.get("elements", []) if all(e.get(k) == v for k, v in selector.items())]
    if len(matches) != 1:
        raise SmokeFailed("Expected unique profile element not observed")
    return matches[0]


def source_hash():
    root = Path(__file__).resolve().parents[2]
    paths = sorted(p for p in (root/"cu_suite/v2").rglob("*") if p.suffix in (".py", ".ps1"))
    paths += [Path(__file__), Path(__file__).with_name("native_harness.py"), Path(__file__).with_name("verify_excel_workbook.py")]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.resolve().relative_to(root).as_posix().encode()+b"\0"+path.read_bytes()+b"\0")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--selection", action="store_true", help="Also verify A1:B2 selection and its exact saved range")
    options = parser.parse_args()
    directory = Path(options.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workbook = directory/"AXIS-text-formula.xlsx"
    report = {"kind": "native_excel_smoke", "release_certified": False, "finished": False,
              "source_sha256": source_hash(), "profile": "Excel French; native UIA; caption_click focus",
              "selection": options.selection, "model_calls": 0, "returned_images": 0,
              "stages": {name: None for name in STAGES + (("name_box", "select_range", "reread_selection") if options.selection else ())}}
    host = None
    def checkpoint():
        temporary = directory/"report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        temporary.replace(directory/"report.json")
    def record(name, result):
        report["stages"][name] = result
        checkpoint()
        return result
    def run(name, session, steps):
        return require_job(record(name, host.run(session, steps)))
    checkpoint()
    try:
        host = NativeHarness(directory, ["excel"])
        desktop = host.call("axis.observe", {})["session_id"]
        launched = run("launch", desktop, [
            {"id": "open", "op": "open_app", "args": {"app": "excel", "args": ["/x"]}},
            {"id": "focus", "op": "focus", "target_from": "open", "args": {"method": "caption_click"}},
            {"id": "startup", "op": "await", "target_from": "open", "args": {"condition": {"kind": "exists", "selector": NEW}}},
            {"id": "read", "op": "observe", "target_from": "open", "args": {"query": NEW}},
        ])
        observed = launched["steps"][-1]["output"]
        require_element(observed, NEW)
        session = observed["session_id"]
        run("new", session, [{"id": "new", "op": "click", "args": {"at": {"selector": NEW}},
                              "postcondition": {"kind": "exists", "selector": cell("A1")}}])
        require_element(record("editor", host.call("axis.observe", {"session_id": session, "query": FORMULA_BAR})), FORMULA_BAR)
        observations = {}
        for address, _, _ in CELLS:
            observations[address] = host.call("axis.observe", {"session_id": session, "query": cell(address)})
            record("cells", observations)
            if require_element(observations[address], cell(address)).get("value") != "":
                raise SmokeFailed("New test cell is not blank; refuse overwrite")
        run("write_commit", session, write_steps())
        if options.selection:
            require_element(record("name_box", host.call("axis.observe", {"session_id": session, "query": NAME_BOX})), NAME_BOX)
            run("select_range", session, selection_steps())
        run("save_dialog", session, [{"id": "dialog", "op": "keys", "args": {"keys": ["f12"]},
                                       "postcondition": {"kind": "exists", "selector": FILENAME}},
                                      {"id": "read", "op": "observe", "args": {"query": FILENAME}}])
        require_element(report["stages"]["save_dialog"]["steps"][-1]["output"], FILENAME)
        if workbook.exists():
            raise SmokeFailed("Test output unexpectedly exists; refuse overwrite")
        run("save", session, [
            {"id": "path", "op": "type_text", "args": {"at": {"selector": FILENAME}, "text": str(workbook), "replace": True},
             "postcondition": value(FILENAME, str(workbook))},
            {"id": "save", "op": "keys", "args": {"keys": ["enter"]}, "postcondition": {"kind": "absent", "selector": FILENAME}},
        ])
        persisted = record("persisted", verify(workbook, expected_selection="A1:B2" if options.selection else None))
        if persisted["passed"] is not True:
            raise SmokeFailed("Independent persisted workbook oracle failed")
        run("close", session, [{"id": "close", "op": "close_window"}])
        reopened = run("reopen", desktop, [
            {"id": "open", "op": "open_app", "args": {"app": "excel", "args": ["/x", str(workbook)]}},
            {"id": "focus", "op": "focus", "target_from": "open", "args": {"method": "caption_click"}},
            {"id": "ready", "op": "await", "target_from": "open", "args": {"condition": value(cell("A1"), TEXT)}},
            {"id": "read", "op": "observe", "target_from": "open", "args": {"query": cell("A1")}},
        ])
        session = reopened["steps"][-1]["output"]["session_id"]
        if options.selection:
            run("reread_selection", session, selection_checks())
        run("reread", session, [{"id": "read_"+address, "op": "await", "args": {"condition": value(cell(address), committed)}}
                               for address, _, committed in CELLS])
        run("close_reopened", session, [{"id": "close", "op": "close_window"}])
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error={"type": type(exc).__name__, "message": str(exc)},
                      cleanup_note="No forced close or discard. Inspect trace for surviving test windows before further input.")
    finally:
        if host is not None:
            try:
                host.close()
            except Exception as exc:
                report.update(passed=False, cleanup_error={"type": type(exc).__name__, "message": str(exc)})
        report["finished"] = True
        checkpoint()
    print(json.dumps({"passed": report.get("passed", False), "report": str(directory/"report.json"), "release_certified": False}))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
