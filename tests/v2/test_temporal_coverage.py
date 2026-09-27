"""Capture/semantic-read latency must not manufacture complete temporal evidence."""
from types import SimpleNamespace

import pytest
from PIL import Image

from cu_suite.v2 import perception
from cu_suite.v2.contracts import AxisError


@pytest.fixture
def rig(monkeypatch):
    state = SimpleNamespace(now=1.0, captures=0, delayed_capture=None,
                            slow_cue=False, final_on=False, move_after=None)
    def counter():
        state.now += .0001
        return state.now
    monkeypatch.setattr(perception, "time", SimpleNamespace(
        monotonic=lambda: state.now, perf_counter=counter))
    target = {"target_id": "test", "identity": "process", "geometry_id": "geometry"}
    settings = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}],
                "interval": .01, "max_gap": .1, "min_pulse": 1.0}
    def capture(_):
        state.captures += 1
        if state.delayed_capture == state.captures:
            state.now += .2
        on = state.captures == 2 or (state.final_on and state.captures >= 4)
        return Image.new("RGB", (20, 20), "red" if on else "black")
    def bind(*_):
        return {**target, "geometry_id": "moved"} if state.move_after and state.captures >= state.move_after else target
    def predicate(*_):
        if state.captures < 3:
            return False
        if state.slow_cue:
            state.now += .2
        return True
    def check(_, deadline):
        if state.now >= deadline:
            raise AxisError("DEADLINE_EXCEEDED", "Expired")
    runtime = SimpleNamespace(_pal=SimpleNamespace(capture=capture), _bind=bind,
        _check=check, _predicate=predicate,
        _bounded_store=lambda store, key, value, limit: store.__setitem__(key, value),
        _profiles={"profile": {"session_id": "session", **target,
            "baseline": {"red": [0, 0, 0]}, "settings": settings}})
    job = SimpleNamespace(cancel=SimpleNamespace(wait=lambda duration: setattr(state, "now", state.now+duration)))
    def run(op="watch"):
        args = {"profile": settings} if op == "calibrate" else {
            "profile_id": "profile", "until": {"kind": "exists"}}
        return perception.execute_temporal(runtime, job, "session", target, {"op": op}, args, {}, 10.0)
    return state, runtime, run


def test_slow_final_capture_is_not_a_complete_demonstration(rig):
    state, _, run = rig
    state.delayed_capture = 3
    with pytest.raises(AxisError) as error:
        run()
    assert error.value.code == "SAMPLING_GAP"


def test_slow_player_cue_read_requires_covered_tail(rig):
    state, _, run = rig
    state.slow_cue = True
    with pytest.raises(AxisError) as error:
        run()
    assert error.value.code == "SAMPLING_GAP"


def test_new_flash_during_cue_read_is_not_replayed_as_complete(rig):
    state, _, run = rig
    state.final_on = True
    with pytest.raises(AxisError) as error:
        run()
    assert error.value.code == "INCOMPLETE_SEQUENCE"


@pytest.mark.parametrize("capture", [1, 3])
def test_geometry_change_inside_capture_invalidates_profile(rig, capture):
    state, _, run = rig
    state.move_after = capture
    with pytest.raises(AxisError) as error:
        run()
    assert error.value.code == "STALE_PROFILE"


def test_normal_covered_tail_keeps_sequence_and_exposes_capture_evidence(rig):
    state, _, run = rig
    result = run()["output"]
    assert result["sequence"] == ["red"]
    assert state.captures == 4
    assert result["samples"] == 4
    assert 0 < result["max_observed_gap"] <= .1


def test_initial_calibration_capture_must_meet_sampling_budget(rig):
    state, runtime, run = rig
    state.delayed_capture = 1
    def capture(_):
        state.captures += 1
        if state.captures == 1:
            state.now += .2
        return Image.new("RGB", (20, 20), "black")
    runtime._pal.capture = capture
    with pytest.raises(AxisError) as error:
        run("calibrate")
    assert error.value.code == "SAMPLING_GAP"
    assert list(runtime._profiles) == ["profile"]


def test_capture_envelopes_bound_worst_case_gap_not_just_completion_times():
    detector = perception.TransitionDetector({"red": [0, 0, 0]}, max_gap=.1)
    detector.feed(1.06, {"red": [0, 0, 0]}, started_at=1.0)
    # Completions are only .06 apart, but pixels may have been acquired at
    # 1.00 then 1.12. This coverage cannot certify a <= .10 sampling gap.
    with pytest.raises(AxisError) as error:
        detector.feed(1.12, {"red": [80, 0, 0]}, started_at=1.07)
    assert error.value.code == "SAMPLING_GAP"
    assert detector.samples == 1 and detector.events == []


@pytest.mark.parametrize("start,end", [(2, 1), (float("nan"), 1), (1, float("inf"))])
def test_invalid_capture_envelope_is_not_evidence(start, end):
    detector = perception.TransitionDetector({"red": [0, 0, 0]}, max_gap=.1)
    with pytest.raises(AxisError) as error:
        detector.feed(end, {"red": [80, 0, 0]}, started_at=start)
    assert error.value.code == "SAMPLING_GAP"
    assert detector.samples == 0 and not detector.events


@pytest.mark.parametrize("fault,code", [
    ("capture_latency", "SAMPLING_GAP"), ("cue_latency", "SAMPLING_GAP"),
    ("tail_flash", "INCOMPLETE_SEQUENCE"), ("moved", "STALE_PROFILE")])
def test_runner_never_replays_a_falsely_complete_tail(tmp_path, monkeypatch, fault, code):
    import time
    from cu_suite.v2.runtime import Runtime, Policy
    from .fake_platform import FakePlatform

    clock = SimpleNamespace(now=1.0)
    def counter():
        clock.now += .001
        return clock.now
    monkeypatch.setattr(perception, "time", SimpleNamespace(monotonic=time.monotonic, perf_counter=counter))
    class Scene(FakePlatform):
        def __init__(self):
            super().__init__()
            self.samples = 0
        def capture(self, target):
            self.samples += 1
            if self.samples == 3:
                self.elements[0]["value"] = "your turn"
                if fault == "capture_latency": clock.now += .2
                if fault == "moved": self.window["geometry_id"] = "moved"
            on = self.samples == 2 or (fault == "tail_flash" and self.samples == 4)
            return Image.new("RGB", (200, 200), "red" if on else "black")
        def inspect(self, target):
            if fault == "cue_latency" and self.samples == 3:
                clock.now += .2
            return super().inspect(target)
    pal = Scene()
    rt = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"coverage.db"))
    try:
        session = rt.call("axis.observe", {"target_id": "test"})["session_id"]
        rt._profiles["profile"] = {"session_id": session, **pal.window,
            "baseline": {"red": [0, 0, 0]}, "settings": {
                "probes": [{"name": "red", "region": [0, 0, 20, 20]}], "interval": .01, "max_gap": .1}}
        result = rt.call("axis.run", {"session_id": session, "idempotency_key": "coverage", "steps": [
            {"id": "watch", "op": "watch", "args": {"profile_id": "profile", "until": {
                "kind": "value", "selector": {"name": "Input"}, "expected": "your turn"}}},
            {"id": "play", "op": "replay", "args": {"watch_step": "watch"},
             "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": "accepted"}}]})
        assert result["status"] == "failed" and result["error"]["code"] == code
        assert not result["effects_verified"] and not pal.calls
        recovered = rt.call("axis.job", {"idempotency_key": "coverage", "action": "result"})
        assert recovered["job_id"] == result["job_id"] and not pal.calls
    finally:
        rt.close()
