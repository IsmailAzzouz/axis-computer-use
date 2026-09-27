"""Public MCP entrypoint. Offline help plus five resident-runtime tools."""
import sys

from cu_suite.v2.cli import main as _main
from cu_suite.v2.mcp import MCPServer

__all__ = ["MCPServer", "main"]


def main(argv=None):
    # Global broker options precede the subcommand; admission options belong to
    # MCP itself. This dedicated entrypoint does not accept other subcommands.
    values = list(sys.argv[1:] if argv is None else argv)
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--token-env", default="AXIS_TOKEN")
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--allow-all", action="store_true")
    parser.add_argument("--journal", default="axis-v2.sqlite3")
    parser.add_argument("--read-all", action="store_true")
    parser.add_argument("--allow-terminate", action="store_true")
    parser.add_argument("--allow-app", action="append", default=[])
    parser.add_argument("--allow-target", action="append", default=[])
    options, remaining = parser.parse_known_args(values)
    cmd = ["--port", str(options.port), "--token-env", options.token_env, "mcp"]
    if options.standalone:
        cmd.append("--standalone")
    if options.allow_all:
        cmd.append("--allow-all")
    if options.journal:
        cmd.extend(["--journal", options.journal])
    if options.read_all:
        cmd.append("--read-all")
    if options.allow_terminate:
        cmd.append("--allow-terminate")
    for app in options.allow_app:
        cmd.extend(["--allow-app", app])
    for target in options.allow_target:
        cmd.extend(["--allow-target", target])
    cmd.extend(remaining)
    return _main(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
