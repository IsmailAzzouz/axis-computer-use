"""AXIS v2 host and model client CLI."""
import argparse
import os
import sys
from contextlib import contextmanager

from .contracts import AxisError
from .transport import AxisClient, BrokerServer
from .framing import MAX_REQUEST, MAX_RESPONSE, json_frame, parse_json, write_stream_frame


@contextmanager
def _host_runtime(policy, journal_path):
    """Own the native worker even when journal/runtime initialization fails."""
    from .platforms import create_platform
    from .runtime import Runtime
    platform = create_platform()
    runtime = None
    try:
        runtime = Runtime(platform, policy=policy, journal_path=journal_path)
        yield runtime
    finally:
        if runtime is None:
            platform.close()
        else:
            runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="axis")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--token-env", default="AXIS_TOKEN")
    commands = parser.add_subparsers(dest="command", required=True)
    safety = commands.add_parser("safety", help="Operator-only: inspect persistent native-input quarantine")
    safety.add_argument("--reconcile-owner")
    safety.add_argument("--confirm-inputs-released", action="store_true")
    safety.add_argument("--confirm-clipboard-reviewed", action="store_true")
    host = commands.add_parser("serve", help="Start the resident, host-authorized runtime")
    host.add_argument("--journal", required=True)
    host.add_argument("--allow-app", action="append", default=[])
    host.add_argument("--allow-target", action="append", default=[])
    host.add_argument("--read-all", action="store_true")
    host.add_argument("--allow-terminate", action="store_true")
    host.add_argument("--allow-all", action="store_true", help="Permit all apps, window mutation, and termination")
    host.add_argument("--max-connections", type=int, default=16)
    host.add_argument("--max-calls", type=int, default=8)
    host.add_argument("--control-calls", type=int, default=2, help="Reserved concurrent axis.job calls")
    host.add_argument("--request-timeout", type=float, default=5, help="Total incoming frame deadline in seconds")
    host.add_argument("--response-timeout", type=float, default=5, help="Total response write deadline in seconds")
    mcp = commands.add_parser("mcp", help="MCP stdio client of the resident broker")
    mcp.add_argument("--max-calls", type=int, default=8)
    mcp.add_argument("--control-calls", type=int, default=2, help="Reserved concurrent axis.job/ping calls")
    mcp.add_argument("--standalone", action="store_true", help="Run the broker runtime in-process via stdio")
    mcp.add_argument("--allow-all", action="store_true", help="Allow all apps, window mutations, and terminations (implies --standalone)")
    mcp.add_argument("--journal", default="axis-v2.sqlite3")
    mcp.add_argument("--read-all", action="store_true")
    mcp.add_argument("--allow-terminate", action="store_true")
    mcp.add_argument("--allow-app", action="append", default=[])
    mcp.add_argument("--allow-target", action="append", default=[])
    for name in ("help", "targets", "observe", "run", "job", "capture"):
        sub = commands.add_parser(name)
        sub.add_argument("--json", default="{}", help="Canonical argument object, or '-' to read JSON from stdin")
    args = parser.parse_args(argv)
    try:
        token = os.environ.get(args.token_env, "")
        if args.command == "serve":
            from .runtime import Policy
            if len(token) < 32:
                raise ValueError("Set a random host token of at least 32 characters in the selected environment variable")
            allow_all = getattr(args, "allow_all", False) or os.environ.get("AXIS_ALLOW_ALL", "").lower() in ("1", "true")
            policy = Policy(
                frozenset(args.allow_target),
                frozenset(args.allow_app),
                args.allow_terminate or allow_all,
                args.read_all or allow_all,
                allow_all=allow_all,
            )
            with _host_runtime(policy, args.journal) as runtime:
                try:
                    with BrokerServer(runtime, token=token, port=args.port, max_connections=args.max_connections,
                                      max_calls=args.max_calls, control_calls=args.control_calls,
                                      request_timeout=args.request_timeout, response_timeout=args.response_timeout) as server:
                        server.serve_forever(poll_interval=.1)
                except KeyboardInterrupt:
                    pass
            return 0
        if args.command == "mcp":
            env_allow_all = os.environ.get("AXIS_ALLOW_ALL", "").lower() in ("1", "true")
            standalone = getattr(args, "standalone", False) or getattr(args, "allow_all", False) or env_allow_all
            if standalone:
                from .runtime import Policy
                from .mcp import MCPServer
                allow_all = getattr(args, "allow_all", False) or env_allow_all
                policy = Policy(
                    frozenset(getattr(args, "allow_target", []) or []),
                    frozenset(getattr(args, "allow_app", []) or []),
                    getattr(args, "allow_terminate", False) or allow_all,
                    getattr(args, "read_all", False) or allow_all,
                    allow_all=allow_all,
                )
                journal = getattr(args, "journal", "axis-v2.sqlite3")
                with _host_runtime(policy, journal) as runtime:
                    MCPServer(runtime, max_calls=args.max_calls, control_calls=args.control_calls).serve()
                return 0
            from .mcp import MCPServer, EnvironmentClient
            MCPServer(EnvironmentClient(token_env=args.token_env, port=args.port),
                      max_calls=args.max_calls, control_calls=args.control_calls).serve()
            return 0
        if args.command == "safety":
            from .platforms import operator_safety
            result = operator_safety(owner=args.reconcile_owner, inputs_released=args.confirm_inputs_released,
                                     clipboard_reviewed=args.confirm_clipboard_reviewed)
        else:
            stdin = getattr(sys.stdin, "buffer", sys.stdin)
            arguments = parse_json(stdin.read(MAX_REQUEST+1) if args.json == "-" else args.json)
            if args.command == "help":
                from .help import guide
                result = guide(arguments)
            else:
                client = AxisClient(token=token, port=args.port)
                result = client.call("axis."+args.command, arguments)
        exit_code = 1 if result.get("error") else 0
    except (ValueError, OSError, RecursionError, AxisError) as exc:
        error = exc.result() if isinstance(exc, AxisError) else {"code": "CLIENT_ERROR", "message": type(exc).__name__}
        result = {"status": "unknown" if isinstance(exc, AxisError) and exc.dispatch == "unknown" else "failed", "error": error}
        exit_code = 1
    try:
        write_stream_frame(getattr(sys.stdout, "buffer", sys.stdout), json_frame(result, MAX_RESPONSE))
    except (ValueError, OSError, RecursionError):
        # Output loss does not mean a dispatched mutation failed. Do not try the
        # same broken stream again, or execute another action to obtain a reply.
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
