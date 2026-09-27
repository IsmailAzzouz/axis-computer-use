"""Read-only probe of the actual worker; not a desktop certification."""
import json
from cu_suite.v2.platforms import create_platform


def main():
    platform = create_platform()
    try:
        caps = platform.capabilities()
        targets = platform.targets()
        print(json.dumps({"capabilities": caps, "target_count": len(targets)}, indent=2))
    finally:
        platform.close()


if __name__ == "__main__":
    main()
