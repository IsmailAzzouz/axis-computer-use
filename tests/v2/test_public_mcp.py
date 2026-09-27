"""Public entrypoints must reach v2, never the retired in-process facade."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from cu_suite.v2.contracts import tool_definitions
from cu_suite.v2.runtime import Policy, Runtime
from cu_suite.v2.transport import AxisClient, BrokerServer
from .fake_platform import FakePlatform


ROOT = Path(__file__).resolve().parents[2]
TOKEN = "public-mcp-test-token-" * 3


@pytest.fixture
def broker(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path / "journal.db"))
    server = BrokerServer(runtime, token=TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield AxisClient(token=TOKEN, port=server.server_address[1]), pal
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        runtime.close()


@pytest.mark.parametrize("module", ["cu_suite.mcp.server", "cu_suite.mcp", "cu_suite.cli", "cu_suite", "cu_suite.v2.cli"])
def test_public_stdio_real_process_reaches_same_broker(module, broker):
    client, pal = broker
    check_stdio(module, client, pal)


def check_stdio(module, client, pal, python=sys.executable, cwd=ROOT):
    dispatched_before = len(pal.calls)
    session = client.observe(target_id="test")["session_id"]
    text = "élève 中文 😀"
    arguments = {"session_id": session, "idempotency_key": "public-" + module, "steps": [
        {"id": "write", "op": "type_text", "args": {"text": text},
         "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": text}},
        {"id": "read", "op": "observe", "args": {"query": {"role": "Edit"}}}]}
    requests = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "qualification", "version": "1"}}},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {"name": "axis.run", "arguments": arguments}},
        {"id": 4, "method": "tools/call", "params": {"name": "axis.click", "arguments": {"coord": [1, 1]}}},
    ]
    command = [str(python), "-m", module, "--port", str(client._port)]
    if module not in ("cu_suite.mcp.server", "cu_suite.mcp"):
        command += ["mcp"]
    result = subprocess.run(command, input="".join(json.dumps({"jsonrpc": "2.0", **r}, ensure_ascii=False) + "\n" for r in requests).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                            env={**{k: v for k, v in os.environ.items() if k != "PYTHONPATH"}, "AXIS_TOKEN": TOKEN}, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    replies = {r["id"]: r for r in map(json.loads, result.stdout.splitlines())}
    assert replies[1]["result"]["serverInfo"]["version"] == "2.0"
    assert replies[2]["result"]["tools"] == tool_definitions()
    outcome = replies[3]["result"]["structuredContent"]
    assert outcome["status"] == "completed" and outcome["effects_verified"]
    assert len(outcome["steps"]) == 2
    assert outcome["steps"][1]["output"]["elements"][0]["value"] == text
    assert replies[4]["result"]["structuredContent"]["error"]["code"] == "UNKNOWN_TOOL"
    assert len(pal.calls) == dispatched_before + 1
    assert pal.calls[-1][0] == "type_text" and pal.elements[0]["value"] == text
    assert client.job(job_id=outcome["job_id"])["status"] == "completed"


def test_public_imports_are_same_v2_implementation():
    from cu_suite import AxisClient as root_client
    from cu_suite.sdk import AxisClient as sdk_client
    from cu_suite.mcp import MCPServer
    from cu_suite.mcp.server import MCPServer as server
    from cu_suite.v2.mcp import MCPServer as v2
    assert root_client is sdk_client is AxisClient
    assert MCPServer is server is v2


def test_public_imports_do_not_load_legacy_native_facade():
    result = subprocess.run([sys.executable, "-c", "import cu_suite.cli, cu_suite.sdk, cu_suite.mcp.server, sys; assert 'cu_suite.agent_facade' not in sys.modules"],
                            cwd=ROOT, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_stdio_without_host_credentials_exposes_tools_but_never_claims_ready():
    requests = [{"id": 1, "method": "tools/list"},
                {"id": 2, "method": "tools/call", "params": {"name": "axis.targets", "arguments": {}}}]
    env = {k: v for k, v in os.environ.items() if k != "AXIS_TOKEN"}
    result = subprocess.run([sys.executable, "-m", "cu_suite.mcp.server"],
                            input="".join(json.dumps({"jsonrpc": "2.0", **r}) + "\n" for r in requests).encode(),
                            cwd=ROOT, env=env, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    replies = {r["id"]: r for r in map(json.loads, result.stdout.splitlines())}
    assert replies[1]["result"]["tools"] == tool_definitions()
    failure = replies[2]["result"]
    assert failure["isError"]
    assert failure["structuredContent"]["version"] == "2.0"
    assert failure["structuredContent"]["error"]["code"] == "HOST_NOT_CONFIGURED"
    assert failure["structuredContent"]["error"]["dispatch"] == "not_sent"


@pytest.mark.parametrize("command", [["click", "--coord", "1", "1"], ["--disable-security", "snapshot", "out.png"]])
def test_removed_cli_commands_are_rejected(command):
    result = subprocess.run([sys.executable, "-m", "cu_suite.cli", *command], cwd=ROOT, capture_output=True, timeout=10)
    assert result.returncode == 2
    assert b"Success" not in result.stdout


def test_model_skill_example_executes_as_a_verified_v2_sequence(broker):
    client, pal = broker
    guide = (ROOT / ".agents/skills/computer-use/SKILL.md").read_text(encoding="utf-8")
    # Exercise the model-facing example, not the wording of its instructions.
    args = json.loads(guide.split("```json\n", 1)[1].split("```", 1)[0])
    args["session_id"] = client.observe(target_id="test")["session_id"]
    result = client.run(**args)
    assert result["status"] == "completed" and result["effects_verified"]
    assert len(result["steps"]) == 3
    assert pal.elements[0]["value"] == "Hello"
