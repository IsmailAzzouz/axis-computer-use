"""Clipboard ownership/rollback tests use no real system clipboard."""
from types import SimpleNamespace
import pytest
from cu_suite.v2.contracts import AxisError


@pytest.fixture
def backend(monkeypatch):
    module = pytest.importorskip("cu_suite.v2.platforms.windows_clipboard")
    state = {"data": {13: "original"}, "sequence": 1, "open": False, "fail_once": False}
    def open_clipboard():
        assert not state["open"]
        state["open"] = True
    def close_clipboard(): state["open"] = False
    def empty():
        assert state["open"]
        state["data"].clear()
        state["sequence"] += 1
    def set_data(kind, value):
        assert state["open"]
        if state["fail_once"]:
            state["fail_once"] = False
            raise OSError("write failed")
        state["data"][kind] = value
        state["sequence"] += 1
    def enum(current):
        keys = sorted(state["data"])
        return next((key for key in keys if key > current), 0)
    fake = SimpleNamespace(OpenClipboard=open_clipboard, CloseClipboard=close_clipboard,
        EmptyClipboard=empty, SetClipboardData=set_data, GetClipboardData=lambda kind: state["data"][kind],
        EnumClipboardFormats=enum, GetClipboardSequenceNumber=lambda: state["sequence"])
    monkeypatch.setattr(module, "clipboard", fake)
    return module, state


def test_restore_only_owned_snapshot(backend):
    module, state = backend
    lease = module.replace_text("payload")
    assert state["data"] == {13: "payload"}
    module.restore(lease)
    assert state["data"] == {13: "original"} and not state["open"]


def test_user_clipboard_change_is_preserved(backend):
    module, state = backend
    lease = module.replace_text("payload")
    state["data"], state["sequence"] = {13: "new user copy"}, 100
    module.restore(lease)
    assert state["data"] == {13: "new user copy"}


def test_unsupported_format_is_not_discarded(backend):
    module, state = backend
    state["data"] = {2: b"bitmap"}
    with pytest.raises(AxisError, match="rich/binary"):
        module.replace_text("payload")
    assert state["data"] == {2: b"bitmap"}


def test_write_failure_restores_before_unlocking(backend):
    module, state = backend
    state["fail_once"] = True
    with pytest.raises(AxisError, match="snapshot restored"):
        module.replace_text("payload")
    assert state["data"] == {13: "original"} and not state["open"]


def test_multiple_pastes_keep_original_snapshot(backend):
    module, state = backend
    lease = module.replace_text("first")
    lease = module.replace_text("second", lease)
    module.restore(lease)
    assert state["data"] == {13: "original"}


@pytest.mark.parametrize("code", ["CANCELLED", "DEADLINE_EXCEEDED"])
def test_expiry_after_snapshot_never_empties_clipboard(backend, code):
    module, state = backend
    checks = []
    def check():
        checks.append(state["open"])
        raise AxisError(code, "Stop before write")
    with pytest.raises(AxisError) as error:
        module.replace_text("payload", check=check)
    assert error.value.code == code and error.value.dispatch == "not_sent"
    assert checks == [True] and not state["open"]
    assert state["data"] == {13: "original"} and state["sequence"] == 1
