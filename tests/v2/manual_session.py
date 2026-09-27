"""Interactive JSON-lines model exercise through the actual MCP/TCP/native path.

Only host-allowlisted apps can be launched. No existing window has mutation
authority. A 'shutdown' host command stops this harness, never kills applications.
"""
import argparse
import base64
import json
from pathlib import Path
import secrets
import sys
import threading
import time

from cu_suite.v2.platforms import create_platform
from cu_suite.v2.runtime import Runtime, Policy
from cu_suite.v2.transport import BrokerServer, AxisClient
from cu_suite.v2.mcp import MCPServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-app", action="append", default=[])
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    platform = create_platform()
    if not platform.capabilities().get("interactive"):
        platform.close()
        raise RuntimeError("Interactive desktop required")
    runtime = Runtime(platform, policy=Policy(apps=frozenset(args.allow_app)), journal_path=str(directory/"journal.sqlite3"))
    token = secrets.token_hex(32)
    broker = BrokerServer(runtime, token=token, port=0)
    server = threading.Thread(target=broker.serve_forever, daemon=True)
    server.start()
    mcp = MCPServer(AxisClient(token=token, port=broker.server_address[1]))
    print(json.dumps({"ready": True, "apps": args.allow_app}), flush=True)
    try:
        with (directory/"model-trace.jsonl").open("a", encoding="utf-8") as trace:
            for line in sys.stdin:
                try:
                    request = json.loads(line)
                    if request.get("command") == "shutdown": break
                    if "request_file" in request:
                        # Windows console input can truncate long JSON lines. A
                        # local test request file still makes ONE unchanged MCP call.
                        path = (directory/request["request_file"]).resolve()
                        if path.parent != directory or path.stat().st_size > 256*1024:
                            raise ValueError("Request file outside output directory or oversized")
                        request = json.loads(path.read_text(encoding="utf-8"))
                    started = time.monotonic()
                    response = mcp.handle_request({"id": request.get("id", 1), "method": "tools/call", "params": request})
                    trace.write(json.dumps({"request": request, "response": response, "elapsed": time.monotonic()-started}, ensure_ascii=True)+"\n")
                    trace.flush()
                    images = []
                    for item in response["result"]["content"]:
                        if item["type"] == "image":
                            path = directory/f"frame-{time.time_ns()}.png"
                            path.write_bytes(base64.b64decode(item["data"]))
                            images.append(str(path))
                    print(json.dumps({"data": response["result"]["structuredContent"],
                                      "isError": response["result"]["isError"], "images": images}, ensure_ascii=True), flush=True)
                except (ValueError, TypeError) as exc:
                    print(json.dumps({"error": type(exc).__name__}), flush=True)
    finally:
        broker.shutdown()
        broker.server_close()
        server.join(1)
        runtime.close()


if __name__ == "__main__":
    main()
