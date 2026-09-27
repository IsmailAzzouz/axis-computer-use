"""Actual adapter inspection with isolated native doubles, not desktop evidence."""
from types import SimpleNamespace as NS

import pytest

from cu_suite.v2.contracts import AxisError
from .test_targeted_accessibility import AUTO, Element, UIA
from .test_windows_action_budget import native


class COMError(Exception):
    hresult = -2147467259  # E_FAIL: root retries are limited to ELEMENTNOTAVAILABLE.


def test_adapter_reports_root_com_failure_without_replaying_read(native):
    adapter, state, target, env = native
    env["COMError"] = COMError
    calls = []
    def unavailable(handle):
        calls.append(handle)
        raise COMError("sensitive window contents")
    adapter.auto = NS(ControlFromHandle=unavailable)
    with pytest.raises(AxisError) as error:
        adapter.inspect(target)
    assert error.value.result() == {
        "code": "OBSERVATION_UNAVAILABLE", "dispatch": "not_sent",
        "message": "Native accessibility root failed (HRESULT 0x80004005)"}
    assert calls == [target["handle"]] and state.calls == []


class ElementNotAvailable(COMError):
    hresult = -2147220991


def test_only_element_not_available_reacquires_bounded_root_without_input(native):
    adapter, state, target, env = native
    env["COMError"] = ElementNotAvailable
    calls = []
    root = Element("root")
    def reacquire(handle):
        calls.append(handle)
        if len(calls) < 3:
            raise ElementNotAvailable("destroyed provider element")
        return root
    adapter.auto = NS(**vars(AUTO), ControlFromHandle=reacquire)
    adapter._uia = UIA()
    result = adapter.inspect(target)
    assert result["coverage"] == "complete"
    assert calls == [target["handle"]]*3
    assert state.calls == []


def test_unavailable_root_reacquisition_stops_after_three_attempts(native):
    adapter, state, target, env = native
    env["COMError"] = ElementNotAvailable
    calls = []
    def unavailable(handle):
        calls.append(handle)
        raise ElementNotAvailable("destroyed provider element")
    adapter.auto = NS(**vars(AUTO), ControlFromHandle=unavailable)
    with pytest.raises(AxisError) as error:
        adapter.inspect(target)
    assert error.value.result() == {
        "code": "OBSERVATION_UNAVAILABLE", "dispatch": "not_sent",
        "message": "Native accessibility root failed (HRESULT 0x80040201)"}
    assert calls == [target["handle"]]*3 and state.calls == []


def test_action_deadline_stops_root_reacquisition(native):
    adapter, state, target, env = native
    env["COMError"] = ElementNotAvailable
    calls = []
    def expired(handle):
        calls.append(handle)
        state.now += .2
        raise ElementNotAvailable("destroyed provider element")
    adapter.auto = NS(ControlFromHandle=expired)
    adapter._action_deadline = state.now+.15
    with pytest.raises(AxisError) as error:
        adapter.inspect(target)
    assert error.value.code == "DEADLINE_EXCEEDED"
    assert calls == [target["handle"]] and state.calls == []


def test_adapter_passes_com_type_into_filtered_control_reader(native):
    adapter, state, target, env = native
    env["COMError"] = COMError
    class BrokenValue:
        @property
        def Value(self):
            raise COMError("sensitive field contents")
    edit = Element("input", "Edit")
    edit.GetPattern = lambda kind: BrokenValue() if kind == 1 else None
    root = Element("root", children=[edit])
    adapter.auto = NS(**vars(AUTO), ControlFromHandle=lambda _: root)
    adapter._uia = UIA()
    with pytest.raises(AxisError) as error:
        adapter.inspect(target, {"role": "Edit"})
    assert error.value.code == "OBSERVATION_UNAVAILABLE"
    assert str(error.value) == "Native accessibility value failed (HRESULT 0x80004005)"
    assert state.calls == []
