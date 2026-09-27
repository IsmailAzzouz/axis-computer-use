"""Public AXIS CLI: the v2 contract, with no v1 action fallback."""
from .v2.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
