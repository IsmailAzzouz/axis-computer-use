"""Bounded JSON framing, shared by local transports; no execution policy here."""
import json
import io
import time

MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 32 * 1024 * 1024  # Explicit PNG, not the 12 KiB text-page budget.
MAX_JSON_DEPTH = 64


class FrameTooLarge(ValueError):
    pass


def parse_json(raw, limit=MAX_REQUEST):
    if len(raw) > limit or (isinstance(raw, str) and len(raw.encode("utf-8")) > limit):
        raise FrameTooLarge("JSON frame exceeds byte limit")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    depth, quoted, escaped = 0, False, False
    for character in raw:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds limit")
        elif character in "]}":
            depth -= 1
    def constant(_):
        raise ValueError("Non-finite JSON number")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(raw, parse_constant=constant, object_pairs_hook=pairs)


def json_frame(value, limit):
    """Bound encoded output while iterating; include the newline in its budget."""
    data = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        if len(data)+len(chunk)+1 > limit:
            raise FrameTooLarge("JSON frame exceeds byte limit")
        encoded = chunk.encode("utf-8")
        if len(data)+len(encoded)+1 > limit:
            raise FrameTooLarge("JSON frame exceeds byte limit")
        data.extend(encoded)
    data.extend(b"\n")
    return bytes(data)


def write_stream_frame(writer, data):
    """Binary stdio is UTF-8; injected text streams remain usable by SDK/tests."""
    writer.write(data if isinstance(writer, (io.BufferedIOBase, io.RawIOBase)) else data.decode("utf-8"))
    writer.flush()


def read_socket_line(connection, limit, deadline):
    """One frame with a total deadline, not a timeout reset by each byte."""
    data = bytearray()
    while True:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError("JSON frame deadline expired")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, limit+1-len(data)))
        if not chunk:
            raise ValueError("Incomplete JSON frame")
        newline = chunk.find(b"\n")
        data.extend(chunk if newline < 0 else chunk[:newline+1])
        if len(data) > limit:
            raise FrameTooLarge("JSON frame exceeds byte limit")
        if newline >= 0:
            return bytes(data)


def send_socket_frame(connection, data, deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError("JSON frame deadline expired")
    connection.settimeout(remaining)
    connection.sendall(data)
