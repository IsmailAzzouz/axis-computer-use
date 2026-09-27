"""Read-only source wiring with all native calls doubled."""
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.windows_capture_source import WindowsCaptureSource


@pytest.fixture
def rig(monkeypatch):
    original = {"handle": 123, "identity": "123:99:process-birth:7", "bounds": [0, 0, 20, 20],
        "client_origin": [0, 0], "dpi": 96, "native_class": "Fixture", "geometry_id": "owner-geometry"}
    local = {**original, "identity": "123:99:process-birth:1", "geometry_id": "observer-geometry",
             "minimized": False, "is_active": True}
    calls = []
    class Reader:
        def pump_events(self): calls.append("pump")
        def _target(self, handle):
            assert handle == 123
            return dict(local)
        def capture(self, target):
            assert target["identity"] == "123:99:process-birth:1"
            calls.append("capture")
            return Image.new("RGB", (20, 20))
        def _fresh(self, target, **kwargs):
            calls.append("fresh")
            assert kwargs == {"geometry": True}
            return dict(local)
        def close(self): calls.append("close")
    monkeypatch.setitem(sys.modules, "cu_suite.v2.platforms.windows", SimpleNamespace(WindowsPlatform=Reader))
    return original, local, calls


def test_observer_uses_own_generation_and_rechecks_after_capture(rig):
    target, _, calls = rig
    source = WindowsCaptureSource(target)
    assert source.capture().size == (20, 20)
    source.close()
    assert calls == ["pump", "pump", "capture", "pump", "fresh", "close"]


@pytest.mark.parametrize("key,value", [("identity", "123:99:new-process:1"), ("bounds", [1, 0, 21, 20]),
    ("client_origin", [2, 0]), ("dpi", 144), ("native_class", "Replacement")])
def test_attach_refuses_mismatched_target_and_closes_reader(rig, key, value):
    target, local, calls = rig
    local[key] = value
    with pytest.raises(AxisError) as error:
        WindowsCaptureSource(target)
    assert error.value.code == "STALE_PROFILE"
    assert calls[-1] == "close" and "capture" not in calls


@pytest.mark.parametrize("key,value", [("minimized", True), ("is_active", False)])
def test_visibility_loss_after_capture_is_not_valid_evidence(rig, key, value):
    target, local, _ = rig
    source = WindowsCaptureSource(target)
    local[key] = value
    try:
        with pytest.raises(AxisError) as error:
            source.capture()
        assert error.value.code == "CAPTURE_OCCLUDED"
    finally:
        source.close()
