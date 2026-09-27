"""Small operator examples; plans execute only in the existing resident runner."""
import argparse
import sys

from .contracts import AxisError, MAX_BYTES, MAX_STEPS, SCHEMAS, VERSION, compile_steps, validate
from .framing import MAX_REQUEST, json_frame, parse_json, write_stream_frame
from .mcp import EnvironmentClient


def _port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("Broker port must be in 1..65535")
    return number


def main(kind, argv=None):
    if kind not in ("simon", "sequence"):
        raise ValueError("Unknown example kind")
    parser = argparse.ArgumentParser(description=(
        "Submit one calibrated Simon round to the authorized AXIS v2 host."
        if kind == "simon" else "Submit one explicit action sequence to the authorized AXIS v2 host."))
    parser.add_argument("--request", required=True, help="UTF-8 JSON axis.run arguments file, or '-' for stdin")
    parser.add_argument("--port", type=_port, default=8769)
    parser.add_argument("--token-env", default="AXIS_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="Validate syntax/budgets only; no host connection or native input")
    options = parser.parse_args(argv)
    submitted, arguments = False, None
    try:
        if options.request == "-":
            raw = getattr(sys.stdin, "buffer", sys.stdin).read(MAX_REQUEST+1)
        else:
            with open(options.request, "rb") as stream:
                raw = stream.read(MAX_REQUEST+1)
        arguments = parse_json(raw)
        validate(arguments, SCHEMAS["axis.run"])
        if kind == "simon":
            if arguments.get("recipe") != "sequence-memory.play@1" or "steps" in arguments or not arguments.get("recipe_args"):
                raise AxisError("INVALID_PLAN", "Simon requires sequence-memory.play@1, recipe_args and an existing calibrated profile; no steps")
            from .perception import sequence_recipe
            steps = sequence_recipe(arguments["recipe_args"])
        else:
            if not arguments.get("steps") or "recipe" in arguments or "recipe_args" in arguments:
                raise AxisError("INVALID_PLAN", "Sequence example requires explicit steps, not a recipe")
            steps = arguments["steps"]
        step_count = compile_steps(steps)
        if options.dry_run:
            result = {"version": VERSION, "status": "validated", "host_checked": False,
                      "statically_counted_steps": step_count, "executed_step_limit": MAX_STEPS}
        else:
            submitted = True
            result = EnvironmentClient(token_env=options.token_env, port=options.port).call("axis.run", arguments)
        exit_code = 1 if result.get("error") or result.get("status") in ("failed", "partial", "cancelled", "unknown") else 0
    except (AxisError, ValueError, OSError, RecursionError, KeyboardInterrupt) as exc:
        if isinstance(exc, AxisError):
            error = exc.result()
        else:
            error = {"code": "CLIENT_INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "CLIENT_ERROR",
                     "message": type(exc).__name__, "dispatch": "unknown" if submitted else "not_sent"}
        error = {**error, "code": error["code"][:128], "message": error["message"][:1024]}
        result = {"version": VERSION, "status": "unknown" if error["dispatch"] == "unknown" else "failed", "error": error}
        if submitted and isinstance(arguments, dict):
            key = arguments["idempotency_key"]
            if len(key) <= 128 and key.isascii():
                result["idempotency_key"] = key
            else:
                result["idempotency_key_in_original_request"] = True
        exit_code = 1
    try:
        write_stream_frame(getattr(sys.stdout, "buffer", sys.stdout), json_frame(result, MAX_BYTES+1))
    except (OSError, ValueError, RecursionError):
        # A broken output stream is not permission to repeat the submitted plan.
        return 1
    return exit_code
