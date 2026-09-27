"""Persistent quarantine across owners/restarts; never touches native input."""
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.safety_latch import SafetyLatch
from .test_windows_action_budget import native


def test_crashed_process_leaves_quarantine(tmp_path):
    path = tmp_path / "safety.db"
    process = subprocess.run([sys.executable, "-c",
        "import os; from cu_suite.v2.safety_latch import SafetyLatch; "
        "s=SafetyLatch("+repr(str(path))+",'desktop'); s.arm(os.getpid()); os._exit(19)"], capture_output=True, timeout=5)
    assert process.returncode == 19
    restarted = SafetyLatch(path, "desktop")
    status = restarted.status()
    assert status["state"] == "quarantined"
    with pytest.raises(AxisError) as error: restarted.arm(42)
    assert error.value.code == "INPUT_UNRECONCILED"
    assert restarted.status() == status


def test_only_one_concurrent_owner_can_arm(tmp_path):
    path = tmp_path / "safety.db"
    a, b = SafetyLatch(path, "desktop"), SafetyLatch(path, "desktop")
    def claim(latch):
        try: return latch.arm(1)
        except AxisError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, (a, b)))
    assert claims.count("INPUT_UNRECONCILED") == 1


def test_reconciliation_is_owner_specific_and_audited(tmp_path):
    path = tmp_path / "safety.db"
    latch = SafetyLatch(path, "desktop")
    first = latch.arm(1)
    with pytest.raises(AxisError): latch.clear("wrong", reason="operator_acknowledged")
    assert latch.status()["owner"] == first
    latch.clear(first, reason="operator_acknowledged")
    second = latch.arm(2)
    with pytest.raises(AxisError): latch.clear(first, reason="operator_acknowledged")
    assert latch.status()["owner"] == second
    latch.clear(second, reason="normal_cleanup")
    assert SafetyLatch(path, "desktop").status()["state"] == "clear"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT reason FROM reconciliations ORDER BY rowid").fetchall() == [("operator_acknowledged",), ("normal_cleanup",)]


def test_abandoned_mutex_preserves_existing_quarantine(tmp_path):
    latch = SafetyLatch(tmp_path / "safety.db", "desktop")
    owner = latch.arm(1, abandoned=True)
    assert latch.arm(2, abandoned=True) == owner
    with pytest.raises(AxisError): latch.arm(3)


def test_corrupt_safety_store_fails_closed(tmp_path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"not a database")
    with pytest.raises(AxisError) as error: SafetyLatch(path, "desktop")
    assert error.value.code == "SAFETY_STORE_UNAVAILABLE"


def prepare(native, tmp_path, abandoned=False):
    adapter, state, _, env = native
    adapter._owns_lease = False
    adapter._mutex = object()
    adapter._safety = SafetyLatch(tmp_path / "safety.db", "desktop")
    adapter._safety_owner = None
    env["os"] = SimpleNamespace(getpid=lambda: 7)
    env["win32con"].WAIT_ABANDONED, env["win32con"].WAIT_OBJECT_0 = 128, 0
    env["win32event"] = SimpleNamespace(WaitForSingleObject=lambda *_: 128 if abandoned else 0,
        ReleaseMutex=lambda _: setattr(state, "closed", state.closed+1))
    return adapter, state


def test_native_lease_arms_before_input_and_clears_after_cleanup(native, tmp_path):
    adapter, _ = prepare(native, tmp_path)
    adapter.acquire_lease()
    assert adapter._owns_lease and adapter._safety.status()["state"] == "quarantined"
    adapter._held = [("key", 17)]
    with pytest.raises(AxisError): adapter.release_lease()
    assert adapter._safety.status()["state"] == "quarantined"
    adapter.release()
    adapter.release_lease()
    assert not adapter._owns_lease and adapter._safety.status()["state"] == "clear"


