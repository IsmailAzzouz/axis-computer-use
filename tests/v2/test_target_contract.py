"""Malformed PAL targets must never become input authority or verified effects."""
import copy

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform


@pytest.fixture
def state(tmp_path):
    pal = FakePlatform()
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"jobs.db"))
    try:
        yield runtime, pal
    finally:
        runtime.close()


def test_bind_cannot_substitute_another_target_before_observation(state):
    runtime, pal = state
    pal.bind = lambda _: {**pal.window, "target_id": "other"}
    pal.inspect = lambda *_: pytest.fail("Must not inspect substituted window")
    result = runtime.call("axis.observe", {"target_id": "test"})
    assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR"
    assert result["error"]["dispatch"] == "not_sent"
    assert not runtime._sessions and not pal.calls


def test_bind_cannot_substitute_another_target_before_input(state):
    runtime, pal = state
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    pal.bind = lambda _: {**pal.window, "target_id": "other"}
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "wrong-target",
        "steps": [{"id": "focus", "op": "focus"}]})
    assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR"
    assert result["error"]["dispatch"] == "not_sent" and not pal.calls


def test_focus_ack_does_not_verify_replacement_window(state):
    runtime, pal = state
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    dispatch = pal.dispatch
    def replace(*args):
        output = dispatch(*args)
        pal.window["identity"] = "replacement"
        return output
    pal.dispatch = replace
    result = runtime.call("axis.run", {"session_id": session, "idempotency_key": "focus-replaced",
        "steps": [{"id": "focus", "op": "focus"}, {"id": "next", "op": "focus"}]})
    assert result["error"]["code"] == "STALE_TARGET"
    assert result["error"]["dispatch"] == "sent"
    assert not result["effects_verified"] and len(pal.calls) == 1
    recovered = runtime.call("axis.job", {"idempotency_key": "focus-replaced", "action": "result"})
    assert recovered["error"] == result["error"] and len(pal.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("identity", ""), ("geometry_id", None), ("target_id", "desktop"),
    ("bounds", [0, 0, -1, 1]), ("bounds", [0, 0, 1]),
    ("bounds", [0, 0, float("nan"), 1]), ("bounds", [False, 0, 1, 1]),
    ("client_origin", [0, float("inf")]), ("client_origin", "0,0"),
    ("is_active", "false"), ("owner_target_id", []), ("title", None),
    ("extra", object()), ("title", "\ud800"),
])
def test_malformed_target_never_reaches_inspection(state, field, value):
    runtime, pal = state
    pal.window[field] = value
    pal.inspect = lambda *_: pytest.fail("Invalid target must not reach inspection")
    result = runtime.call("axis.observe", {"target_id": "test"})
    assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR", result
    assert result["error"]["dispatch"] == "not_sent" and not pal.calls


def test_duplicate_discovery_ids_are_not_arbitrarily_selected(state):
    runtime, pal = state
    pal.targets = lambda: [pal.window, {**pal.window, "identity": "other-instance"}]
    result = runtime.call("axis.targets", {})
    assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR"
    assert "targets" not in result


def test_discovery_filters_authority_from_one_snapshot(state):
    runtime, pal = state
    calls = []
    def targets():
        calls.append(True)
        if len(calls) > 1:
            raise AxisError("OBSERVATION_UNAVAILABLE", "Do not discard a failed read as policy denial")
        return [pal.window, {**pal.window, "target_id": "dialog", "identity": "dialog-instance",
            "owner_target_id": "test"}, {**pal.window, "target_id": "unrelated", "identity": "unrelated"}]
    pal.targets = targets
    result = runtime.call("axis.targets", {})
    assert {w["target_id"] for w in result["targets"]} == {"test", "dialog"}
    assert len(calls) == 1


def test_duplicate_dialog_id_cannot_grant_input_authority(state):
    runtime, pal = state
    dialog = {**pal.window, "target_id": "dialog", "identity": "dialog-instance"}
    pal.targets = lambda: [pal.window, dialog, {**dialog, "owner_target_id": "test"}]
    with pytest.raises(AxisError) as error:
        runtime._allowed("dialog", mutate=True)
    assert error.value.code == "ADAPTER_CONTRACT_ERROR" and not pal.calls


def test_target_snapshot_is_independent_of_provider_mutation(state):
    runtime, pal = state
    pal.bind = lambda _: pal.window
    snapshot = runtime._bind("test")
    original = copy.deepcopy(snapshot)
    pal.window["bounds"][0] = -300
    pal.window["identity"] = "replacement"
    assert snapshot == original


def test_closed_predicate_rejects_wrong_window_binding(state):
    runtime, pal = state
    target = runtime._bind("test")
    pal.bind = lambda _: {**pal.window, "target_id": "other"}
    with pytest.raises(AxisError) as error:
        runtime._predicate(target, {"kind": "window_closed"})
    assert error.value.code == "ADAPTER_CONTRACT_ERROR"


def test_negative_coordinates_and_collapsed_window_are_valid(state):
    runtime, pal = state
    pal.window["bounds"] = [-300, -100, -300, -100]
    pal.window["client_origin"] = [-300, -100]
    assert runtime._bind("test")["bounds"] == pal.window["bounds"]


@pytest.mark.parametrize("raw", [None, {}, "window"])
def test_non_list_discovery_is_not_an_empty_desktop(state, raw):
    runtime, pal = state
    pal.targets = lambda: raw
    result = runtime.call("axis.targets", {})
    assert result["error"]["code"] == "ADAPTER_CONTRACT_ERROR"
    assert "targets" not in result


def test_discovery_error_remains_an_error_not_an_empty_desktop(state):
    runtime, pal = state
    def targets():
        raise AxisError("OBSERVATION_UNAVAILABLE", "Unavailable desktop")
    pal.targets = targets
    result = runtime.call("axis.targets", {})
    assert result["error"]["code"] == "OBSERVATION_UNAVAILABLE"
    assert "targets" not in result


def test_geometry_change_requires_new_geometry_id(state):
    runtime, pal = state
    original = runtime._bind("test")
    pal.window["client_origin"][0] += 5
    with pytest.raises(AxisError) as error:
        runtime._bind("test", original)
    assert error.value.code == "ADAPTER_CONTRACT_ERROR"
    pal.window["geometry_id"] = "moved"
    assert runtime._bind("test", original)["geometry_id"] == "moved"


def test_long_title_truncation_does_not_mutate_adapter(state):
    runtime, pal = state
    pal.window["title"] = "文"*3000
    result = runtime.call("axis.targets", {})
    assert result["targets"][0]["title_truncated"]
    assert result["targets"][0]["title"] == "文"*2048
    assert pal.window["title"] == "文"*3000


@pytest.mark.parametrize("code,closed", [("TARGET_NOT_FOUND", True), ("TARGET_UNKNOWN", False),
    ("TARGET_UNAVAILABLE", False)])
def test_only_confirmed_original_absence_proves_close(state, code, closed):
    runtime, pal = state
    target = runtime._bind("test")
    def bind(_):
        raise AxisError(code, "Original binding unavailable")
    pal.bind = bind
    if closed:
        assert runtime._predicate(target, {"kind": "window_closed"})
    else:
        with pytest.raises(AxisError) as error:
            runtime._predicate(target, {"kind": "window_closed"})
        assert error.value.code == code
