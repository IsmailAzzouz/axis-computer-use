"""Shared acceptance host: all actions still traverse MCP/TCP/runner/worker."""
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
from contextlib import ExitStack
from cu_suite.v2.platforms import create_platform
from cu_suite.v2.runtime import Runtime, Policy
from cu_suite.v2.transport import BrokerServer, AxisClient
from cu_suite.v2.mcp import MCPServer


class NativeHarness:
    def __init__(self, output, apps):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        platform = create_platform()
        self.runtime = None
        with ExitStack() as resources:
            # Ownership transfers to Runtime only after its construction succeeds.
            resources.callback(lambda: self.runtime.close() if self.runtime is not None else platform.close())
            if not platform.capabilities().get("interactive"):
                raise RuntimeError("Interactive desktop authorization required")
            self.runtime = Runtime(platform, policy=Policy(apps=frozenset(apps)),
                                   journal_path=str(self.output/("journal-"+uuid.uuid4().hex+".sqlite3")))
            token = secrets.token_hex(32)
            self.broker = BrokerServer(self.runtime, token=token, port=0)
            resources.callback(self.broker.server_close)
            self.thread = threading.Thread(target=self.broker.serve_forever, daemon=True)
            self.thread.start()
            # Never shutdown a server whose serve_forever thread never started.
            resources.callback(self.thread.join, 1)
            resources.callback(self.broker.shutdown)
            self.mcp = MCPServer(AxisClient(token=token, port=self.broker.server_address[1]))
            self.trace = []
            self._resources = resources.pop_all()

    def call(self, name, arguments=None):
        request = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments or {}}}
        started = time.monotonic()
        self._record({"event": "request", "request": request})
        response = self.mcp.handle_request(request)
        entry = {"request": request, "response": response, "seconds": time.monotonic()-started}
        self.trace.append(entry)
        self._record({"event": "response", **entry})
        return response["result"]["structuredContent"]

    def _record(self, event):
        # Preserve the original key before dispatch, including a lost response.
        # Requests contain no host token; never replay from this trace automatically.
        with (self.output/"trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=True)+"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def run(self, session, steps, **kwargs):
        result = self.call("axis.run", {"session_id": session, "steps": steps, "idempotency_key": uuid.uuid4().hex, **kwargs})
        return result if kwargs.get("async") else self.finish(result)

    def finish(self, result):
        deadline = time.monotonic()+65
        while result.get("status") in ("accepted", "running"):
            if time.monotonic() > deadline:
                raise RuntimeError("Job still running; no new action will be submitted")
            time.sleep(.02)
            result = self.call("axis.job", {"job_id": result["job_id"], "action": "result"})
        return result

    def close(self):
        try:
            self._resources.close()
        finally:
            (self.output/"trace.json").write_text(json.dumps(self.trace, ensure_ascii=True, indent=2), encoding="utf-8")
