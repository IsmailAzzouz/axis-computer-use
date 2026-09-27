"""Authenticated loopback JSON transport. All clients share one resident runtime.

No pickle, filesystem tokens, remote binding, or model-provided host permissions.
"""
import hmac
import math
import socket
import socketserver
import threading
import time

from .contracts import AxisError, SCHEMAS, VERSION, validate
from .framing import (MAX_REQUEST, MAX_RESPONSE, FrameTooLarge, json_frame,
                      parse_json, read_socket_line, send_socket_frame)


def _token_valid(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 4096:
        raise ValueError("Host token must contain 32 to 4096 characters")


def _positive(value, name, *, integer=False):
    types = (int,) if integer else (int, float)
    maximum = 256 if integer else 3600
    if type(value) not in types or value <= 0 or value > maximum or not math.isfinite(value):
        raise ValueError(f"{name} must be {'an integer' if integer else 'finite'} in (0, {maximum}]")


def _failure(code, message, *, dispatch="not_sent"):
    return {"version": VERSION, "status": "unknown" if dispatch == "unknown" else "failed",
            "error": {"code": code, "message": message, "dispatch": dispatch}}


class AxisClient:
    def __init__(self, *, token, port=8769, timeout=15):
        _token_valid(token)
        _positive(timeout, "timeout")
        self._token, self._port, self._timeout = token, port, timeout

    def call(self, tool, arguments=None):
        if not isinstance(tool, str) or tool not in SCHEMAS:
            raise AxisError("UNKNOWN_TOOL", "Unknown tool; use axis.help")
        arguments = {} if arguments is None else arguments
        validate(arguments, SCHEMAS[tool])
        if tool == "axis.help":
            return self.help(**arguments)
        try:
            data = json_frame({"token": self._token, "tool": tool, "arguments": arguments}, MAX_REQUEST)
        except FrameTooLarge as exc:
            raise AxisError("REQUEST_TOO_LARGE", "Request exceeds transport limit") from exc
        except (ValueError, TypeError, RecursionError) as exc:
            raise AxisError("INVALID_REQUEST", "Request cannot be encoded as UTF-8 JSON") from exc
        sent_possible = False
        deadline = time.monotonic()+self._timeout
        try:
            with socket.create_connection(("127.0.0.1", self._port), self._timeout) as connection:
                sent_possible = True  # sendall can fail after sending a partial request.
                send_socket_frame(connection, data, deadline)
                result = read_socket_line(connection, MAX_RESPONSE, deadline)
            response = parse_json(result, MAX_RESPONSE)
            if not isinstance(response, dict) or response.get("version") != VERSION:
                raise ValueError()
            return response
        except (OSError, ValueError, RecursionError) as exc:
            raise AxisError("TRANSPORT_ERROR" if sent_possible else "BROKER_UNAVAILABLE",
                            "Broker response unavailable; reconcile with the same idempotency key",
                            dispatch="unknown" if sent_possible else "not_sent") from exc

    @staticmethod
    def help(**arguments):
        """Read help without constructing a credentialed client."""
        from .help import guide
        return guide(arguments)

    def targets(self, **arguments): return self.call("axis.targets", arguments)
    def observe(self, **arguments): return self.call("axis.observe", arguments)
    def run(self, **arguments): return self.call("axis.run", arguments)
    def job(self, **arguments): return self.call("axis.job", arguments)
    def capture(self, **arguments): return self.call("axis.capture", arguments)


class BrokerServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = False  # server_close drains calls before its host closes Runtime.
    request_queue_size = 16

    def __init__(self, runtime, *, token, port=8769, max_connections=16,
                 max_calls=8, control_calls=2, request_timeout=5, response_timeout=5):
        _token_valid(token)
        for name, value in (("max_connections", max_connections), ("max_calls", max_calls), ("control_calls", control_calls)):
            _positive(value, name, integer=True)
        _positive(request_timeout, "request_timeout")
        _positive(response_timeout, "response_timeout")
        self.runtime, self._token = runtime, token
        self.request_timeout, self.response_timeout = request_timeout, response_timeout
        self._max_connections = max_connections
        self._calls, self._controls = threading.BoundedSemaphore(max_calls), threading.BoundedSemaphore(control_calls)
        self._connections, self._connection_lock = set(), threading.Lock()
        self._closing = False
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def connection_count(self):
        with self._connection_lock:
            return len(self._connections)

    def process_request(self, request, client_address):
        with self._connection_lock:
            admitted = not self._closing and len(self._connections) < self._max_connections
            if admitted:
                self._connections.add(request)
                try:
                    # Register/start the handler before server_close can join it.
                    super().process_request(request, client_address)
                except BaseException:
                    self._connections.discard(request)
                    self.shutdown_request(request)
                    raise
        if not admitted:
            try:
                # No worker allocation and no authenticated request was dispatched.
                frame = json_frame(_failure("RESOURCE_LIMIT", "Broker connection limit reached; request was not dispatched"), 1024)
                send_socket_frame(request, frame, time.monotonic()+.05)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._connection_lock:
                self._connections.discard(request)

    def server_close(self):
        with self._connection_lock:
            self._closing = True
            connections = list(self._connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Joining handlers does not cancel or replay an already submitted job.
        super().server_close()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        dispatched = False
        request = {}
        try:
            raw = read_socket_line(self.request, MAX_REQUEST, time.monotonic()+self.server.request_timeout)
            request = parse_json(raw)
            if not isinstance(request, dict):
                raise ValueError()
            token = request.get("token", "")
            if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.server._token.encode()):
                result = _failure("UNAUTHORIZED", "Invalid broker credentials")
            else:
                if (set(request) - {"token", "tool", "arguments"} or not isinstance(request.get("tool"), str)
                        or not isinstance(request.get("arguments", {}), dict)):
                    raise ValueError()
                slots = self.server._controls if request["tool"] == "axis.job" else self.server._calls
                if not slots.acquire(blocking=False):
                    result = _failure("RESOURCE_LIMIT", "Broker execution limit reached; request was not dispatched")
                else:
                    try:
                        dispatched = True
                        result = self.server.runtime.call(request["tool"], request.get("arguments", {}))
                    finally:
                        slots.release()
        except AxisError as exc:
            result = _failure(exc.code, str(exc), dispatch=exc.dispatch)
        except FrameTooLarge:
            result = _failure("REQUEST_TOO_LARGE", "JSON frame exceeds byte limit")
        except (ValueError, KeyError, TypeError, OSError, RecursionError):
            result = _failure("INTERNAL_ERROR" if dispatched else "INVALID_REQUEST",
                              "Runtime response unavailable" if dispatched else "Malformed or incomplete JSON request",
                              dispatch="unknown" if dispatched else "not_sent")
        except Exception:
            result = _failure("INTERNAL_ERROR", "Runtime response unavailable", dispatch="unknown")
        try:
            frame = json_frame(result, MAX_RESPONSE)
        except (ValueError, TypeError, RecursionError):
            result = _failure("RESPONSE_TOO_LARGE", "Response cannot be delivered; recover run results with the original idempotency key",
                              dispatch="unknown" if dispatched else "not_sent")
            frame = json_frame(result, MAX_RESPONSE)
        try:
            send_socket_frame(self.request, frame, time.monotonic()+self.server.response_timeout)
        except OSError:
            pass  # Losing a client does not cancel or resubmit its job.
