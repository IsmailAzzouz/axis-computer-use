"""Deterministic late-provider boundaries; no desktop or timing-sensitive sleeps."""
import time
from types import SimpleNamespace

import pytest

from cu_suite.v2 import runtime as engine, perception
from cu_suite.v2.runtime import Policy, Runtime
from .fake_platform import FakePlatform


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pal = FakePlatform()
    rt = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path / "deadline.db"))
    session = rt.call("axis.observe", {"target_id": "test"})["session_id"]
    clock = SimpleNamespace(now=100.0)
    fake_time = SimpleNamespace(monotonic=lambda: clock.now, time=time.time, perf_counter=time.perf_counter)
    monkeypatch.setattr(engine, "time", fake_time)
    monkeypatch.setattr(perception, "time", fake_time)
    yield rt, pal, session, clock
    rt.close()


def run(rig, step, *, timeout=10):
    rt, _, session, _ = rig
    return rt.call("axis.run", {"session_id": session, "idempotency_key": "deadline-case",
                               "timeout": timeout, "steps": [step]})


def click(**fields):
    return {"id": "click", "op": "click", "args": {"at": {"selector": {"name": "Input"}}},
            "verification": "dispatch_only", **fields}


def late(obj, method, clock, delay=.2):
    original = getattr(obj, method)
    def delayed(*args, **kwargs):
        value = original(*args, **kwargs)
        clock.now += delay
        return value
    setattr(obj, method, delayed)


@pytest.mark.parametrize("boundary", ["bind", "precondition", "resolve", "journal"])
def test_expired_preparation_never_dispatches(rig, boundary):
    rt, pal, _, clock = rig
    step = click(timeout=.1)
    method = {"bind": "_bind", "precondition": "_predicate", "resolve": "_resolve", "journal": "_journal"}[boundary]
    late(rt, method, clock)
    if boundary == "precondition":
        step["precondition"] = {"kind": "exists", "selector": {"name": "Input"}}
    result = run(rig, step)
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert result["error"]["dispatch"] == "not_sent"
    assert not pal.calls and pal.releases == 1


@pytest.mark.parametrize("op", ["if", "repeat"])
def test_control_step_passes_its_budget_to_children(rig, op):
    _, pal, _, clock = rig
    late(pal, "dispatch", clock)
    children = [click(id="first"), click(id="never")]
    args = {"count": 2, "steps": children} if op == "repeat" else {
        "condition": {"kind": "exists", "selector": {"name": "Input"}}, "then": children}
    result = run(rig, {"id": "parent", "op": op, "timeout": .1, "args": args})
    assert result["status"] == "partial"
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert len(pal.calls) == 1
    assert result["steps"][0]["dispatch"] == "sent"
    assert not result["effects_verified"]


@pytest.mark.parametrize("op", ["observe", "await", "focus", "click"])
def test_late_success_is_not_reported_as_on_time_completion(rig, op):
    rt, pal, _, clock = rig
    if op in ("focus", "click"):
        late(pal, "dispatch", clock)
    else:
        late(pal, "inspect", clock)
    step = click(timeout=.1) if op == "click" else {"id": "late", "op": op, "timeout": .1}
    if op == "await":
        step["args"] = {"timeout": 5, "condition": {"kind": "exists", "selector": {"name": "Input"}}}
    result = run(rig, step)
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert not result["effects_verified"]
    assert result["status"] == ("partial" if op in ("focus", "click") else "failed")
    before = len(pal.calls)
    recovered = rt.call("axis.job", {"idempotency_key": "deadline-case", "action": "result"})
    assert recovered["job_id"] == result["job_id"] and len(pal.calls) == before
    if op in ("focus", "click"):
        assert result["steps"][0]["dispatch"] == "sent"


