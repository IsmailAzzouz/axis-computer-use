"""Real sockets/stdio admission and fault tests; no desktop input."""
from contextlib import contextmanager
import io
import json
import queue
import socket
import threading
import time

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.framing import FrameTooLarge, MAX_REQUEST, json_frame, parse_json
from cu_suite.v2.mcp import MCPServer
from cu_suite.v2.transport import AxisClient, BrokerServer

TOKEN = "bounded-test-token-"*3
RUN = {"session_id": "s", "idempotency_key": "first", "steps": [{"id": "a", "op": "focus"}]}


def eventually(predicate, timeout=2):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Condition did not become true within bounded wait")
        time.sleep(.005)


@contextmanager
def broker(runtime, **options):
    server = BrokerServer(runtime, token=TOKEN, port=0, **options)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
    thread.start()
    try:
        yield server, AxisClient(token=TOKEN, port=server.server_address[1], timeout=2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()
        assert server.connection_count == 0


class BlockingRuntime:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "axis.run":
            self.entered.set()
            assert self.release.wait(3), "Test did not release blocking call"
        elif tool == "axis.job":
            self.release.set()
        return {"version": "2.0", "job_id": "job", "status": "completed"}


def test_broker_has_bounded_admission_and_reserved_job_capacity():
    runtime = BlockingRuntime()
    with broker(runtime, max_calls=1, control_calls=1) as (server, client):
        results = []
        thread = threading.Thread(target=lambda: results.append(client.run(**RUN)))
        thread.start()
        try:
            assert runtime.entered.wait(1)
            rejected = client.run(**{**RUN, "idempotency_key": "must-not-run"})
            assert rejected["error"]["code"] == "RESOURCE_LIMIT"
            assert rejected["error"]["dispatch"] == "not_sent"
            assert len(runtime.calls) == 1
            assert client.job(job_id="job", action="cancel")["status"] == "completed"
            thread.join(1)
            assert not thread.is_alive() and results[0]["status"] == "completed"
            assert [name for name, _ in runtime.calls] == ["axis.run", "axis.job"]
        finally:
            runtime.release.set()
            thread.join(1)


def test_idle_connections_are_capped_and_reclaimed_without_dispatch():
    runtime = BlockingRuntime()
    with broker(runtime, max_connections=2, request_timeout=.25) as (server, client):
        connections = [socket.create_connection(server.server_address) for _ in range(2)]
        try:
            eventually(lambda: server.connection_count == 2)
            with socket.create_connection(server.server_address, timeout=1) as rejected:
                with rejected.makefile("rb") as reader:
                    result = json.loads(reader.readline())
            assert result["error"]["code"] == "RESOURCE_LIMIT"
            assert result["error"]["dispatch"] == "not_sent"
            assert server.connection_count <= 2 and runtime.calls == []
            eventually(lambda: server.connection_count == 0)
            assert client.targets()["version"] == "2.0"
            assert len(runtime.calls) == 1
        finally:
            for connection in connections:
                connection.close()


def drip(connection, stop):
    try:
        while not stop.wait(.02):
            connection.sendall(b" ")
    except OSError:
        pass


def test_trickling_request_cannot_extend_the_broker_frame_deadline():
    runtime = BlockingRuntime()
    with broker(runtime, request_timeout=.12) as (server, _):
        with socket.create_connection(server.server_address, timeout=1) as connection:
            stop = threading.Event()
            thread = threading.Thread(target=drip, args=(connection, stop))
            started = time.monotonic()
            thread.start()
            try:
                with connection.makefile("rb") as reader:
                    response = json.loads(reader.readline())
                assert response["error"]["dispatch"] == "not_sent"
                assert time.monotonic()-started < .8
                assert runtime.calls == []
            finally:
                stop.set()
                thread.join(1)


def test_trickling_acknowledgement_is_bounded_unknown_and_not_retried():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    calls, stop = [], threading.Event()
    def respond():
        with listener.accept()[0] as connection:
            with connection.makefile("rb") as reader:
                calls.append(reader.readline())
            drip(connection, stop)
    thread = threading.Thread(target=respond)
    thread.start()
    try:
        started = time.monotonic()
        client = AxisClient(token=TOKEN, port=listener.getsockname()[1], timeout=.12)
        with pytest.raises(AxisError) as error:
            client.targets()
        assert error.value.dispatch == "unknown" and error.value.code == "TRANSPORT_ERROR"
        assert time.monotonic()-started < .8 and len(calls) == 1
    finally:
        stop.set()
        thread.join(1)
        listener.close()


def test_oversized_post_dispatch_response_does_not_claim_no_effect(monkeypatch):
    from cu_suite.v2 import transport
    monkeypatch.setattr(transport, "MAX_RESPONSE", 512)
    class LargeRuntime:
        calls = 0
        def call(self, *args):
            self.calls += 1
            return {"version": "2.0", "status": "completed", "output": "x"*1000}
    runtime = LargeRuntime()
    with broker(runtime) as (_, client):
        result = client.run(**RUN)
        assert result["status"] == "unknown"
        assert result["error"]["code"] == "RESPONSE_TOO_LARGE"
        assert result["error"]["dispatch"] == "unknown" and runtime.calls == 1


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_ambiguous_and_nonfinite_values(raw):
    with pytest.raises(ValueError):
        parse_json(raw)


def test_json_frames_measure_utf8_bytes_including_newline():
    value = {"text": "😀中文"}
    encoded = json_frame(value, 100)
    assert parse_json(encoded) == value
    assert json_frame(value, len(encoded)) == encoded
    with pytest.raises(FrameTooLarge): json_frame(value, len(encoded)-1)
    with pytest.raises(FrameTooLarge): parse_json(encoded.decode(), len(encoded)-1)


class InputPipe:
    def __init__(self): self.lines = queue.Queue()
    def readline(self, size):
        assert 0 < size <= MAX_REQUEST+1
        return self.lines.get(timeout=3)
    def send(self, request): self.lines.put(json.dumps(request)+"\n")
    def close(self): self.lines.put("")


class OutputPipe(io.StringIO):
    def __init__(self):
        super().__init__()
        self.responses = queue.Queue()
    def write(self, text):
        self.responses.put(json.loads(text))
        return super().write(text)


def call_request(request_id, name, arguments=None):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


def test_stdio_has_no_waiting_action_queue_and_reserves_job_calls():
    client = BlockingRuntime()
    reader, writer = InputPipe(), OutputPipe()
    server = MCPServer(client, max_calls=1, control_calls=1)
    thread = threading.Thread(target=server.serve, args=(reader, writer))
    thread.start()
    try:
        reader.send(call_request(1, "axis.run", RUN))
        assert client.entered.wait(1)
        reader.send(call_request(2, "axis.run", {**RUN, "idempotency_key": "not-admitted"}))
        rejected = writer.responses.get(timeout=1)
        assert rejected["id"] == 2
        assert rejected["result"]["structuredContent"]["error"]["code"] == "RESOURCE_LIMIT"
        assert len(client.calls) == 1
        reader.send(call_request(3, "axis.job", {"job_id": "job", "action": "cancel"}))
        answers = [writer.responses.get(timeout=1), writer.responses.get(timeout=1)]
        assert {answer["id"] for answer in answers} == {1, 3}
        assert len(client.calls) == 2
    finally:
        client.release.set()
        reader.close()
        thread.join(2)
        assert not thread.is_alive()


@pytest.mark.parametrize("text", ["x"*(MAX_REQUEST*2), "😀"*(MAX_REQUEST//2)], ids=["ascii", "utf8"])
def test_stdio_rejects_oversized_lines_without_reading_or_executing_their_suffix(text):
    client = BlockingRuntime()
    reader, writer = io.StringIO(text+"\n"+json.dumps(call_request(2, "axis.run", RUN))+"\n"), io.StringIO()
    MCPServer(client).serve(reader, writer)
    assert reader.tell() <= MAX_REQUEST+1
    assert client.calls == []
    responses = writer.getvalue().splitlines()
    assert len(responses) == 1 and json.loads(responses[0])["error"]["code"] == -32700


def test_stdio_deep_json_does_not_kill_subsequent_control_requests():
    reader = io.StringIO("["*2000+"0"+"]"*2000+'\n{"id":1,"method":"ping"}\n')
    writer = io.StringIO()
    MCPServer(BlockingRuntime()).serve(reader, writer)
    replies = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1] == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_cli_limits_stdin_before_parsing_or_connecting(monkeypatch, capsys):
    from cu_suite.v2 import cli
    class EndlessInput:
        read_sizes = []
        def read(self, size):
            assert 0 < size <= MAX_REQUEST+1
            self.read_sizes.append(size)
            return "x"*size
    reader = EndlessInput()
    monkeypatch.setenv("AXIS_TOKEN", TOKEN)
    monkeypatch.setattr(cli.sys, "stdin", reader)
    monkeypatch.setattr(AxisClient, "call", lambda *args: pytest.fail("Oversized stdin must not connect"))
    assert cli.main(["targets", "--json", "-"]) == 1
    assert reader.read_sizes == [MAX_REQUEST+1]
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), 10**1000], ids=["zero", "negative", "bool", "nan", "inf", "huge"])
def test_host_rejects_invalid_limits_before_accepting_connections(value):
    with pytest.raises(ValueError): BrokerServer(None, token=TOKEN, port=0, max_connections=value)
    with pytest.raises(ValueError): BrokerServer(None, token=TOKEN, port=0, request_timeout=value)
    with pytest.raises(ValueError): AxisClient(token=TOKEN, timeout=value)
    with pytest.raises(ValueError): MCPServer(None, max_calls=value)


