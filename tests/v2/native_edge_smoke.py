"""Opt-in native Edge customer and CSV upload smoke; never release certification."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading

from testbench.server import Store, TestbenchServer

from cu_suite.v2.contracts import compile_steps
from .native_harness import NativeHarness
from .verify_edge_workflow import verify

NAME = {"role": "Edit", "name": "Name"}
EMAIL = {"role": "Edit", "name": "Email"}
COMPANY = {"role": "Edit", "name": "Company"}
PLAN = {"role": "ComboBox", "name": "Plan"}
STARTER_OPTION = {"role": "ListItem", "name": "Starter"}
TEAM_OPTION = {"role": "ListItem", "name": "Team"}
SAVE = {"role": "Button", "name": "Save customer"}
EDIT_MAYA = {"role": "Button", "name": "Edit Maya Chen"}
CUSTOMERS = {"role": "Button", "name": "03 Customers"}
SEARCH = {"role": "Edit", "automation_id": "customer-search"}
UPLOAD = {"automation_id": "file-upload"}
FILE_NAME = {"role": "Edit", "automation_id": "1148"}
COMPANY_VALUE = "AXIS élève 中文 😀"
EMAIL_VALUE = "maya.chen+ops@example.test"
STAGES = ("launch", "customers", "search_customer", "edit_customer", "save_customer", "reopen_customer",
          "documents", "upload_dialog", "upload", "verify", "close")


class SmokeFailed(RuntimeError):
    pass


def value(selector, expected):
    return {"kind": "value", "selector": selector, "expected": expected}


def require_job(result, *, requested_steps=None):
    if (not isinstance(result, dict) or result.get("status") != "completed"
            or result.get("next_cursor") or result.get("error")):
        raise SmokeFailed("Native plan was incomplete or unresolved; preserve result and original key; no retry")
    steps = result.get("steps", [])
    if requested_steps == upload_open_steps():
        # Only this one click crosses into a separately discovered native window.
        # This is dispatch evidence, NOT effect verification or workflow success.
        if (len(steps) != 1 or steps[0].get("id") != "choose_file"
                or steps[0].get("op") != "click" or steps[0].get("dispatch") != "sent"
                or steps[0].get("verification") != "unobservable" or steps[0].get("error")
                or result.get("effects_verified") is not False):
            raise SmokeFailed("File-dialog dispatch unresolved; no retry")
    elif (result.get("effects_verified") is not True
          or any(s.get("verification") != "met" or s.get("dispatch") == "unknown" or s.get("error") for s in steps)):
        raise SmokeFailed("Native plan effects remain unverified")
    return result


def customer_save_steps():
    return [
        {"id": "email", "op": "type_text", "args": {"at": {"selector": EMAIL}, "replace": True, "text": EMAIL_VALUE}, "postcondition": value(EMAIL, EMAIL_VALUE)},
        {"id": "company", "op": "type_text", "args": {"at": {"selector": COMPANY}, "replace": True, "text": COMPANY_VALUE}, "postcondition": value(COMPANY, COMPANY_VALUE)},
        {"id": "open_plan", "op": "click", "args": {"at": {"selector": PLAN}}, "postcondition": {"kind": "selected", "selector": STARTER_OPTION, "expected": True}},
        # An open Chromium select moves focus/highlight before committing the
        # SelectionItem state. The ComboBox value is verified after Enter below.
        {"id": "choose_team", "op": "keys", "args": {"keys": ["down"]}, "postcondition": {"kind": "focused", "selector": TEAM_OPTION, "expected": True}},
        {"id": "commit_team", "op": "keys", "args": {"keys": ["enter"]}, "postcondition": value(PLAN, "Team")},
        {"id": "save", "op": "click", "args": {"at": {"selector": SAVE}}, "postcondition": {"kind": "absent", "selector": EMAIL}},
    ]


def customer_search_steps():
    return [
        {"id": "search", "op": "type_text", "args": {"at": {"selector": SEARCH}, "text": "Maya Chen", "replace": True},
         "postcondition": value(SEARCH, "Maya Chen")},
        {"id": "found", "op": "await", "args": {"condition": {"kind": "exists", "selector": EDIT_MAYA}}},
    ]


def documents_navigation_steps(base_url):
    return [
        {"id": "close_form", "op": "keys", "args": {"keys": ["escape"]}, "postcondition": {"kind": "absent", "selector": EMAIL}},
        {"id": "focus_address", "op": "keys", "args": {"keys": ["ctrl", "l"]}, "postcondition": {"kind": "focused", "selector": {"role": "Edit", "automation_id": "view_1021"}, "expected": True}},
        {"id": "address", "op": "type_text", "args": {"text": base_url + "/#documents", "replace": True}, "postcondition": value({"role": "Edit", "automation_id": "view_1021"}, base_url + "/#documents")},
        {"id": "navigate", "op": "keys", "args": {"keys": ["enter"]}, "postcondition": {"kind": "name", "selector": {"role": "Document", "automation_id": "RootWebArea"}, "expected": "Documents · AXIS Training Ground"}},
    ]


def upload_open_steps():
    return [{"id": "choose_file", "op": "click", "args": {"at": {"selector": UPLOAD}}, "verification": "dispatch_only"}]


def upload_file_steps(fixture):
    return [
        {"id": "path", "op": "type_text", "args": {"at": {"selector": FILE_NAME}, "text": str(fixture), "replace": True}, "postcondition": value(FILE_NAME, str(fixture))},
        {"id": "open", "op": "keys", "args": {"keys": ["enter"]}, "postcondition": {"kind": "window_closed"}},
    ]


def validate_plan(steps):
    """The only dispatch-only exception is the exact owned file-dialog trigger."""
    compile_steps(steps)
    if any(s.get("verification") == "dispatch_only" for s in steps) and steps != upload_open_steps():
        raise SmokeFailed("dispatch_only action lacks a later UI verification")
    return steps


def submit_once(host, session, steps):
    """Submit one native plan once; an uncertain result is never replayed."""
    return require_job(host.run(session, validate_plan(steps)), requested_steps=steps)


def require_element(result, selector):
    if isinstance(result, dict) and result.get("error"):
        raise SmokeFailed("Observation failed: " + str(result["error"].get("code", "unknown")))
    if not isinstance(result, dict) or result.get("coverage") != "complete" or result.get("next_cursor"):
        raise SmokeFailed("Observation incomplete")
    matches = [e for e in result.get("elements", []) if all(e.get(k) == v for k, v in selector.items())]
    if len(matches) != 1:
        raise SmokeFailed("Expected unique observed UIA element")
    return matches[0]


def source_hash():
    root = Path(__file__).resolve().parents[2]
    paths = sorted(p for p in (root / "cu_suite/v2").rglob("*") if p.suffix in (".py", ".ps1"))
    paths += [Path(__file__), Path(__file__).with_name("native_harness.py"),
              Path(__file__).with_name("verify_edge_workflow.py")]
    paths += sorted(p for p in (root / "testbench").rglob("*")
                    if p.is_file() and (p.suffix in (".py", ".html", ".js", ".css") or "assets" in p.parts))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.resolve().relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _record_observation(host, report, directory, stage, result):
    entry = report["stages"].get(stage)
    if not isinstance(entry, dict):
        entry = {}
        report["stages"][stage] = entry
    entry.setdefault("observations", []).append({"query": result.get("query"), "result": result})
    _checkpoint(report, directory)
    return result


def _checkpoint(report, directory):
    temp = directory / "report.json.tmp"
    temp.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    temp.replace(directory / "report.json")


def diagnose_cycle(report, directory):
    """Read-only comparison while the original UIA client/runtime is still alive."""
    jobs = (report["stages"].get("save_customer") or {}).get("native_jobs", [])
    if not jobs:
        return
    job = jobs[-1]
    steps, error = job.get("steps", []), job.get("error") or {}
    cleanup = job.get("cleanup") or {}
    if (error.get("code") != "OBSERVATION_UNAVAILABLE"
            or error.get("message") != "Native accessibility traversal cycle"
            or not steps or steps[-1].get("id") != "open_plan"
            or steps[-1].get("op") != "click" or steps[-1].get("dispatch") != "sent"
            or cleanup.get("state") != "confirmed" or cleanup.get("owned_input_count") != 0
            or cleanup.get("clipboard_pending") is not False):
        return
    pid = report["stages"]["launch"]["native_jobs"][0]["steps"][0]["output"]["process_id"]
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid diagnostic test process identity")
    from .native_uia_search_probe import supervise
    def checkpoint(record):
        report["uia_cycle_diagnostic"] = record
        _checkpoint(report, directory)
    checkpoint(supervise(pid, "list_items", False, checkpoint, same_client=True))


def diagnose_plan_state(host, session, report, directory):
    """Reconcile a sent Down key without replay, before losing the native client."""
    jobs = (report["stages"].get("save_customer") or {}).get("native_jobs", [])
    if not jobs or host is None or session is None:
        return
    job = jobs[-1]
    steps, cleanup = job.get("steps", []), job.get("cleanup") or {}
    if (not steps or steps[-1].get("id") != "choose_team" or steps[-1].get("dispatch") != "sent"
            or cleanup.get("state") != "confirmed" or cleanup.get("owned_input_count") != 0
            or cleanup.get("clipboard_pending") is not False):
        return
    report["plan_failure_observations"] = []
    for query in ({"role": "ListItem"}, PLAN):
        result = host.call("axis.observe", {"session_id": session, "query": query})
        report["plan_failure_observations"].append({"query": query, "result": result})
        _checkpoint(report, directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New, empty run directory")
    parser.add_argument("--diagnose-uia-cycle", action="store_true", help="Read-only search comparison after the known Plan failure; never retries input")
    parser.add_argument("--diagnose-plan-state", action="store_true", help="Observe Plan and options after a sent but unverified Down key; no replay")
    args = parser.parse_args(argv)
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"kind": "native_edge_smoke", "finished": False, "passed": False,
              "release_certified": False, "model_calls": 0, "returned_images": 0,
              "source_sha256": source_hash(), "profile": "English Testbench app; French Edge/native file dialog",
              "stages": {stage: None for stage in STAGES}}
    _checkpoint(report, directory)
    host = store = server = thread = page = None

    def run(stage, session, steps):
        result = host.run(session, validate_plan(steps))
        entry = report["stages"].get(stage)
        if not isinstance(entry, dict):
            entry = {}
            report["stages"][stage] = entry
        entry.setdefault("native_jobs", []).append(result)
        _checkpoint(report, directory)
        return require_job(result, requested_steps=steps)

    try:
        database = directory / "testbench.sqlite3"
        store = Store(database)
        server = TestbenchServer(("127.0.0.1", 0), store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = "http://127.0.0.1:%d" % server.server_address[1]
        expected_run_id = store.setting("run_id")  # Oracle binding only; never supplied to AXIS.
        report["oracle_binding"] = {"expected_run_id": expected_run_id, "base_url": base_url,
                                    "database": str(database)}
        _checkpoint(report, directory)
        fixture = Path(__file__).resolve().parents[2] / "testbench/assets/contacts.csv"
        host = NativeHarness(directory, ["msedge"])
        desktop = host.call("axis.observe", {})["session_id"]
        profile = directory / "edge-guest-profile"
        opened = run("launch", desktop, [
            {"id": "open", "op": "open_app", "args": {"app": "msedge", "args": [
                "--user-data-dir=" + str(profile), "--guest", "--no-first-run", "--new-window", base_url + "/#customers"]}},
            {"id": "focus", "op": "focus", "target_from": "open", "args": {"method": "caption_click"}},
            {"id": "ready", "op": "await", "target_from": "open", "args": {"condition": {"kind": "exists", "selector": CUSTOMERS}}},
            {"id": "observe", "op": "observe", "target_from": "open", "args": {"query": CUSTOMERS}},
        ])
        edge_target = opened["steps"][0]["output"]["target_id"]
        page = opened["steps"][-1]["output"]["session_id"]
        require_element(opened["steps"][-1]["output"], CUSTOMERS)
        run("customers", page, [{"id": "customers", "op": "click", "args": {"at": {"selector": CUSTOMERS}},
                                 "postcondition": {"kind": "exists", "selector": SEARCH}}])
        require_element(_record_observation(host, report, directory, "search_customer",
            host.call("axis.observe", {"session_id": page, "query": SEARCH})), SEARCH)
        run("search_customer", page, customer_search_steps())
        require_element(_record_observation(host, report, directory, "edit_customer",
            host.call("axis.observe", {"session_id": page, "query": EDIT_MAYA})), EDIT_MAYA)
        run("edit_customer", page, [{"id": "edit", "op": "click", "args": {"at": {"selector": EDIT_MAYA}},
                                     "postcondition": value(EMAIL, "maya.chen@example.test")}])
        for selector in (NAME, EMAIL, COMPANY, PLAN, SAVE):
            element = require_element(_record_observation(host, report, directory, "edit_customer",
                host.call("axis.observe", {"session_id": page, "query": selector})), selector)
            if selector == PLAN and element.get("value") != "Starter":
                raise SmokeFailed("Expected initial Starter plan; refusing blind relative selection")
        run("save_customer", page, customer_save_steps())
        require_element(_record_observation(host, report, directory, "reopen_customer",
            host.call("axis.observe", {"session_id": page, "query": EDIT_MAYA})), EDIT_MAYA)
        run("reopen_customer", page, [
            {"id": "reopen", "op": "click", "args": {"at": {"selector": EDIT_MAYA}}, "postcondition": value(EMAIL, EMAIL_VALUE)},
            {"id": "check_company", "op": "await", "args": {"condition": value(COMPANY, COMPANY_VALUE)}},
            {"id": "check_plan", "op": "await", "args": {"condition": value(PLAN, "Team")}},
        ])
        require_element(_record_observation(host, report, directory, "reopen_customer",
            host.call("axis.observe", {"session_id": page, "query": COMPANY})), COMPANY)
        require_element(_record_observation(host, report, directory, "reopen_customer",
            host.call("axis.observe", {"session_id": page, "query": PLAN})), PLAN)
        address_bar = {"role": "Edit", "automation_id": "view_1021"}
        require_element(_record_observation(host, report, directory, "documents",
            host.call("axis.observe", {"session_id": page, "query": address_bar})), address_bar)
        run("documents", page, documents_navigation_steps(base_url))
        require_element(_record_observation(host, report, directory, "documents",
            host.call("axis.observe", {"session_id": page, "query": UPLOAD})), UPLOAD)
        launch_result = run("upload_dialog", page, upload_open_steps())
        targets = host.call("axis.targets", {})
        owned_dialogs = [t for t in targets.get("targets", []) if t.get("owner_target_id") == edge_target]
        if len(owned_dialogs) != 1:
            raise SmokeFailed("Could not uniquely identify the owned native file dialog")
        dialog = owned_dialogs[0]
        dialog_session = host.call("axis.observe", {"target_id": dialog["target_id"], "query": FILE_NAME})
        file_edit = require_element(_record_observation(host, report, directory, "upload_dialog", dialog_session), FILE_NAME)
        if file_edit.get("value") not in (None, ""):
            raise SmokeFailed("Native file name field is not blank; refusing unintended selection")
        report["stages"]["upload_dialog"]["dialog_followup_verification"] = {
            "owned_target_id": dialog["target_id"], "file_name_selector_observed": True,
            "click_effects_verified": launch_result.get("effects_verified") is True,
        }
        _checkpoint(report, directory)
        run("upload", dialog_session["session_id"], upload_file_steps(fixture))
        run("upload", page, [{"id": "upload_complete", "op": "await", "args": {"condition": {
            "kind": "name", "selector": {"automation_id": "upload-status"},
            "expected": "contacts.csv uploaded and saved."}}}])
        status = require_element(_record_observation(host, report, directory, "upload",
            host.call("axis.observe", {"session_id": page, "query": {"automation_id": "upload-status"}})),
            {"automation_id": "upload-status"})
        if status.get("name") != "contacts.csv uploaded and saved.":
            raise SmokeFailed("Upload completion status was not visibly verified")
        oracle = verify(base_url, fixture, expected_run_id=expected_run_id)
        report["stages"]["verify"] = {"kind": "read_only_oracle", "result": oracle}
        _checkpoint(report, directory)
        if oracle.get("passed") is not True:
            raise SmokeFailed("Independent workflow oracle failed")
        current = host.call("axis.targets", {})
        owned = [t for t in current.get("targets", []) if t.get("target_id") == edge_target]
        if len(owned) != 1:
            raise SmokeFailed("Owned Edge window no longer uniquely identified; refusing close")
        run("close", page, [{"id": "close_owned_edge", "op": "close_window"}])
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error={"type": type(exc).__name__, "message": str(exc)},
                      cleanup_note="Failure evidence retained; no action retry or forced close was attempted.")
        if args.diagnose_uia_cycle:
            try:
                diagnose_cycle(report, directory)
            except Exception as diagnostic_error:
                report["uia_cycle_diagnostic_error"] = {"type": type(diagnostic_error).__name__}
        if args.diagnose_plan_state:
            try:
                diagnose_plan_state(host, page, report, directory)
            except Exception as diagnostic_error:
                report["plan_state_diagnostic_error"] = {"type": type(diagnostic_error).__name__}
    finally:
        if host is not None:
            try:
                host.close()
            except Exception as exc:
                report.update(passed=False, cleanup_error={"type": type(exc).__name__, "message": str(exc)})
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
                thread.join(2)
            server.server_close()
        if store is not None:
            store.close()
        report["finished"] = True
        _checkpoint(report, directory)
    print(json.dumps({"passed": report["passed"], "report": str(directory / "report.json"), "release_certified": False}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
