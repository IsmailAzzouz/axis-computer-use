"""Run isolated testbench HTTP and browser checks (not an AXIS capability claim)."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-only', action='store_true', help='Run HTTP tests without Chromium')
    args = parser.parse_args()
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT), '-p', 'test_server.py', '-v'])
    if result.returncode:
        return result.returncode
    if args.http_only:
        return 0
    node = shutil.which('node')
    if not node:
        print('Browser verification requires Node.js 22+ and a Chromium browser.', file=sys.stderr)
        return 2
    return subprocess.run([node, str(ROOT / 'browser_verification.mjs'), '--python', sys.executable]).returncode


if __name__ == '__main__':
    raise SystemExit(main())
