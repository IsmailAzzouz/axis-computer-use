"""Run the browser-independent JS save-flow regressions in the cumulative suite."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_form_save_regressions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for testbench JavaScript regressions")
    root = Path(__file__).resolve().parent
    result = subprocess.run([node, "--test", str(root/"form_save.test.mjs")],
                            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stdout+result.stderr
