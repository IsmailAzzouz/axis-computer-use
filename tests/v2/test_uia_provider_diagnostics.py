"""Portable tests for sanitized UIA provider read diagnostics."""

from types import SimpleNamespace as NS

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.windows_accessibility import read_controls
from .test_targeted_accessibility import AUTO, UIA, Element


SENSITIVE_PROVIDER_TEXT = "provider leaked SECRET_WINDOW_TEXT"


class FakeCOMError(Exception):
    def __init__(self, hresult=0x80040201, message=SENSITIVE_PROVIDER_TEXT):
        super().__init__(message)
        self.hresult = hresult


def fail_once(obj, name):
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise FakeCOMError()

    setattr(obj, name, fail)
    return calls


def assert_provider_diagnostic(error, stage):
    assert error.code == "OBSERVATION_UNAVAILABLE"
    assert error.dispatch == "not_sent"
    assert f"{stage} failed" in str(error)
    assert "0x80040201" in str(error)
    assert SENSITIVE_PROVIDER_TEXT not in str(error)
    assert SENSITIVE_PROVIDER_TEXT not in repr(error.result())


@pytest.mark.parametrize("stage", ["root", "identity", "value", "selection", "geometry"])
def test_known_provider_failures_are_sanitized_and_not_retried(stage):
    node = Element("diagnostic", "Edit")
    if stage == "root":
        calls = fail_once(node, "FindFirst")
    elif stage == "identity":
        calls = fail_once(node, "GetRuntimeId")
    elif stage == "value":
        pattern = FailingValue()
        node.GetPattern = lambda kind: pattern if kind == 1 else None
        calls = pattern.calls
    elif stage == "selection":
        pattern = FailingSelection()
        node.GetPattern = lambda kind: pattern if kind == 4 else None
        calls = pattern.calls
    else:
        node = FailingGeometryElement("diagnostic", "Edit")
        calls = node.geometry_calls

    with pytest.raises(AxisError) as caught:
        read_controls(AUTO, UIA(), [node], provider_errors=(FakeCOMError,))

    assert_provider_diagnostic(caught.value, stage)
    assert calls == [True]


class FailingValue:
    def __init__(self):
        self.calls = []

    @property
    def Value(self):
        self.calls.append(True)
        raise FakeCOMError()


class FailingSelection:
    def __init__(self):
        self.calls = []

    @property
    def IsSelected(self):
        self.calls.append(True)
        raise FakeCOMError()


class FailingGeometryElement(Element):
    def __init__(self, name, role):
        self.geometry_calls = []
        super().__init__(name, role)

    @property
    def BoundingRectangle(self):
        self.geometry_calls.append(True)
        raise FakeCOMError()

    @BoundingRectangle.setter
    def BoundingRectangle(self, _value):
        pass


def test_provider_failure_on_later_root_discards_prior_partial_elements():
    first = Element("already-read")
    broken = Element("broken")
    calls = fail_once(broken, "FindFirst")

    with pytest.raises(AxisError) as caught:
        read_controls(AUTO, UIA(), [first, broken], provider_errors=(FakeCOMError,))

    assert_provider_diagnostic(caught.value, "root")
    assert calls == [True]
    assert "already-read" not in str(caught.value)


def test_missing_hresult_is_reported_as_unavailable_not_zero():
    class NoHresultError(Exception):
        pass

    node = Element("missing-hresult")

    def fail(*_args, **_kwargs):
        raise NoHresultError(SENSITIVE_PROVIDER_TEXT)

    node.FindFirst = fail
    with pytest.raises(AxisError) as caught:
        read_controls(AUTO, UIA(), [node], provider_errors=(NoHresultError,))

    assert caught.value.code == "OBSERVATION_UNAVAILABLE"
    assert caught.value.dispatch == "not_sent"
    assert "HRESULT unavailable" in str(caught.value)
    assert SENSITIVE_PROVIDER_TEXT not in str(caught.value)
    assert "0x00000000" not in str(caught.value)


@pytest.mark.parametrize("error", [RuntimeError(SENSITIVE_PROVIDER_TEXT), AxisError("KEEP", "original")])
def test_unlisted_errors_propagate_unchanged(error):
    node = Element("unchanged")
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise error

    node.FindFirst = fail
    with pytest.raises(type(error)) as caught:
        read_controls(AUTO, UIA(), [node], provider_errors=(FakeCOMError,))

    assert caught.value is error
    assert calls == [True]


def test_injected_provider_exception_type_is_required():
    node = Element("default-propagation")
    calls = fail_once(node, "FindFirst")

    with pytest.raises(FakeCOMError):
        read_controls(AUTO, UIA(), [node])

    assert calls == [True]
