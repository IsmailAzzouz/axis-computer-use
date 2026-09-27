"""Run one calibrated Simon recipe through the resident AXIS v2 broker.

See docs/AXIS_V2_EXAMPLES.md for profile/session setup and request format.
"""
from cu_suite.v2.example_clients import main as _main


def main(argv=None):
    return _main("simon", argv)


if __name__ == "__main__":
    raise SystemExit(main())
