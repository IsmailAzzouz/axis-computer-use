"""Opt-in MCP -> TCP -> runtime -> worker -> native fixture acceptance.

Never targets the user's documents. The fixture oracle is read only by this
harness, not by the model-facing runtime. Reports are evidence for these exact
scenarios, not a certification of Excel/Edge or all desktop operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform as system_platform
import secrets
import sys
import threading
import time
import uuid

from cu_suite.v2.mcp import MCPServer
from cu_suite.v2.platforms import create_platform
from cu_suite.v2.runtime import Policy, Runtime
from cu_suite.v2.transport import AxisClient, BrokerServer
from benchmarks.qualification import latency_summary, summarize


def required_scenarios(options):
    required = {name: "action" for name in ("launch", "focus", "unicode_batch", "right_click_menu", "slider_value", "drag", "close")}
    required["native_events"] = "read"
    if options.temporal: required["simon"] = "action"
    if options.ocr: required["ocr"] = "read"
    if options.paste: required["paste"] = "action"
    return required


def source_fingerprint():
    root = Path(__file__).resolve().parents[2]
    paths = sorted(path for path in (root/"cu_suite/v2").rglob("*") if path.suffix in (".py", ".ps1"))
    paths += [Path(__file__).resolve(), root/"testbench/native_fixture_v2.py", root/"benchmarks/qualification.py"]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode()+b"\0"+path.read_bytes()+b"\0")
    return digest.hexdigest()


def write_report(output, name, value):
    # Output is a newly created run directory. Preserve the last complete report
    # if interrupted during serialization/write; never reuse another run's oracle.
    temporary = output/(name+".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")
    temporary.replace(output/name)


def append_trace(output, event):
    # Keep the original idempotency key even if the reply/process is lost. Only
    # fixture tool arguments/results are recorded, never the broker credential.
    with (output/"trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=True)+"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--temporal", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--paste", action="store_true")
    parser.add_argument("--focus-method", choices=("native", "caption_click"), default="native")
    options = parser.parse_args()
    if not 1 <= options.trials <= 10000:
        parser.error("--trials must be between 1 and 10000")
    output = Path(options.output).resolve()
    if output.exists():
        parser.error("--output must be a new run directory; previous evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=False)
    required = required_scenarios(options)
    reports = []
    metrics = {"model_calls": 0, "tool_calls": 0, "images_returned": 0}
    latencies = []
    configuration = {"os": system_platform.platform(), "python": sys.version, "source_sha256": source_fingerprint(),
        "focus_method": options.focus_method, "required_scenarios": required,
        "model": None, "model_settings": None, "model_budget": None,
        "driver": "scripted deterministic harness", "route": "in-process MCP handler/TCP/runtime/native worker"}
    readiness = {}
    finished = False
    all_trials_run = False

    def persist():
        summary = summarize(reports, required, options.trials, finished=finished)
        summary.update(configuration=configuration, readiness=readiness,
                       metrics={**metrics, "tool_latency": latency_summary(latencies)})
        write_report(output, "report.json", reports)
        write_report(output, "summary.json", summary)
        return summary

    persist()  # Record the planned denominator before attempting native setup.
    platform = runtime = broker = thread = None
    try:
        platform = create_platform()
        readiness["capabilities"] = platform.capabilities()
        if not readiness["capabilities"].get("interactive"):
            raise RuntimeError("Interactive desktop unavailable; run with explicit session authorization")
        runtime = Runtime(platform, policy=Policy(apps=frozenset({sys.executable})), journal_path=str(output/("journal-"+uuid.uuid4().hex+".sqlite3")))
        token = secrets.token_hex(32)
        broker = BrokerServer(runtime, token=token, port=0)
        thread = threading.Thread(target=broker.serve_forever, daemon=True)
        thread.start()
        mcp = MCPServer(AxisClient(token=token, port=broker.server_address[1]))
        import win32gui
        import win32process
    except BaseException as exc:
        readiness["setup_error"] = type(exc).__name__
        try:
            if broker:
                if thread and thread.is_alive(): broker.shutdown()
                broker.server_close()
            if runtime: runtime.close()
            elif platform: platform.close()
        finally:
            persist()
        raise

    def call(name, arguments, *, scenario=None):
        if scenario:
            record["scenarios"].setdefault(scenario, {"result": None, "oracle_met": None})
        request = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        append_trace(output, {"phase": "request", "trial": record["trial"], "scenario": scenario, "request": request})
        started = time.monotonic()
        metrics["tool_calls"] += 1
        try:
            response = mcp.handle_request(request)
            append_trace(output, {"phase": "response", "request_id": request["id"], "response": response})
            metrics["images_returned"] += sum(item["type"] == "image" for item in response["result"]["content"])
            result = response["result"]["structuredContent"]
            if scenario: record["scenarios"][scenario]["result"] = result
            return result
        except BaseException as exc:
            append_trace(output, {"phase": "interrupted", "request_id": request["id"], "error_type": type(exc).__name__})
            raise
        finally:
            latencies.append(time.monotonic()-started)

    def run(session, steps=None, *, scenario=None, **kwargs):
        args = {"session_id": session, "idempotency_key": uuid.uuid4().hex, **kwargs}
        if steps is not None: args["steps"] = steps
        result = call("axis.run", args, scenario=scenario)
        deadline = time.monotonic()+65
        while result.get("status") in ("accepted", "running"):
            if time.monotonic() >= deadline:
                raise RuntimeError("Job still running; inspect original job/key, never resubmit")
            time.sleep(.05)
            result = call("axis.job", {"job_id": result["job_id"], "action": "result"}, scenario=scenario)
        return result

    try:
        for trial in range(options.trials):
            oracle = output/f"oracle-{trial}.json"
            session = None
            record = {"trial": trial, "route": configuration["route"], "scenarios": {}, "started": time.time()}
            try:
                desktop = call("axis.observe", {})["session_id"]
                launch = run(desktop, [{"id": "open", "op": "open_app", "args": {"app": sys.executable,
                    "args": [str(Path(__file__).resolve().parents[2]/"testbench"/"native_fixture_v2.py"), "--oracle", str(oracle), "--seed", str(trial)]}}], scenario="launch")
                record["launch"] = launch
                record["scenarios"]["launch"] = {"result": launch, "oracle_met": None}
                if launch["status"] != "completed": raise RuntimeError("Fixture launch failed")
                actual = json.loads(oracle.read_text(encoding="utf-8"))
                record["scenarios"]["launch"]["oracle_met"] = actual["pid"] == launch["steps"][0]["output"].get("process_id")
                target = launch["steps"][0]["output"]["target_id"]
                observation = call("axis.observe", {"target_id": target})
                session = observation["session_id"]
                focus = run(session, [{"id": "focus", "op": "focus", "args": {"method": options.focus_method}}], scenario="focus")
                record["focus"] = focus
                record["scenarios"]["focus"] = {"result": focus, "oracle_met":
                    win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == actual["pid"]}
                if focus["status"] != "completed": raise RuntimeError("Fixture activation rejected by Windows")
                observation = call("axis.observe", {"session_id": session})
                record["initial_observation"] = observation
                call("axis.observe", {"session_id": session, "scope": "events"})
                text = f"AXIS {trial} : élève — 中文 😀"
                actions = run(session, [
                    {"id": "text", "op": "type_text", "args": {"at": {"selector": {"role": "Edit", "automation_id": "101"}}, "text": text, "replace": True},
                     "postcondition": {"kind": "value", "selector": {"role": "Edit", "automation_id": "101"}, "expected": text}},
                    {"id": "submit", "op": "click", "args": {"at": {"selector": {"name": "Submit", "role": "Button"}}},
                     "postcondition": {"kind": "exists", "selector": {"name": "Submitted"}}},
                ], scenario="unicode_batch")
                actual = json.loads(oracle.read_text(encoding="utf-8"))
                record["scenarios"]["unicode_batch"] = {"result": actions, "oracle_met": actual["text"] == text and actual["submitted"]}
                event_result = call("axis.observe", {"session_id": session, "scope": "events", "since": "0"}, scenario="native_events")
                record["scenarios"]["native_events"] = {"result": event_result, "oracle_met": any(e["kind"] in ("value", "name") for e in event_result.get("events", []))}
                if options.ocr:
                    ocr = call("axis.observe", {"session_id": session, "scope": "ocr"}, scenario="ocr")
                    record["scenarios"]["ocr"] = {"result": ocr, "oracle_met": "start sequence" in ocr.get("text", "").lower()}
                if actions["status"] != "completed" or not record["scenarios"]["unicode_batch"]["oracle_met"]:
                    raise RuntimeError("Unicode batch did not satisfy independent oracle")
                if options.paste:
                    pasted = text+" / pasted"
                    paste = run(session, [{"id": "paste", "op": "paste_text", "args": {"at": {"selector": {"automation_id": "101", "role": "Edit"}}, "text": pasted, "replace": True},
                        "postcondition": {"kind": "value", "selector": {"automation_id": "101", "role": "Edit"}, "expected": pasted}}], scenario="paste")
                    record["scenarios"]["paste"] = {"result": paste, "oracle_met": json.loads(oracle.read_text(encoding="utf-8"))["text"] == pasted}
                info = call("axis.targets", {})["targets"]
                bound = next(t for t in info if t["target_id"] == target)
                def point(x, y):
                    return {"point": {"space": "client", "geometry_id": bound["geometry_id"], "x": x, "y": y}}
                context = run(session, [
                    {"id": "right", "op": "click", "args": {"at": point(540, 210), "button": "right"},
                     "postcondition": {"kind": "exists", "selector": {"name": "Accept context", "role": "MenuItem"}}},
                    {"id": "accept", "op": "click", "args": {"at": {"selector": {"name": "Accept context", "role": "MenuItem"}}},
                     "postcondition": {"kind": "exists", "selector": {"name": "Context accepted"}}},
                ], scenario="right_click_menu")
                actual = json.loads(oracle.read_text(encoding="utf-8"))
                record["scenarios"]["right_click_menu"] = {"result": context, "oracle_met": actual["context"]}
                if context["status"] != "completed":
                    run(session, [{"id": "dismiss", "op": "keys", "args": {"keys": ["escape"]}, "verification": "dispatch_only"}])
                slider = run(session, [{"id": "slider", "op": "set_slider", "args": {"at": {"selector": {"automation_id": "106", "role": "Slider"}}, "value": 50},
                    "postcondition": {"kind": "value", "selector": {"automation_id": "106", "role": "Slider"}, "expected": 50}}], scenario="slider_value")
                time.sleep(.05)
                actual = json.loads(oracle.read_text(encoding="utf-8"))
                record["scenarios"]["slider_value"] = {"result": slider, "oracle_met": actual["slider"] == 50}
                drag = run(session, [{"id": "drag", "op": "drag", "args": {"start": point(60, 210), "end": point(440, 210), "duration": .4},
                    "postcondition": {"kind": "exists", "selector": {"name": "Drop accepted"}}}], scenario="drag")
                actual = json.loads(oracle.read_text(encoding="utf-8"))
                record["scenarios"]["drag"] = {"result": drag, "oracle_met": actual["dragged"]}
                if options.temporal:
                    # Probe geometry is a declared fixture calibration, not hidden game state.
                    dx = bound["client_origin"][0]-bound["bounds"][0]
                    dy = bound["client_origin"][1]-bound["bounds"][1]
                    probes = [{"name": n, "region": [x+dx, 300+dy, x+20+dx, 320+dy]} for n, x in (("red", 60), ("green", 180), ("blue", 300), ("yellow", 420))]
                    calibration = run(session, [{"id": "calibrate", "op": "calibrate", "args": {"profile": {"probes": probes, "min_pulse": .4, "interval": .02, "max_gap": .15}}}])
                    record["calibration"] = calibration
                    if calibration["status"] == "completed":
                        recipe = run(session, recipe="sequence-memory.play@1", recipe_args={"profile_id": calibration["steps"][0]["output"]["profile_id"],
                            "trigger": {"id": "start", "op": "click", "verification": "dispatch_only", "args": {"at": {"selector": {"name": "Start sequence"}}}},
                            "player_turn": {"kind": "exists", "selector": {"name": "Your turn"}}, "accepted": {"kind": "exists", "selector": {"name": "Round accepted"}}}, scenario="simon")
                        record["scenarios"]["simon"] = {"result": recipe, "oracle_met": json.loads(oracle.read_text(encoding="utf-8"))["round_accepted"], "model_images": 0}
            except Exception as exc:
                record["error"] = str(exc)
            finally:
                try:
                    if session:
                        record["close"] = run(session, [{"id": "close", "op": "close_window"}], scenario="close")
                        record["scenarios"]["close"] = {"result": record["close"], "oracle_met": None}
                        record["scenarios"]["close"]["oracle_met"] = json.loads(oracle.read_text(encoding="utf-8"))["closed"] is True
                except Exception as exc:
                    record["cleanup_error"] = type(exc).__name__
                    record.setdefault("error", "Fixture cleanup could not be verified")
                record["finished"] = time.time()
                record["missing_scenarios"] = sorted(required.keys()-record["scenarios"].keys())
                reports.append(record)
                persist()
            print(json.dumps({"trial": trial, "error": record.get("error"), "scenarios": {k: v["oracle_met"] for k, v in record["scenarios"].items()}}))
        all_trials_run = True
        summary = summarize(reports, required, options.trials, finished=True)
        passed = summary["meets_scenario_reliability_gate"] if options.trials >= 100 else summary["verified_trials"] == options.trials
        return 0 if passed else 1
    finally:
        try:
            broker.shutdown()
            broker.server_close()
            thread.join(1)
            runtime.close()
            finished = all_trials_run
        except BaseException as exc:
            finished = False
            readiness["shutdown_error"] = type(exc).__name__
            raise
        finally:
            persist()


if __name__ == "__main__":
    raise SystemExit(main())