def test_sdk_unicode_encoding_failure_is_not_sent_or_retried():
    with pytest.raises(AxisError) as error:
        AxisClient(token=TOKEN).observe(query={"name": "\ud800"})
    assert error.value.code == "INVALID_REQUEST" and error.value.dispatch == "not_sent"


def test_reserved_lane_cancels_real_runtime_through_stdio_and_tcp(tmp_path):
    from cu_suite.v2.runtime import Runtime, Policy
    from .fake_platform import FakePlatform
    class CancelPlatform(FakePlatform):
        def __init__(self):
            super().__init__()
            self.entered, self.cancelled = threading.Event(), threading.Event()
        def dispatch(self, *args):
            self.calls.append("dispatch")
            self.entered.set()
            assert self.cancelled.wait(3)
            raise AxisError("CANCELLED", "Test action interrupted", dispatch="sent")
        def cancel(self): self.cancelled.set()
    pal = CancelPlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"journal"))
    try:
        with broker(runtime, max_calls=1, control_calls=1) as (_, client):
            session = client.observe(target_id="test")["session_id"]
            reader, writer = InputPipe(), OutputPipe()
            mcp = MCPServer(client, max_calls=1, control_calls=1)
            thread = threading.Thread(target=mcp.serve, args=(reader, writer))
            thread.start()
            try:
                reader.send(call_request(1, "axis.run", {**RUN, "session_id": session}))
                assert pal.entered.wait(1)
                reader.send(call_request(2, "axis.run", {**RUN, "session_id": session, "idempotency_key": "rejected"}))
                assert writer.responses.get(timeout=1)["result"]["structuredContent"]["error"]["code"] == "RESOURCE_LIMIT"
                reader.send(call_request(3, "axis.job", {"idempotency_key": "first", "action": "cancel"}))
                responses = [writer.responses.get(timeout=1), writer.responses.get(timeout=1)]
                run = next(r for r in responses if r["id"] == 1)["result"]["structuredContent"]
                assert run["status"] == "cancelled" and not run["effects_verified"]
                assert pal.calls == ["dispatch"] and pal.releases == 1
                assert client.job(idempotency_key="first", action="result")["status"] == "cancelled"
                assert runtime._db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1
            finally:
                pal.cancelled.set()
                reader.close()
                thread.join(2)
                assert not thread.is_alive()
    finally:
        runtime.close()


