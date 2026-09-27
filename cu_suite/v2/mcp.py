"""MCP stdio adapter for an existing AXIS broker; no duplicated dispatch logic."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from .contracts import AxisError, VERSION, tool_definitions
from .framing import MAX_REQUEST, MAX_RESPONSE, FrameTooLarge, json_frame, parse_json, write_stream_frame
from .transport import AxisClient, _positive


class EnvironmentClient:
    """Defer broker credentials until a tool call, not MCP discovery.

    An offline/unconfigured host must not hide the tool catalogue. This never
    creates a runtime or grants desktop authority from model-supplied arguments.
    """
    def __init__(self, *, token_env="AXIS_TOKEN", port=8769):
        self.token_env, self.port = token_env, port

    def call(self, tool, arguments):
        import os
        from .contracts import SCHEMAS, validate
        if tool not in SCHEMAS:
            raise AxisError("UNKNOWN_TOOL", "Unknown tool; use axis.help")
        validate(arguments, SCHEMAS[tool])
        if tool == "axis.help":
            from .help import guide
            return guide(arguments)
        token = os.environ.get(self.token_env, "")
        if not 32 <= len(token) <= 4096:
            raise AxisError("HOST_NOT_CONFIGURED", "Start the authorized AXIS host and forward its token environment variable to this MCP process; then reconnect. No desktop input was sent.")
        return AxisClient(token=token, port=self.port).call(tool, arguments)


class MCPServer:
    def __init__(self, client, *, max_calls=8, control_calls=2):
        _positive(max_calls, "max_calls", integer=True)
        _positive(control_calls, "control_calls", integer=True)
        self.client = client
        self.max_calls, self.control_calls = max_calls, control_calls

    @staticmethod
    def _tool_result(value):
        content = []
        if "image_base64" in value:
            value = dict(value)
            content.append({"type": "image", "data": value.pop("image_base64"), "mimeType": "image/png"})
        content.insert(0, {"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))})
        return {"content": content, "structuredContent": value,
                "isError": value.get("status") in ("failed", "partial", "cancelled", "unknown") or bool(value.get("error"))}

    def handle_request(self, request):
        def error(code, message, request_id=None):
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if not isinstance(request, dict):
            return error(-32600, "Request must be an object")
        request_id = request.get("id")
        if (not isinstance(request.get("method"), str) or request.get("jsonrpc", "2.0") != "2.0"
                or isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None)))):
            return error(-32600, "Invalid request envelope")
        if "id" not in request:
            return None
        method, params = request.get("method"), request.get("params", {})
        if not isinstance(params, dict):
            return error(-32602, "Parameters must be an object", request_id)
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "axis", "version": VERSION}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_definitions()}
        elif method == "tools/call":
            if not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
                return error(-32602, "Tool name and arguments have invalid types", request_id)
            try:
                value = self.client.call(params["name"], params.get("arguments", {}))
            except AxisError as exc:
                value = {"version": VERSION, "status": "unknown" if exc.dispatch == "unknown" else "failed", "error": exc.result()}
            except (OSError, KeyError):
                value = {"version": VERSION, "status": "unknown", "error": {"code": "BROKER_UNAVAILABLE", "message": "Reconnect; use the same idempotency key for retries", "dispatch": "unknown"}}
            result = self._tool_result(value)
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def serve(self, reader=None, writer=None):
        reader = getattr(sys.stdin, "buffer", sys.stdin) if reader is None else reader
        writer = getattr(sys.stdout, "buffer", sys.stdout) if writer is None else writer
        lock = threading.Lock()
        failed_output = threading.Event()
        def emit(response):
            if response is None or failed_output.is_set():
                return
            try:
                frame = json_frame(response, MAX_RESPONSE)
            except (ValueError, TypeError, RecursionError):
                # Execution may already have happened; never claim not_sent here.
                frame = json_frame({"jsonrpc": "2.0", "id": response.get("id"), "error": {
                    "code": -32603, "message": "Response unavailable; reconcile with the original idempotency key",
                    "data": {"dispatch": "unknown"}}}, MAX_RESPONSE)
            with lock:
                if failed_output.is_set():
                    return
                try:
                    write_stream_frame(writer, frame)
                except (OSError, ValueError):
                    failed_output.set()

        def respond(request, slots):
            try:
                if failed_output.is_set():
                    return  # An unavailable output is not permission for more work.
                try:
                    response = self.handle_request(request)
                except Exception:
                    response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                                "error": {"code": -32603, "message": "Request outcome unavailable",
                                          "data": {"dispatch": "unknown"}}}
                emit(response)
            finally:
                slots.release()  # Includes response writing: no unbounded output queue.

        normal_slots = threading.BoundedSemaphore(self.max_calls)
        control_slots = threading.BoundedSemaphore(self.control_calls)
        with ThreadPoolExecutor(max_workers=self.max_calls) as normal, ThreadPoolExecutor(max_workers=self.control_calls) as control:
            while not failed_output.is_set():
                line = reader.readline(MAX_REQUEST+1)
                if not line:
                    break
                try:
                    request = parse_json(line)
                except FrameTooLarge:
                    emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Request exceeds byte limit; stream closed"}})
                    break  # Never interpret the rest of an oversized line as a request.
                except (ValueError, TypeError, RecursionError):
                    emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON request"}})
                    continue
                params = request.get("params", {}) if isinstance(request, dict) else {}
                is_control = isinstance(request, dict) and (request.get("method") == "ping" or
                             (request.get("method") == "tools/call" and isinstance(params, dict) and params.get("name") == "axis.job"))
                pool, slots = (control, control_slots) if is_control else (normal, normal_slots)
                if slots.acquire(blocking=False):
                    try:
                        pool.submit(respond, request, slots)
                    except BaseException:
                        slots.release()
                        raise
                else:
                    if isinstance(request, dict) and "id" not in request:
                        continue  # Notifications never get a response or perform input.
                    request_id = request.get("id") if isinstance(request, dict) else None
                    if type(request_id) not in (str, int, type(None)):
                        request_id = None
                    value = {"version": VERSION, "status": "failed", "error": {
                        "code": "RESOURCE_LIMIT", "message": "MCP execution limit reached; request was not dispatched", "dispatch": "not_sent"}}
                    if isinstance(request, dict) and request.get("method") == "tools/call":
                        emit({"jsonrpc": "2.0", "id": request_id, "result": self._tool_result(value)})
                    else:
                        emit({"jsonrpc": "2.0", "id": request_id,
                              "error": {"code": -32001, "message": "MCP admission limit reached", "data": {"dispatch": "not_sent"}}})
        if failed_output.is_set():
            raise OSError("MCP output unavailable; submitted job outcomes require reconciliation")
