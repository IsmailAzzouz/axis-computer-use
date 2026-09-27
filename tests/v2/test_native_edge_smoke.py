"""Portable contracts for the opt-in native Edge workflow driver."""
from types import SimpleNamespace

import pytest

from .native_edge_smoke import (
    COMPANY, EMAIL, FILE_NAME, PLAN, SmokeFailed, customer_save_steps,
    documents_navigation_steps, require_element, require_job, submit_once,
    upload_file_steps, upload_open_steps, validate_plan,
)
from cu_suite.v2.contracts import compile_steps


def test_customer_search_handles_paginated_list_before_resolving_edit_button():
    from .native_edge_smoke import customer_search_steps, EDIT_MAYA, SEARCH
    steps = customer_search_steps()
    assert compile_steps(steps) == 2
    assert steps[0]["args"]["at"]["selector"] == SEARCH
    assert steps[0]["args"]["text"] == "Maya Chen"
    assert steps[0]["postcondition"]["expected"] == "Maya Chen"
    assert steps[1]["args"]["condition"] == {"kind": "exists", "selector": EDIT_MAYA}


def test_dispatch_only_plan_is_followed_by_native_value_assertion():
    steps = upload_open_steps()
    assert compile_steps(steps) == 1
    assert steps[0]["verification"] == "dispatch_only"
    assert validate_plan(steps) is steps
    altered = [{**steps[0], "id": "other_dialog_action"}]
    with pytest.raises(SmokeFailed, match="later UI verification"):
        validate_plan(altered)


@pytest.mark.parametrize("steps", [
    [{"id": "keydown", "op": "keys", "args": {"keys": ["enter"]}, "verification": "dispatch_only"}],
    [{"id": "click", "op": "click", "args": {"at": {"selector": PLAN}}, "verification": "dispatch_only"},
     {"id": "other", "op": "await", "args": {"condition": {"kind": "exists", "selector": EMAIL}}}],
])
def test_dispatch_only_without_matching_later_assertion_is_rejected(steps):
    with pytest.raises(SmokeFailed, match="later UI verification"):
        validate_plan(steps)


@pytest.mark.parametrize("result", [
    None, {}, {"status": "completed", "effects_verified": False},
    {"status": "unknown", "effects_verified": True},
    {"status": "completed", "effects_verified": True, "next_cursor": "more"},
    {"status": "completed", "effects_verified": True,
     "steps": [{"dispatch": "not_sent", "verification": "unobservable"}]},
])
def test_driver_rejects_failed_unknown_truncated_and_unobservable_results(result):
    with pytest.raises(SmokeFailed):
        require_job(result)


def test_completed_verified_job_is_accepted():
    result = {"status": "completed", "effects_verified": True, "steps": []}
    assert require_job(result) is result


def test_observation_steps_may_be_not_sent_when_the_native_plan_verified():
    result = {"status": "completed", "effects_verified": True,
              "steps": [{"dispatch": "not_sent", "verification": "met"}]}
    assert require_job(result) is result


def test_real_dispatch_only_result_requires_exact_dialog_trigger_and_stays_unverified():
    result = {"status": "completed", "effects_verified": False, "steps": [{
        "id": "choose_file", "op": "click", "dispatch": "sent", "verification": "unobservable"}]}
    with pytest.raises(SmokeFailed):
        require_job(result)
    assert require_job(result, requested_steps=upload_open_steps()) is result
    assert result["effects_verified"] is False


@pytest.mark.parametrize("changes", [{"dispatch": "unknown"}, {"dispatch": "not_sent"},
    {"id": "other"}, {"op": "keys"}, {"error": {"code": "lost"}}, {"verification": "dispatch_only"}])
def test_dialog_exception_never_accepts_unresolved_or_different_input(changes):
    result = {"status": "completed", "effects_verified": False, "steps": [{
        "id": "choose_file", "op": "click", "dispatch": "sent", "verification": "unobservable", **changes}]}
    with pytest.raises(SmokeFailed):
        require_job(result, requested_steps=upload_open_steps())