def test_broker_close_drains_inflight_call_without_cancelling_or_replaying():
    runtime = BlockingRuntime()
    with broker(runtime, max_calls=1) as (server, client):
        outcomes = []
        def run():
            try:
                outcomes.append(client.run(**RUN))
            except AxisError as exc:
                outcomes.append(exc)
        caller = threading.Thread(target=run)
        caller.start()
        assert runtime.entered.wait(1)
        server.shutdown()
        closed = threading.Event()
        def close():
            server.server_close()
            closed.set()
        closer = threading.Thread(target=close)
        closer.start()
        try:
            assert not closed.wait(.05), "Do not close Runtime while its transport call is active"
            assert not runtime.release.is_set()
        finally:
            runtime.release.set()
            closer.join(2)
            caller.join(2)
        assert closed.is_set() and not caller.is_alive()
        assert len(runtime.calls) == 1 and len(outcomes) == 1
        assert isinstance(outcomes[0], AxisError) and outcomes[0].dispatch == "unknown"


def test_depth_limit_does_not_count_brackets_or_escaped_quotes_inside_strings():
    value = {"text": '"[\\\\{"'*1000}
    assert parse_json(json_frame(value, MAX_REQUEST)) == value


def test_stdio_closed_output_prevents_later_client_calls():
    class ClosedWriter:
        def write(self, _): raise BrokenPipeError()
        def flush(self): pytest.fail("Closed output must not be flushed")
    client = BlockingRuntime()
    # Parse failure is synchronous, before any pool admission.
    reader = io.StringIO("invalid\n"+json.dumps(call_request(1, "axis.targets"))+"\n")
    with pytest.raises(OSError, match="reconciliation"):
        MCPServer(client).serve(reader, ClosedWriter())
    assert client.calls == []


