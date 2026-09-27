"""Agent guide examples, offline transports and compact strict schemas."""
import copy
import json
import os
import subprocess
import sys

import pytest

from cu_suite.v2.contracts import ACTION_ARGS, AxisError, MAX_BYTES, SCHEMAS, compile_steps, tool_definitions, validate
from cu_suite.v2.help import action_example, guide
from cu_suite.v2.mcp import EnvironmentClient, MCPServer
from cu_suite.v2.runtime import Policy, Runtime
from cu_suite.v2.transport import AxisClient
from .fake_platform import FakePlatform


@pytest.mark.parametrize("arguments", [{}, {"topic": "run"}, {"topic": "actions"}, {"topic": "errors"}] + [{"action": a} for a in ACTION_ARGS])
def test_guide_same_offline_and_runtime_without_desktop_reads(tmp_path, monkeypatch, arguments):
    monkeypatch.delenv("AXIS_TOKEN", raising=False)
    class NoDesktop:
        def __getattr__(self, name):
            raise AssertionError("Help must not access native platform: " + name)
    runtime = Runtime(NoDesktop(), journal_path=str(tmp_path / "help.db"))
    expected = guide(arguments)
    try:
        assert runtime.call("axis.help", arguments) == expected
        assert EnvironmentClient().call("axis.help", arguments) == expected
        assert AxisClient.help(**arguments) == expected
        reply = MCPServer(EnvironmentClient()).handle_request({"id": 1, "method": "tools/call", "params": {"name": "axis.help", "arguments": arguments}})["result"]
        assert not reply["isError"] and reply["structuredContent"] == expected
        assert len(json.dumps(expected, separators=(",", ":")).encode()) <= MAX_BYTES
        if not arguments or arguments.get("topic") == "run":
            assert len(json.dumps(expected)) < 2400
    finally:
        # This runtime has no native worker to close.
        runtime._db.close()


@pytest.mark.parametrize("arguments", [{"topic": "bogus"}, {"action": "eval"}, {"token": "secret"}, [], None])
def test_invalid_help_rejected_without_credentials(monkeypatch, arguments):
    monkeypatch.delenv("AXIS_TOKEN", raising=False)
    with pytest.raises(AxisError, match="request"):
        EnvironmentClient().call("axis.help", arguments)


def test_help_example_executes_and_reconciles_without_duplicate_input(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path / "example.db"))
    try:
        example = guide()["example"]
        args = example["arguments"]
        args["session_id"] = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        validate(args, SCHEMAS[example["tool"]])
        assert compile_steps(args["steps"]) == 3
        result = runtime.call(example["tool"], args)
        assert result["status"] == "completed" and result["effects_verified"]
        assert pal.elements[0]["value"] == "Hello"
        assert result["steps"][2]["output"]["elements"][0]["value"] == "Hello"
        count = len(pal.calls)
        recovered = runtime.call("axis.job", {"idempotency_key": args["idempotency_key"], "action": "result"})
        assert recovered["job_id"] == result["job_id"] and len(pal.calls) == count
    finally:
        runtime.close()


def test_cli_and_stdio_help_work_without_token_or_host():
    env = {k: v for k, v in os.environ.items() if k != "AXIS_TOKEN"}
    cli = subprocess.run([sys.executable, "-m", "cu_suite", "help"], env=env, capture_output=True, timeout=10)
    assert cli.returncode == 0 and json.loads(cli.stdout) == guide()
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "axis.help"}}
    mcp = subprocess.run([sys.executable, "-m", "cu_suite.mcp.server"], input=(json.dumps(request)+"\n").encode(), env=env, capture_output=True, timeout=10)
    assert mcp.returncode == 0
    assert json.loads(mcp.stdout)["result"]["structuredContent"] == guide()


@pytest.mark.parametrize("step,valid", [
    ({"id": "f", "op": "focus"}, True),
    ({"id": "r", "op": "repeat", "args": {"count": 2, "steps": [{"id": "f", "op": "focus"}]}}, True),
    ({"id": "c", "op": "click", "args": {"at": {"selector": {"name": "Input"}}}, "verification": "dispatch_only"}, True),
    ({"id": "c", "op": "click", "args": {}}, False),
    ({"id": "f", "op": "focus", "args": {"x": 1}}, False),
    ({"id": "f", "op": "focus", "unknown": 1}, False),
    ({"op": "focus"}, False),
    ({"id": "f", "op": "eval"}, False),
    ({"id": "r", "op": "repeat", "args": {"count": 2, "steps": [{"op": "focus"}]}}, False),
])
def test_compact_schema_preserves_strict_contract(step, valid):
    request = {"session_id": "s", "idempotency_key": "k", "steps": [step]}
    public = next(t["inputSchema"] for t in tool_definitions() if t["name"] == "axis.run")
    for schema in (SCHEMAS["axis.run"], public):
        if valid:
            validate(request, schema)
        else:
            with pytest.raises(AxisError):
                validate(request, schema)
    assert len(json.dumps(public)) < 14000


def test_error_names_missing_parameter():
    bad = guide()["example"]["arguments"]
    bad["steps"] = [{"id": "c", "op": "click", "args": {}}]
    with pytest.raises(AxisError, match=r"args: missing required field.*at"):
        validate(bad, SCHEMAS["axis.run"])


def test_help_results_are_not_shared_mutable_state():
    original = copy.deepcopy(ACTION_ARGS["click"])
    guide({"action": "click"})["args_schema"]["required"].clear()
    assert ACTION_ARGS["click"] == original


@pytest.mark.parametrize("action", ["focus", "click", "type_text", "paste_text", "keys", "scroll", "open_app", "close_window"])
def test_common_action_help_has_complete_compact_valid_run(action):
    result = guide({"action": action})
    example = result["example"]
    assert example["tool"] == "axis.run"
    public = next(t["inputSchema"] for t in tool_definitions() if t["name"] == "axis.run")
    for schema in (SCHEMAS["axis.run"], public):
        validate(example["arguments"], schema)
    assert compile_steps(example["arguments"]["steps"]) > 0
    assert len(json.dumps(result)) < 3000
    if action in ("keys", "scroll"):
        step = next(s for s in example["arguments"]["steps"] if s["op"] == action)
        assert step["verification"] == "dispatch_only"
        assert "NOT verified" in result["guide"]
    if action == "open_app":
        assert all(s["target_from"] == "open" for s in example["arguments"]["steps"][1:])


def test_action_examples_are_fresh_and_do_not_invent_advanced_plans():
    example = action_example("type_text")
    example["arguments"]["steps"][1]["args"]["at"]["selector"]["name"] = "Changed"
    assert action_example("type_text")["arguments"]["steps"][1]["args"]["at"]["selector"]["name"] == "Input"
    assert action_example("watch") is None