def test_native_restart_cannot_clear_prior_owner(native, tmp_path):
    adapter, state = prepare(native, tmp_path)
    owner = adapter._safety.arm(999)
    with pytest.raises(AxisError) as error: adapter.acquire_lease()
    assert error.value.code == "INPUT_UNRECONCILED"
    assert not adapter._owns_lease and state.closed == 1
    assert adapter._safety.status()["owner"] == owner


def test_abandoned_native_mutex_persists_block(native, tmp_path):
    adapter, state = prepare(native, tmp_path, abandoned=True)
    with pytest.raises(AxisError): adapter.acquire_lease()
    assert adapter._safety.status()["state"] == "quarantined" and state.closed == 1


def test_cli_safety_is_not_a_model_tool(monkeypatch, capsys):
    from cu_suite.v2 import cli, platforms
    from cu_suite.v2.contracts import SCHEMAS
    calls = []
    def control(**kwargs):
        calls.append(kwargs)
        return {"state": "clear"}
    monkeypatch.setattr(platforms, "operator_safety", control)
    assert cli.main(["safety"]) == 0
    assert json.loads(capsys.readouterr().out) == {"state": "clear"}
    assert calls == [{"owner": None, "inputs_released": False, "clipboard_reviewed": False}]
    assert "axis.safety" not in SCHEMAS and len(SCHEMAS) == 6


@pytest.fixture
def operator(tmp_path, monkeypatch):
    module = pytest.importorskip("cu_suite.v2.platforms.windows_safety")
    latch = SafetyLatch(tmp_path / "operator.db", "desktop")
    owner = latch.arm(999)
    state = SimpleNamespace(busy=False, held=False, acquired=0, released=0, closed=0)
    def wait(*_):
        state.acquired += 1
        return 258 if state.busy else module.win32con.WAIT_OBJECT_0
    mutex = SimpleNamespace(Close=lambda: setattr(state, "closed", state.closed+1))
    monkeypatch.setattr(module, "desktop_latch", lambda: latch)
    monkeypatch.setattr(module, "win32event", SimpleNamespace(CreateMutex=lambda *_: mutex,
        WaitForSingleObject=wait, ReleaseMutex=lambda _: setattr(state, "released", state.released+1)))
    monkeypatch.setattr(module, "win32api", SimpleNamespace(GetAsyncKeyState=lambda _: 0x8000 if state.held else 0))
    return module, latch, owner, state


@pytest.mark.parametrize("reason", ["confirmation", "busy", "held", "wrong-owner"])
def test_operator_refuses_unsafe_clear(operator, reason):
    module, latch, owner, state = operator
    state.busy, state.held = reason == "busy", reason == "held"
    with pytest.raises(AxisError):
        module.operator_safety("wrong" if reason == "wrong-owner" else owner,
            inputs_released=reason != "confirmation", clipboard_reviewed=True)
    assert latch.status()["owner"] == owner
    if reason == "busy": assert state.released == 0
    if reason == "confirmation": assert state.acquired == 0


def test_operator_status_has_no_mutex_or_input_effect(operator):
    module, _, owner, state = operator
    assert module.operator_safety()["owner"] == owner
    assert state.acquired == state.released == state.closed == 0


def test_operator_clear_is_exact_and_does_not_replay(operator):
    module, latch, owner, state = operator
    result = module.operator_safety(owner, inputs_released=True, clipboard_reviewed=True)
    assert result["state"] == "clear" and result["effects_replayed"] is False
    assert state.acquired == state.released == state.closed == 1
    assert latch.arm(10) != owner


def test_windows_latch_scope_is_shared_across_processes(tmp_path, monkeypatch):
    module = pytest.importorskip("cu_suite.v2.platforms.windows_safety")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(module.win32service, "GetThreadDesktop", lambda _: 1)
    monkeypatch.setattr(module.win32service, "GetUserObjectInformation", lambda *_: "Default")
    monkeypatch.setattr(module.win32ts, "ProcessIdToSessionId", lambda _: 7)
    first = module.desktop_latch()
    owner = first.arm(100)
    second = module.desktop_latch()
    assert first.path == second.path and second.status()["owner"] == owner
    with pytest.raises(AxisError): second.arm(200)
