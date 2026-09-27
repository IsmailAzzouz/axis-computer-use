"""Runnable examples must stay on the v2 broker path, including failure cases."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.framing import MAX_REQUEST
from cu_suite.v2.runtime import Policy, Runtime
from cu_suite.v2.transport import BrokerServer
from PIL import Image, ImageDraw
from .fake_platform import FakePlatform

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "examples-test-token-" * 3


def plan():
    return {"session_id": "session", "idempotency_key": "user-chosen-key",
            "steps": [{"id": "read", "op": "observe", "args": {"query": {"role": "Edit"}}}]}


def simon():
    return {"session_id": "session", "idempotency_key": "user-chosen-key", "recipe": "sequence-memory.play@1",
            "recipe_args": {"profile_id": "calibrated-profile",
                "trigger": {"id": "start", "op": "click", "args": {"at": {"selector": {"name": "Start"}}}, "verification": "dispatch_only"},
                "player_turn": {"kind": "value", "selector": {"name": "Status"}, "expected": "your turn"},
                "accepted": {"kind": "value", "selector": {"name": "Status"}, "expected": "accepted"}}}


@pytest.mark.parametrize("script,payload", [("play_sequence.py", plan()), ("run_simon.py", simon())])
def test_example_dry_run_has_no_host_or_native_access(script, payload):
    result = subprocess.run([sys.executable, str(ROOT/script), "--request", "-", "--dry-run"],
        input=json.dumps(payload).encode(), capture_output=True, cwd=ROOT,
        env={k: v for k, v in os.environ.items() if k != "AXIS_TOKEN"}, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "validated" and data["host_checked"] is False
    assert data["version"] == "2.0"


def test_example_replay_is_one_real_broker_request(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal.db"))
    calls = []
    class CountingRuntime:
        def call(self, tool, args):
            calls.append((tool, args))
            return runtime.call(tool, args)
    server = BrokerServer(CountingRuntime(), token=TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        request = {**plan(), "session_id": session, "steps": [
            {"id": "write", "op": "type_text", "args": {"text": "élève 中文 😀"},
             "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": "élève 中文 😀"}},
            plan()["steps"][0]]}
        response = subprocess.run([sys.executable, str(ROOT/"play_sequence.py"), "--request", "-", "--port", str(server.server_address[1])],
            input=json.dumps(request, ensure_ascii=False).encode(), capture_output=True,
            env={**os.environ, "AXIS_TOKEN": TOKEN}, timeout=10)
        assert response.returncode == 0, json.loads(response.stdout).get("error")
        result = json.loads(response.stdout)
        assert result["status"] == "completed" and result["effects_verified"]
        assert result["steps"][1]["output"]["elements"][0]["value"] == "élève 中文 😀"
        assert len(calls) == 1 and calls[0] == ("axis.run", request)
        assert len(pal.calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        runtime.close()


def invoke(monkeypatch, kind, request, *, dry=False):
    from cu_suite.v2.example_clients import main
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.BytesIO(request if isinstance(request, bytes) else json.dumps(request).encode()))
    monkeypatch.setattr(sys, "stdout", output)
    code = main(kind, ["--request", "-", *(["--dry-run"] if dry else [])])
    return code, json.loads(output.getvalue())


@pytest.mark.parametrize("kind,payload", [("simon", plan()), ("sequence", simon()),
    ("sequence", {**plan(), "steps": [{"id": "bad", "op": "click", "args": {"at": {"selector": {"name": "Input"}}}}]}),
    ("sequence", b"["*70+b"]"*70), ("sequence", b" "*(MAX_REQUEST+1)),
    ("sequence", b'{"session_id":"a","session_id":"b"}')],
    ids=["simon-needs-recipe", "sequence-needs-steps", "missing-postcondition", "nesting", "oversized", "duplicate-field"])
def test_bad_examples_fail_before_connection(monkeypatch, kind, payload):
    from cu_suite.v2.example_clients import EnvironmentClient
    monkeypatch.setattr(EnvironmentClient, "call", lambda *_: pytest.fail("Must reject before connection"))
    code, result = invoke(monkeypatch, kind, payload)
    assert code == 1 and result["status"] == "failed"
    assert result["error"]["dispatch"] == "not_sent"


@pytest.mark.parametrize("failure", [AxisError("TRANSPORT_ERROR", "lost acknowledgement", dispatch="unknown"), KeyboardInterrupt()])
def test_lost_ack_is_unknown_with_original_key_and_no_retry(monkeypatch, failure):
    from cu_suite.v2.example_clients import EnvironmentClient
    calls = []
    def call(self, tool, arguments):
        calls.append((tool, arguments))
        raise failure
    monkeypatch.setattr(EnvironmentClient, "call", call)
    code, result = invoke(monkeypatch, "simon", simon())
    assert code == 1 and result["status"] == "unknown"
    assert result["idempotency_key"] == "user-chosen-key"
    assert len(calls) == 1 and calls[0][1] == simon()


@pytest.mark.parametrize("script", ["run_simon.py", "play_sequence.py"])
def test_importing_examples_has_no_side_effects(script):
    # No import of the previous native facade and no subprocess-per-click loop.
    result = subprocess.run([sys.executable, "-c",
        "import importlib.util,sys; s=importlib.util.spec_from_file_location('example',sys.argv[1]); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "assert 'cu_suite.agent_facade' not in sys.modules", str(ROOT/script)], capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 0, result.stderr
    assert not result.stdout


def test_output_loss_does_not_repeat_submission(monkeypatch):
    from cu_suite.v2.example_clients import EnvironmentClient, main
    class ClosedOutput:
        def write(self, _): raise BrokenPipeError()
        def flush(self): raise BrokenPipeError()
    calls = []
    monkeypatch.setattr(EnvironmentClient, "call", lambda _, tool, args: calls.append(args) or {"version": "2.0", "status": "accepted", "job_id": "job"})
    monkeypatch.setattr(sys, "stdin", io.BytesIO(json.dumps(plan()).encode()))
    monkeypatch.setattr(sys, "stdout", ClosedOutput())
    assert main("sequence", ["--request", "-"]) == 1
    assert calls == [plan()]


def test_long_recovery_key_does_not_overflow_error_page(monkeypatch):
    from cu_suite.v2.example_clients import EnvironmentClient
    def call(*_): raise AxisError("TRANSPORT_ERROR", "lost acknowledgement", dispatch="unknown")
    monkeypatch.setattr(EnvironmentClient, "call", call)
    payload = {**plan(), "idempotency_key": "文"*4096}
    code, result = invoke(monkeypatch, "sequence", payload)
    assert code == 1 and result["status"] == "unknown"
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 12*1024
    assert result["idempotency_key_in_original_request"]


def test_request_file_is_validated_without_host(monkeypatch, tmp_path):
    from cu_suite.v2.example_clients import EnvironmentClient, main
    path = tmp_path / "plan.json"
    path.write_bytes(json.dumps(plan()).encode())
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(EnvironmentClient, "call", lambda *_: pytest.fail("Dry run cannot connect"))
    assert main("sequence", ["--request", str(path), "--dry-run"]) == 0
    assert json.loads(output.getvalue())["statically_counted_steps"] == 1


@pytest.mark.parametrize("scenario", ["fast-round", "slow-round", "injected-trigger-sampling-gap"])
def test_simon_roundtrip_records_repeated_events_and_reports_evidence_scopes(tmp_path, scenario):
    missing_samples = scenario == "injected-trigger-sampling-gap"
    fast = scenario == "fast-round"
    class SimonPlatform(FakePlatform):
        def __init__(self):
            super().__init__()
            self.started, self.replayed = None, 0
            self.capture_times = []
        def dispatch(self, target, op, args, timeout):
            result = super().dispatch(target, op, args, timeout)
            if op == "click":
                if self.started is None:
                    self.started = time.monotonic()
                    if missing_samples:
                        time.sleep(.12)  # deterministic missed sample while the trigger is in flight
                else:
                    self.replayed += 1
                    if self.replayed == 2:
                        self.elements[0]["value"] = "accepted"
            return result
        def capture(self, target):
            self.capture_times.append(time.monotonic())
            frame = Image.new("RGB", (200, 200), "black")
            if self.started is not None:
                elapsed = time.monotonic()-self.started
                on = (.10 <= elapsed < .35 or .50 <= elapsed < .75) if fast else (.10 <= elapsed < 1.10 or 1.50 <= elapsed < 2.50)
                if on:
                    ImageDraw.Draw(frame).rectangle((10, 10, 29, 29), fill="red")
                if elapsed >= (.9 if fast else 2.7) and not self.replayed:
                    self.elements[0]["value"] = "your turn"
            return frame
    pal = SimonPlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal.db"))
    server = BrokerServer(runtime, token=TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        calibration = runtime.call("axis.run", {"session_id": session, "idempotency_key": "calibrate",
            "steps": [{"id": "calibrate", "op": "calibrate", "args": {"profile": {
                "probes": [{"name": "red", "region": [10, 10, 30, 30]}], "interval": .01,
                "max_gap": .09 if missing_samples or fast else .4, "min_pulse": .2 if fast else 1.0}}}]})
        assert calibration["status"] == "completed", calibration
        payload = simon()
        payload["session_id"] = session
        recipe = payload["recipe_args"]
        recipe["profile_id"] = calibration["steps"][0]["output"]["profile_id"]
        recipe["trigger"]["args"]["at"]["selector"] = {"name": "Input"}
        for key in ("player_turn", "accepted"):
            recipe[key]["selector"] = {"name": "Input"}
        response = subprocess.run([sys.executable, str(ROOT/"run_simon.py"), "--request", "-", "--port", str(server.server_address[1])],
            input=json.dumps(payload).encode(), capture_output=True, env={**os.environ, "AXIS_TOKEN": TOKEN}, timeout=10)
        result = json.loads(response.stdout)
        if missing_samples:
            assert response.returncode == 1
            assert result["error"]["code"] == "SAMPLING_GAP"
            assert pal.replayed == 0 and len(pal.calls) == 1
            return
        assert response.returncode == 0, {"error": result.get("error"),
            "capture_gaps": [b-a for a, b in zip(pal.capture_times, pal.capture_times[1:])], "start": pal.started}
        assert result["status"] == "completed", result
        watched = next(step for step in result["steps"] if step["id"] == "demonstration")
        replay = next(step for step in result["steps"] if step["id"] == "playback")
        assert watched["output"]["sequence"] == ["red", "red"]
        assert watched["output"]["sample_clock"] == "performance_counter"
        assert replay["verification"] == "met" and pal.replayed == 2
        # Aggregate demonstration/round proof covers only its declared members;
        # individual clicks still have no fabricated per-click observations.
        assert result["effects_verified"] is True
        assert watched["verification_scope"] == {"kind": "triggered_demonstration", "first_step": 0, "step_count": 1, "trigger_id": recipe["trigger"]["id"]}
        assert replay["verification_scope"] == {"kind": "sequence_acceptance", "first_step": 2, "step_count": 2}
        assert all(step["dispatch"] == "sent" and step["verification"] == "unobservable"
                   for step in result["steps"] if step["op"] == "click")
        assert b"image_base64" not in response.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        runtime.close()