@pytest.mark.parametrize("op", ["calibrate", "watch", "await_visual"])
def test_perception_baseline_uses_step_deadline_before_further_work(rig, op):
    rt, pal, session, clock = rig
    late(pal, "capture", clock)
    settings = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}],
                "interval": .005, "max_gap": .02, "min_pulse": .1}
    rt._profiles["p"] = {"session_id": session, **pal.window,
                         "baseline": {"red": [0, 0, 0]}, "settings": settings}
    args = {"profile": settings} if op == "calibrate" else {
        "profile_id": "p", "until": {"kind": "exists", "selector": {"name": "Input"}},
        "duration": 5, "trigger": click()} if op == "watch" else {"timeout": 5, "require_change": False, "stable_for": .05}
    result = run(rig, {"id": "perception", "op": op, "args": args, "timeout": .1})
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert not pal.calls and not result["effects_verified"]
    assert list(rt._profiles) == ["p"]


def test_watch_duration_also_bounds_trigger(rig):
    rt, pal, session, clock = rig
    settings = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}],
                "interval": .005, "max_gap": .02, "min_pulse": .1}
    rt._profiles["p"] = {"session_id": session, **pal.window,
                         "baseline": {"red": [0, 0, 0]}, "settings": settings}
    late(pal, "capture", clock)
    result = run(rig, {"id": "watch", "op": "watch", "timeout": 5, "args": {
        "profile_id": "p", "duration": .1, "trigger": click(),
        "until": {"kind": "exists", "selector": {"name": "Input"}}}})
    assert result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert not pal.calls


def test_late_launch_ack_keeps_target_for_reconciliation(rig):
    rt, pal, _, clock = rig
    rt.policy = Policy(frozenset({"test"}), frozenset({"fixture"}))
    late(pal, "dispatch", clock)
    result = run(rig, {"id": "open", "op": "open_app", "timeout": .1, "args": {"app": "fixture"}})
    assert result["status"] == "partial" and result["error"]["dispatch"] == "sent"
    assert result["steps"][0]["output"]["target_id"] == "test"
    assert "test" in rt._created and len(pal.calls) == 1


def test_cancellation_during_dispatch_retains_ack_and_stops(rig):
    rt, pal, session, _ = rig
    original = pal.dispatch
    def cancel_after_ack(*args):
        value = original(*args)
        next(iter(rt._jobs.values())).cancel.set()
        return value
    pal.dispatch = cancel_after_ack
    result = rt.call("axis.run", {"session_id": session, "idempotency_key": "cancel-case",
                                 "steps": [click(), click(id="never")]})
    assert result["status"] == "cancelled" and result["error"]["dispatch"] == "sent"
    assert result["steps"][0]["dispatch"] == "sent" and len(pal.calls) == 1
    assert pal.releases == 1


def test_replay_children_share_remaining_parent_budget(rig, monkeypatch):
    rt, pal, session, clock = rig
    settings = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}]}
    rt._profiles["p"] = {"session_id": session, **pal.window, "settings": settings}
    actual = perception.execute_temporal
    def recorded_watch(runtime, job, sid, target, step, args, outputs, deadline):
        if step["op"] == "watch":
            # Supply a completed observation; only replay timing is under test.
            return {"verification": "met", "output": {"profile_id": "p", "sequence": ["red"]*3}}
        return actual(runtime, job, sid, target, step, args, outputs, deadline)
    monkeypatch.setattr(perception, "execute_temporal", recorded_watch)
    late(pal, "dispatch", clock, delay=.06)
    result = rt.call("axis.run", {"session_id": session, "idempotency_key": "replay-case", "steps": [
        {"id": "watch", "op": "watch", "args": {"profile_id": "p", "until": {"kind": "exists", "selector": {"name": "Input"}}}},
        {"id": "play", "op": "replay", "timeout": .1, "args": {"watch_step": "watch", "interval": .01},
         "postcondition": {"kind": "exists", "selector": {"name": "Input"}}}]})
    assert result["status"] == "partial" and result["error"]["code"] == "DEADLINE_EXCEEDED"
    assert len(pal.calls) == 2 and not result["effects_verified"]
    assert result["steps"][-1]["dispatch"] == "sent"
