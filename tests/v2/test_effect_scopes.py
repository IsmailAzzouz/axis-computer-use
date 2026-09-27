"""A round-level acceptance can cover its own clicks, not arbitrary effects."""
import copy

import pytest

from cu_suite.v2.perception import sequence_recipe
from cu_suite.v2.runtime import Job, Runtime
from cu_suite.v2.verification import effects_verified
from .fake_platform import FakePlatform


def replay_steps():
    return [
        {"id": "play-0", "op": "click", "dispatch": "sent", "verification": "unobservable"},
        {"id": "play-1", "op": "click", "dispatch": "sent", "verification": "unobservable"},
        {"id": "play", "op": "replay", "dispatch": "sent", "verification": "met", "output": {"replayed": 2},
         "verification_scope": {"kind": "sequence_acceptance", "first_step": 0, "step_count": 2}},
    ]


def test_sequence_acceptance_keeps_individual_clicks_unobservable():
    steps = replay_steps()
    original = copy.deepcopy(steps)
    assert effects_verified(steps)
    assert steps == original and steps[0]["verification"] == "unobservable"


@pytest.mark.parametrize("index,field,value", [
    (0, "dispatch", "unknown"), (0, "dispatch", "not_sent"),
    (0, "error", {"code": "EFFECT_UNKNOWN"}), (0, "op", "type_text"),
    (0, "id", "unrelated-click"), (0, "verification", "unmet"),
    (2, "verification", "unobservable"), (2, "dispatch", "unknown"),
    (2, "error", {"code": "CLEANUP_FAILED"}), (2, "op", "observe"),
    (2, "output", {"replayed": 1}), (2, "output", None),
    (2, "verification_scope", {"kind": "sequence_acceptance", "first_step": -1, "step_count": 3}),
    (2, "verification_scope", {"kind": "sequence_acceptance", "first_step": 0, "step_count": True}),
    (2, "verification_scope", {"kind": "sequence_acceptance", "first_step": 0, "step_count": 1}),
    (2, "verification_scope", {"kind": "anything", "first_step": 0, "step_count": 2}),
])
def test_scope_cannot_verify_unknown_failed_or_unrelated_effects(index, field, value):
    steps = replay_steps()
    steps[index][field] = value
    assert not effects_verified(steps)


def test_other_dispatch_only_input_remains_unverified():
    steps = [{"id": "unrelated", "op": "click", "dispatch": "sent", "verification": "unobservable"}]+replay_steps()
    steps[-1]["verification_scope"]["first_step"] = 1
    assert not effects_verified(steps)


def test_two_replay_iterations_use_ordinals_not_ambiguous_step_names():
    steps = replay_steps()+replay_steps()
    steps[-1]["verification_scope"]["first_step"] = 3
    assert effects_verified(steps)
    steps[3]["dispatch"] = "unknown"
    assert not effects_verified(steps)


def test_recipe_does_not_add_blocking_trigger_wait_or_override_caller_predicate():
    args = {"profile_id": "p", "trigger": {"id": "start", "op": "click", "args": {"at": {"ref": "r"}}},
            "player_turn": {"kind": "exists", "selector": {"name": "Your turn"}},
            "accepted": {"kind": "exists", "selector": {"name": "Accepted"}}}
    original = copy.deepcopy(args)
    assert "postcondition" not in sequence_recipe(args)[0]["args"]["trigger"]
    assert args == original
    args["trigger"]["postcondition"] = {"kind": "exists", "selector": {"name": "Started"}}
    assert sequence_recipe(args)[0]["args"]["trigger"]["postcondition"] == args["trigger"]["postcondition"]


@pytest.mark.parametrize("trigger_op,verified", [("click", True), ("keys", True), ("type_text", False), ("open_app", False)])
def test_completed_demonstration_covers_only_its_physical_trigger(trigger_op, verified):
    steps = [{"id": "start", "op": trigger_op, "dispatch": "sent", "verification": "unobservable"},
        {"id": "watch", "op": "watch", "dispatch": "not_sent", "verification": "met",
         "output": {"sequence": ["red", "red"]}, "verification_scope": {
             "kind": "triggered_demonstration", "first_step": 0, "step_count": 1, "trigger_id": "start"}}]
    assert effects_verified(steps) is verified
    steps[-1]["output"]["sequence"] = []
    assert not effects_verified(steps)
    steps[-1]["output"]["sequence"] = ["red"]
    steps[0]["dispatch"] = "unknown"
    assert not effects_verified(steps)


@pytest.mark.parametrize("status", ["completed", "partial", "unknown", "cancelled"])
def test_durable_job_recovery_preserves_scope_without_replaying(tmp_path, status):
    runtime = Runtime(FakePlatform(), journal_path=str(tmp_path/"db"))
    try:
        from cu_suite.v2.runtime import encoded
        stored = {"status": status, "steps": replay_steps(), "error": None}
        runtime._db.execute("INSERT INTO requests VALUES (?,?,?,?)", ("key", "digest", "job", encoded(stored)))
        runtime._db.commit()
        result = runtime.call("axis.job", {"idempotency_key": "key", "action": "result"})
        assert result["effects_verified"] is (status == "completed")
        assert result["steps"] == stored["steps"] and not runtime._pal.calls
    finally:
        runtime.close()


def test_running_job_cannot_advertise_terminal_scope_verification(tmp_path):
    runtime = Runtime(FakePlatform(), journal_path=str(tmp_path/"db"))
    try:
        job = Job("j", status="running", steps=replay_steps())
        runtime._jobs["j"] = job
        assert not runtime.call("axis.job", {"job_id": "j", "action": "result"})["effects_verified"]
        job.done.set()
    finally:
        runtime.close()


def test_model_cannot_supply_its_own_effect_verification_scope():
    from cu_suite.v2.contracts import AxisError, SCHEMAS, validate
    request = {"session_id": "s", "idempotency_key": "k", "steps": [
        {"id": "focus", "op": "focus", "verification_scope": {
            "kind": "sequence_acceptance", "first_step": 0, "step_count": 1}}]}
    with pytest.raises(AxisError):
        validate(request, SCHEMAS["axis.run"])
