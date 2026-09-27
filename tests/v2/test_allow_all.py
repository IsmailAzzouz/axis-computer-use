"""Portable tests for allow-all policy and standalone MCP mode."""
import io
import json

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.mcp import MCPServer
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform


def test_runtime_allow_all_policy(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(allow_all=True), journal_path=str(tmp_path / "journal.db"))
    try:
        targets_result = runtime.call("axis.targets", {})
        assert targets_result["apps"] == ["*"]
        assert len(targets_result["targets"]) == 1

        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        open_result = runtime.call("axis.run", {
            "session_id": session, "idempotency_key": "allow-all-open",
            "steps": [{"id": "open", "op": "open_app", "args": {"app": "custom_app_123"}}],
        })
        assert open_result["status"] == "completed"

        mutate = runtime.call("axis.run", {
            "session_id": session, "idempotency_key": "allow-all-type",
            "steps": [{"id": "type", "op": "type_text", "args": {"text": "hello"}, "verification": "dispatch_only"}],
        })
        assert mutate["status"] == "completed"
        assert not mutate["effects_verified"]

        terminate = runtime.call("axis.run", {
            "session_id": session, "idempotency_key": "allow-all-term",
            "steps": [{"id": "term", "op": "terminate_app", "verification": "dispatch_only"}],
        })
        assert terminate["status"] == "completed"

        # Authority belongs to the host policy and cannot be supplied in a model plan.
        before = len(pal.calls)
        forged = runtime.call("axis.run", {
            "session_id": session, "idempotency_key": "model-authority",
            "allow_all": True,
            "steps": [{"id": "x", "op": "type_text", "args": {"text": "forged"}, "verification": "dispatch_only"}],
        })
        assert forged["status"] == "failed"
        assert len(pal.calls) == before
    finally:
        runtime.close()


def test_invalid_plan_sends_nothing(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(allow_all=True), journal_path=str(tmp_path / "invalid.db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        result = runtime.call("axis.run", {
            "session_id": session, "idempotency_key": "invalid-plan",
            "steps": [
                {"id": "first", "op": "type_text", "args": {"text": "must not send"}, "verification": "dispatch_only"},
                {"id": "bad", "op": "not_an_operation"},
            ],
        })
        assert result["status"] == "failed"
        assert not pal.calls
    finally:
        runtime.close()


def test_unknown_effect_is_not_retried_with_same_key(tmp_path):
    pal = FakePlatform()
    pal.effect_error = AxisError("EFFECT_UNKNOWN", "Lost acknowledgement", dispatch="unknown")
    runtime = Runtime(pal, policy=Policy(allow_all=True), journal_path=str(tmp_path / "unknown.db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        request = {"session_id": session, "idempotency_key": "unknown-once",
                   "steps": [{"id": "type", "op": "type_text", "args": {"text": "uncertain"}, "verification": "dispatch_only"}]}
        first = runtime.call("axis.run", request)
        retry = runtime.call("axis.run", request)
        assert first["status"] == "unknown"
        assert retry["job_id"] == first["job_id"]
        assert retry["status"] == "unknown"
        assert len(pal.calls) == 1
    finally:
        runtime.close()


def test_standalone_mcp_without_broker_uses_fake_platform(tmp_path):
    """Exercise stdio dispatch in process; never starts an installed/native worker."""
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(allow_all=True), journal_path=str(tmp_path / "standalone.db"))
    try:
        mcp = MCPServer(runtime)
        requests = [{"jsonrpc": "2.0", "id": ident, "method": method,
                     **({"params": params} if params is not None else {})}
                   for ident, method, params in [
                       (1, "initialize", {}), (2, "tools/list", {}),
                       (3, "tools/call", {"name": "axis.help", "arguments": {}})]]
        writer = io.StringIO()
        mcp.serve(io.StringIO("".join(json.dumps(request)+"\n" for request in requests)), writer)
        replies = [json.loads(line) for line in writer.getvalue().splitlines()]
        by_id = {reply["id"]: reply for reply in replies}
        assert len(replies) == 3 and set(by_id) == {1, 2, 3}
        assert by_id[1]["result"]["serverInfo"]["name"] == "axis"
        assert "axis.run" in [tool["name"] for tool in by_id[2]["result"]["tools"]]
        assert "content" in by_id[3]["result"]
        assert not pal.calls
    finally:
        runtime.close()


def test_standalone_default_policy_refuses_windows(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, journal_path=str(tmp_path / "default.db"))
    try:
        response = MCPServer(runtime).handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "axis.targets", "arguments": {}},
        })
        assert response["result"]["structuredContent"]["targets"] == []
        assert pal.targets()  # the fake has a window, but host policy hides it
        assert not pal.calls
    finally:
        runtime.close()


def test_false_allow_all_environment_does_not_activate_policy(tmp_path, monkeypatch):
    import cu_suite.v2.cli as cli
    import cu_suite.v2.platforms as platforms

    monkeypatch.setenv("AXIS_ALLOW_ALL", "false")
    monkeypatch.setattr(platforms, "create_platform", FakePlatform)
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())
    observed = {}

    class MCPStub:
        def __init__(self, runtime, **kwargs):
            observed["policy"] = runtime.policy

        def serve(self):
            return None

    monkeypatch.setattr("cu_suite.v2.mcp.MCPServer", MCPStub)
    assert cli.main(["mcp", "--standalone", "--journal", str(tmp_path / "env.db")]) == 0
    assert observed["policy"] == Policy()


def test_public_allow_all_flag_routes_to_v2_cli(monkeypatch):
    from cu_suite.mcp import server as public_server

    observed = {}
    def stub(argv):
        observed["argv"] = argv
        return 0

    monkeypatch.setattr(public_server, "_main", stub)
    assert public_server.main(["--allow-all", "--journal", "portable.db"]) == 0
    assert observed["argv"] == ["--port", "8769", "--token-env", "AXIS_TOKEN", "mcp",
                                "--allow-all", "--journal", "portable.db"]
