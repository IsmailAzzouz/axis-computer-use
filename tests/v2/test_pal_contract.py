"""Portable structural conformance/admission checks. No native input."""
from types import SimpleNamespace

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.pal_contract import read_capabilities, validate_adapter
from cu_suite.v2.runtime import Runtime, Policy
from .fake_platform import FakePlatform


@pytest.mark.parametrize("raw", [None, [], {}, {"actions": "click"}, {"actions": ["click", "click"]},
    {"actions": ["watch"]}, {"actions": ["arbitrary_shell"]}, {"actions": [7]},
    {"actions": [], "capture": "false"}, {"actions": [], "ocr": 1},
    {"actions": [], "interactive": None}, {"actions": [], "targeted_accessibility": True},
    {"actions": [], "temporal_capture": True}, {"actions": [], "extra": float("nan")},
    {"actions": [], "extra": object()}, {"actions": [], "extra": "文"*3000}])
def test_invalid_capability_profiles_are_explicit_errors(raw):
    pal = FakePlatform()
    pal.capabilities = lambda: raw
    with pytest.raises(AxisError) as error:
        read_capabilities(pal)
    assert error.value.code == "ADAPTER_CONTRACT_ERROR"
    assert error.value.dispatch == "not_sent" and not pal.calls


@pytest.mark.parametrize("feature,port", [("accessibility", "inspect"), ("capture", "capture"),
    ("ocr", "ocr"), ("subscriptions", "events"), ("temporal_capture", "open_observer")])
def test_advertised_features_need_callable_ports(feature, port):
    pal = FakePlatform()
    raw = pal.capabilities()
    pal.capabilities = lambda: {**raw, feature: True}
    setattr(pal, port, None)
    with pytest.raises(AxisError) as error:
        read_capabilities(pal)
    assert error.value.code == "ADAPTER_CONTRACT_ERROR"
    assert port in str(error.value)


def test_capabilities_return_an_independent_portable_snapshot():
    pal = FakePlatform()
    original = pal.capabilities()
    original["metadata"] = {"tags": ["experimental"]}
    pal.capabilities = lambda: original
    result = read_capabilities(pal)
    result["actions"].clear()
    result["metadata"]["tags"].append("changed")
    assert original["actions"]
    assert original["metadata"]["tags"] == ["experimental"]


def test_host_admission_requires_native_lease_cancel_and_cleanup_ports():
    pal = FakePlatform()
    for name in ("acquire_lease", "release_lease", "cancel", "cleanup_status"):
        with pytest.raises(AxisError) as error:
            validate_adapter(pal)
        assert name in str(error.value)
        setattr(pal, name, lambda: None)
    assert validate_adapter(pal)["actions"]
    assert not pal.calls


def test_read_only_host_does_not_need_input_ownership_ports():
    pal = FakePlatform()
    pal.capabilities = lambda: {"actions": [], "accessibility": True}
    pal.dispatch = None
    assert validate_adapter(pal)["actions"] == []


def test_malformed_later_capability_stops_before_first_effect(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"jobs.db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        raw = pal.capabilities()
        pal.capabilities = lambda: {**raw, "capture": "false"}
        result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "bad-pal", "steps": [
            {"id": "focus", "op": "focus"}, {"id": "wait", "op": "await_visual", "args": {}}]})
        assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR"
        assert result["error"]["dispatch"] == "not_sent" and not pal.calls
    finally:
        runtime.close()


@pytest.mark.parametrize("feature,tool,extra", [
    ("capture", "axis.capture", {}), ("accessibility", "axis.observe", {}),
    ("capture", "axis.observe", {"scope": "visual_diff"})])
def test_unavailable_reads_never_enter_backend(tmp_path, feature, tool, extra):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"jobs.db"))
    try:
        session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
        if extra:
            extra = {**extra, "since": runtime.call("axis.capture", {"session_id": session, "include_image": False})["frame_id"]}
        raw = pal.capabilities()
        pal.capabilities = lambda: {**raw, feature: False}
        pal.capture = lambda *_: pytest.fail("Unavailable capture must not run")
        pal.inspect = lambda *_: pytest.fail("Unavailable accessibility must not run")
        result = runtime.call(tool, {"session_id": session, **extra})
        assert result["error"]["code"] == "CAPABILITY_UNAVAILABLE", result
    finally:
        runtime.close()


def test_ambiguous_os_registration_does_not_load_either_adapter(monkeypatch):
    from cu_suite.v2 import platforms
    entry = SimpleNamespace(name="axis-test-os", load=lambda: pytest.fail("Ambiguous adapter must not load"))
    monkeypatch.setattr(platforms, "sys", SimpleNamespace(platform="axis-test-os"))
    monkeypatch.setattr(platforms, "entry_points", lambda **_: [entry, entry])
    with pytest.raises(AxisError) as error:
        platforms.create_platform()
    assert error.value.code == "ADAPTER_CONTRACT_ERROR"


def test_rejected_plugin_is_closed_without_input(monkeypatch):
    from cu_suite.v2 import platforms
    pal = FakePlatform()
    closed = []
    pal.close = lambda: closed.append(True)
    entry = SimpleNamespace(name="axis-test-os", load=lambda: lambda: pal)
    monkeypatch.setattr(platforms, "sys", SimpleNamespace(platform="axis-test-os"))
    monkeypatch.setattr(platforms, "entry_points", lambda **_: [entry])
    with pytest.raises(AxisError):
        platforms.create_platform()
    assert closed == [True] and not pal.calls