def test_observation_append_does_not_erase_native_job(tmp_path):
    from .native_edge_smoke import _record_observation
    report = {"stages": {"upload_dialog": {"native_jobs": [{"effects_verified": False}]}}}
    observation = {"coverage": "complete", "elements": []}
    _record_observation(None, report, tmp_path, "upload_dialog", observation)
    assert report["stages"]["upload_dialog"]["native_jobs"] == [{"effects_verified": False}]
    assert report["stages"]["upload_dialog"]["observations"][0]["result"] == observation


@pytest.mark.parametrize("steps", [
    customer_save_steps(),
    documents_navigation_steps("http://127.0.0.1:12345"),
    upload_open_steps(),
    upload_file_steps("C:/testbench/assets/contacts.csv"),
])
def test_real_driver_plans_compile_and_have_postconditions_or_explicit_dialog_verification(steps):
    assert compile_steps(steps) == len(steps)
    assert validate_plan(steps) is steps


def test_customer_plan_verifies_popup_selection_then_committed_combo_value():
    from .native_edge_smoke import STARTER_OPTION, TEAM_OPTION
    steps = customer_save_steps()
    by_id = {step["id"]: step for step in steps}
    assert by_id["open_plan"]["postcondition"] == {"kind": "selected", "selector": STARTER_OPTION, "expected": True}
    assert by_id["choose_team"]["postcondition"] == {"kind": "focused", "selector": TEAM_OPTION, "expected": True}
    assert by_id["commit_team"]["postcondition"]["selector"] == PLAN


def test_upload_dialog_plan_uses_observed_filename_selector():
    assert all(step.get("args", {}).get("at", {}).get("selector") == FILE_NAME
               for step in upload_file_steps("contacts.csv") if step["op"] == "type_text")


@pytest.mark.parametrize("observation", [
    {}, {"coverage": "truncated", "elements": [{"role": "Edit", "name": "Email"}]},
    {"coverage": "complete", "elements": []},
    {"coverage": "complete", "elements": [{"role": "Edit", "name": "Email"}] * 2},
    {"coverage": "complete", "next_cursor": "more", "elements": [{"role": "Edit", "name": "Email"}]},
])
def test_only_unique_complete_observations_satisfy_selector(observation):
    with pytest.raises(SmokeFailed):
        require_element(observation, EMAIL)


def test_provider_error_is_not_mislabeled_as_empty_or_incomplete_tree():
    with pytest.raises(SmokeFailed, match="Observation failed: NATIVE_ERROR"):
        require_element({"error": {"code": "NATIVE_ERROR", "dispatch": "not_sent"}}, EMAIL)


def test_native_plan_is_submitted_once_even_when_result_is_unknown():
    calls = []
    host = SimpleNamespace(run=lambda session, steps: calls.append((session, steps)) or {
        "status": "unknown", "effects_verified": False,
    })
    plan = [{"id": "write", "op": "type_text", "args": {"at": {"selector": COMPANY}, "text": "value"},
             "postcondition": {"kind": "value", "selector": COMPANY, "expected": "value"}}]
    with pytest.raises(SmokeFailed):
        submit_once(host, "session", plan)
    assert len(calls) == 1


def test_existing_output_directory_is_not_reused(tmp_path):
    from .native_edge_smoke import main

    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "report.json"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        main(["--output", str(existing)])
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_startup_failure_retains_bound_fixture_and_never_retries(tmp_path, monkeypatch):
    import json
    from . import native_edge_smoke as smoke
    from testbench.server import Store
    attempts = []
    def unavailable(*args):
        attempts.append(args)
        raise RuntimeError("desktop unavailable")
    monkeypatch.setattr(smoke, "NativeHarness", unavailable)
    output = tmp_path/"fresh-trial"
    assert smoke.main(["--output", str(output)]) == 1
    report = json.loads((output/"report.json").read_text(encoding="utf-8"))
    assert len(attempts) == 1 and report["finished"] is True
    assert report["passed"] is False and report["release_certified"] is False
    assert report["error"]["message"] == "desktop unavailable"
    database = output/"testbench.sqlite3"
    assert database.is_file() and report["oracle_binding"]["database"] == str(database)
    store = Store(database)
    try:
        assert store.state()["run_id"] == report["oracle_binding"]["expected_run_id"]
        assert not store.state()["documents"]
    finally:
        store.close()