def test_mcp_default_stdio_uses_utf8_independently_of_console_encoding(monkeypatch):
    from cu_suite.v2 import mcp
    phrase = "élève 中文 😀"
    request = call_request(1, "axis.observe", {"query": {"name": phrase}})
    raw_input = io.BytesIO(json_frame(request, MAX_REQUEST))
    raw_output = io.BytesIO()
    stdin = io.TextIOWrapper(raw_input, encoding="ascii")
    stdout = io.TextIOWrapper(raw_output, encoding="ascii")
    class Echo:
        def call(self, tool, arguments):
            return {"version": "2.0", "name": arguments["query"]["name"]}
    monkeypatch.setattr(mcp.sys, "stdin", stdin)
    monkeypatch.setattr(mcp.sys, "stdout", stdout)
    MCPServer(Echo()).serve()
    response = json.loads(raw_output.getvalue())
    assert response["result"]["structuredContent"]["name"] == phrase


def test_cli_default_stdio_uses_utf8_and_does_not_retry_broken_output(monkeypatch):
    from cu_suite.v2 import cli
    phrase = "élève 中文 😀"
    stdin = io.TextIOWrapper(io.BytesIO(json_frame({"query": {"name": phrase}}, MAX_REQUEST)), encoding="ascii")
    raw_output = io.BytesIO()
    stdout = io.TextIOWrapper(raw_output, encoding="ascii")
    monkeypatch.setenv("AXIS_TOKEN", TOKEN)
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    calls = []
    def call(self, tool, arguments):
        calls.append(arguments)
        return {"version": "2.0", "name": arguments["query"]["name"]}
    monkeypatch.setattr(AxisClient, "call", call)
    assert cli.main(["observe", "--json", "-"]) == 0
    assert json.loads(raw_output.getvalue())["name"] == phrase
    class BrokenOutput:
        writes = 0
        def write(self, _):
            self.writes += 1
            raise BrokenPipeError()
    broken = BrokenOutput()
    monkeypatch.setattr(cli.sys, "stdout", broken)
    assert cli.main(["observe", "--json", '{"query":{"name":"test"}}']) == 1
    assert broken.writes == 1 and len(calls) == 2
