"""Run one explicit sequence through AXIS v2; no hardcoded target or coordinates.

See docs/AXIS_V2_EXAMPLES.md. The model/host supplies a contextualized plan.
"""
from cu_suite.v2.example_clients import main as _main


def main(argv=None):
    return _main("sequence", argv)


if __name__ == "__main__":
    raise SystemExit(main())
