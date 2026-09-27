import json
import threading
import socket
import pytest

from cu_suite.v2.mcp import MCPServer
from cu_suite.v2.contracts import AxisError, MAX_BYTES
from cu_suite.v2.runtime import Runtime, Policy, Job
from cu_suite.v2.transport import BrokerServer, AxisClient
from .fake_platform import FakePlatform


@pytest.mark.parametrize("envelope", [[], None, 1, "text", {"token": "wrong", "tool": "axis.targets"}])
def test_broker_malformed_envelopes_are_structured_and_do_not_dispatch(envelope):
    class NeverCalled:
        def call(self, *args): raise AssertionError("Unexpected dispatch")
    server = BrokerServer(NeverCalled(), token="test-token-"*4, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address) as connection:
            connection.sendall(json.dumps(envelope).encode()+b"\n")
            with connection.makefile("rb") as stream:
                response = json.loads(stream.readline())
        assert response["error"]["code"] in ("INVALID_REQUEST", "UNAUTHORIZED")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


@pytest.mark.parametrize("envelope", [[], None, 1, {"id": 1, "method": "tools/call", "params": []},
    {"id": 1, "method": "tools/call", "params": {"name": []}},
    {"id": 1, "method": "tools/call", "params": {"name": "axis.targets", "arguments": []}}])
def test_mcp_invalid_envelopes_do_not_dispatch(envelope):
    class NeverCalled:
        def call(self, *args): raise AssertionError("Unexpected dispatch")
    response = MCPServer(NeverCalled()).handle_request(envelope)
    assert response["error"]["code"] in (-32600, -32602)


@pytest.mark.parametrize("arguments", [[], False, "", 0])
def test_sdk_does_not_coerce_invalid_empty_arguments(arguments):
    with pytest.raises(AxisError):
        AxisClient(token="test-token-"*4).call("axis.targets", arguments)


@pytest.mark.parametrize("reply", [b"", b"[]\n", b"not-json\n", b"{}"])
def test_lost_or_invalid_acknowledgement_is_unknown_and_never_retried(reply):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    received = []
    def respond():
        with listener.accept()[0] as connection:
            with connection.makefile("rb") as stream:
                received.append(stream.readline())
            connection.sendall(reply)
    thread = threading.Thread(target=respond)
    thread.start()
    try:
        client = AxisClient(token="test-token-"*4, port=listener.getsockname()[1])
        with pytest.raises(AxisError) as failure:
            client.targets()
        assert failure.value.dispatch == "unknown"
        assert failure.value.code == "TRANSPORT_ERROR"
        thread.join(1)
        assert len(received) == 1
    finally:
        listener.close()


def test_mcp_keeps_unknown_transport_outcome():
    class Disconnected:
        def call(self, *args): raise AxisError("TRANSPORT_ERROR", "Lost reply", dispatch="unknown")
    result = MCPServer(Disconnected()).handle_request({"id": 1, "method": "tools/call", "params": {"name": "axis.run"}})
    assert result["result"]["structuredContent"]["status"] == "unknown"
    assert result["result"]["isError"]


def test_real_socket_mcp_sdk_share_session_and_contract(tmp_path):
    runtime = Runtime(FakePlatform(), policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal.db"))
    token = "test-token-"*4
    server = BrokerServer(runtime, token=token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = AxisClient(token=token, port=server.server_address[1])
        mcp = MCPServer(client)
        session = client.observe(target_id="test")["session_id"]
        result = mcp.handle_request({"id": 1, "method": "tools/call", "params": {"name": "axis.observe", "arguments": {"session_id": session}}})
        assert result["result"]["structuredContent"]["session_id"] == session
        assert not result["result"]["isError"]
        denied = AxisClient(token="wrong-token-"*4, port=server.server_address[1]).targets()
        assert denied["error"]["code"] == "UNAUTHORIZED"
        image = mcp.handle_request({"id": 2, "method": "tools/call", "params": {"name": "axis.capture", "arguments": {"session_id": session}}})
        assert image["result"]["content"][1]["type"] == "image"
        unknown = mcp.handle_request({"id": 3, "method": "tools/call", "params": {"name": "axis.click", "arguments": {}}})
        assert unknown["result"]["isError"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)
        runtime.close()


def test_mcp_paged_result_survives_restart_and_expired_sessions(tmp_path):
    path = str(tmp_path/"journal.db")
    original = Runtime(FakePlatform(), journal_path=path)
    large = "中文😀"*10000
    job = Job("durable-large", status="completed", steps=[{"id": "step", "op": "watch", "dispatch": "sent",
              "verification": "met", "output": {"sequence": [large, "last"]}}])
    stored = {"status": job.status, "steps": job.steps, "error": None}
    original._db.execute("INSERT INTO requests VALUES (?,?,?,?)", ("lost-key", "digest", job.job_id, json.dumps(stored)))
    original._db.commit()
    original.close()
    pal = FakePlatform()
    runtime = Runtime(pal, journal_path=path)
    token = "test-token-"*4
    server = BrokerServer(runtime, token=token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        mcp = MCPServer(AxisClient(token=token, port=server.server_address[1]))
        def call(cursor=None, action="result"):
            args = {"idempotency_key": "lost-key", "action": action}
            if cursor: args["cursor"] = cursor
            response = mcp.handle_request({"id": 1, "method": "tools/call", "params": {"name": "axis.job", "arguments": args}})
            assert len(response["result"]["content"][0]["text"].encode()) <= MAX_BYTES
            return response["result"]["structuredContent"]
        first = call()
        assert first["job_id"] == job.job_id and first["effects_verified"]
        page = call(first["steps"][0]["output"]["sequence"]["cursor"])
        cursor = page["output"][0]["item_data"]["cursor"]
        fragments = []
        while cursor:
            page = call(cursor)
            fragments.append(page["data"])
            assert page["next_cursor"] != cursor
            cursor = page["next_cursor"]
        assert json.loads("".join(fragments)) == large
        assert call(action="status")["status"] == "completed"
        assert pal.calls == [] and runtime._sessions == {}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)
        runtime.close()
