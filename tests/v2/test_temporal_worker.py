"""Real spawned observation processes; deterministic scene, never native input."""
import time

import pytest

from cu_suite.v2.contracts import AxisError
from cu_suite.v2.temporal_worker import TemporalObserver
from cu_suite.v2.runtime import Runtime, Policy
from .fake_platform import FakePlatform


SETTINGS = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}],
            "interval": .01, "max_gap": .20, "min_pulse": .5}
BASELINE = {"red": [0, 0, 0]}


def open_scene(path, fault=None, duration=5):
    return TemporalObserver("tests.v2.temporal_fixture", "SceneSource",
        {"marker": str(path), "fault": fault}, SETTINGS, BASELINE, time.monotonic()+duration)


def trigger(path):
    staged = path.with_suffix(".staged")
    staged.write_text(str(time.perf_counter()))
    staged.replace(path)


def test_sampling_continues_while_caller_is_busy_and_preserves_repetitions(tmp_path):
    path = tmp_path/"start"
    observer = open_scene(path)
    try:
        assert not observer.ready["sequence"] and not observer.ready["active"]
        trigger(path)
        time.sleep(1.6)  # Simulate a long in-flight input; no caller polls/captures.
        snapshot = observer.snapshot()
        assert snapshot["sequence"] == ["red", "red"] and not snapshot["active"]
        assert snapshot["samples"] > 20
        assert snapshot["max_observed_gap"] <= SETTINGS["max_gap"]
        assert snapshot["observation_mode"] == "continuous"
        assert not any("image" in key for key in snapshot)
    finally:
        observer.close()
    assert not observer.is_alive()


@pytest.mark.parametrize("fault,code", [("gap", "SAMPLING_GAP"), ("crash", "OBSERVATION_LOST"),
                                         ("moved", "STALE_PROFILE")])
def test_sampling_failure_is_latched_not_restarted(tmp_path, fault, code):
    path = tmp_path/"start"
    observer = open_scene(path, fault)
    process_id = observer._process.pid
    try:
        trigger(path)
        time.sleep(.5)
        with pytest.raises(AxisError) as error:
            observer.snapshot()
        assert error.value.code == code
        assert observer._process.pid == process_id
    finally:
        observer.close()
    assert not observer.is_alive()


def test_stuck_capture_is_stopped_without_waiting_for_source_completion(tmp_path):
    path = tmp_path/"start"
    observer = open_scene(path, "hang")
    trigger(path)
    time.sleep(.05)
    start = time.monotonic()
    observer.close()
    assert time.monotonic()-start < 2
    assert not observer.is_alive()
    observer.close()


def test_observer_protocol_cannot_dispatch_input(tmp_path):
    observer = open_scene(tmp_path/"start")
    try:
        observer._connection.send(("dispatch", "click"))
        with pytest.raises(AxisError) as error:
            observer._receive()
        assert error.value.code == "INVALID_REQUEST"
        assert not hasattr(observer, "dispatch")
    finally:
        observer.close()


def test_cancel_interrupts_stuck_snapshot_and_reader_is_joined(tmp_path):
    import threading
    path = tmp_path/"start"
    cancelled = threading.Event()
    observer = TemporalObserver("tests.v2.temporal_fixture", "SceneSource", {"marker": str(path), "fault": "hang"},
        SETTINGS, BASELINE, time.monotonic()+5, cancel=cancelled)
    timer = threading.Timer(.1, cancelled.set)
    try:
        trigger(path)
        time.sleep(.05)
        timer.start()
        started = time.monotonic()
        with pytest.raises(AxisError) as error:
            observer.snapshot()
        assert error.value.code == "CANCELLED"
        assert time.monotonic()-started < 1
    finally:
        timer.cancel()
        observer.close()
    assert not observer.is_alive()


def test_expired_observer_never_returns_a_late_sample(tmp_path):
    observer = open_scene(tmp_path/"start")
    try:
        observer._deadline = time.monotonic()-.01
        with pytest.raises(AxisError) as error:
            observer.snapshot()
        assert error.value.code in ("DEADLINE_EXCEEDED", "OBSERVATION_LOST")
    finally:
        observer.close()


def test_input_cancel_stops_reader_without_a_parent_checkpoint(tmp_path):
    import multiprocessing
    cancelled = multiprocessing.get_context("spawn").Event()
    observer = TemporalObserver("tests.v2.temporal_fixture", "SceneSource", {"marker": str(tmp_path/"start")},
        SETTINGS, BASELINE, time.monotonic()+5, input_cancel=cancelled)
    try:
        cancelled.set()
        observer._process.join(1)
        assert not observer.is_alive()
        with pytest.raises(AxisError) as error:
            observer.snapshot()
        assert error.value.code == "CANCELLED"
    finally:
        observer.close()
    assert cancelled.is_set(), "Closing a reader must not reset shared input cancellation"


def test_normal_reader_close_does_not_cancel_input_worker(tmp_path):
    import multiprocessing
    cancelled = multiprocessing.get_context("spawn").Event()
    observer = TemporalObserver("tests.v2.temporal_fixture", "SceneSource", {"marker": str(tmp_path/"start")},
        SETTINGS, BASELINE, time.monotonic()+5, input_cancel=cancelled)
    observer.close()
    assert not cancelled.is_set()


@pytest.mark.parametrize("fault", [None, "gap", "moved", "slow_cue", "replaced_during_attach", "rejected", "uncertain_click"])
def test_one_run_captures_during_trigger_and_stops_observer_before_replay(tmp_path, fault):
    path = tmp_path/"start"
    class ScenePlatform(FakePlatform):
        observer = None
        cue_delayed = False
        def capabilities(self):
            return {**super().capabilities(), "temporal_capture": True}
        def open_observer(self, target, settings, baseline, deadline, *, cancel=None):
            self.observer = TemporalObserver("tests.v2.temporal_fixture", "SceneSource",
                {"marker": str(path), "fault": fault}, settings, baseline, deadline, cancel=cancel)
            if fault == "replaced_during_attach":
                self.window["identity"] = "replacement-process"
            return self.observer
        def inspect(self, target):
            if fault == "slow_cue" and path.exists() and not self.cue_delayed:
                self.cue_delayed = True
                time.sleep(1.6)
                self.elements[0]["value"] = "your turn"
            return super().inspect(target)
        def dispatch(self, *args):
            if not self.calls:
                trigger(path)
                if fault != "slow_cue":
                    time.sleep(1.6)
                    self.elements[0]["value"] = "your turn"
            else:
                assert not self.observer.is_alive(), "Own clicks must not be sampled"
                if len(self.calls) == 2 and fault != "rejected":
                    self.elements[0]["value"] = "accepted"
            output = super().dispatch(*args)
            if fault == "uncertain_click" and len(self.calls) == 2:
                raise AxisError("EFFECT_UNKNOWN", "Lost replay click acknowledgement", dispatch="unknown")
            return output
    pal = ScenePlatform()
    rt = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(tmp_path/"jobs.db"))
    try:
        session = rt.call("axis.observe", {"target_id": "test"})["session_id"]
        rt._profiles["p"] = {"session_id": session, **pal.window, "baseline": BASELINE, "settings": SETTINGS}
        result = rt.call("axis.run", {"session_id": session, "idempotency_key": "round", "timeout": 4 if fault == "rejected" else 8,
            "recipe": "sequence-memory.play@1", "recipe_args": {
                "profile_id": "p", "trigger": {"id": "start", "op": "click", "verification": "dispatch_only", "args": {"at": {"selector": {"name": "Input"}}}},
                "player_turn": {"kind": "value", "selector": {"name": "Input"}, "expected": "your turn"},
                "accepted": {"kind": "value", "selector": {"name": "Input"}, "expected": "accepted"}}})
        while result["status"] in ("accepted", "running"):
            time.sleep(.05)
            result = rt.call("axis.job", {"idempotency_key": "round", "action": "result"})
        if fault == "replaced_during_attach":
            assert result["status"] == "failed" and result["error"]["code"] == "STALE_TARGET", result
            assert not pal.calls
        elif fault in ("gap", "moved"):
            assert result["status"] == "partial", result
            assert result["error"]["code"] == ("SAMPLING_GAP" if fault == "gap" else "STALE_PROFILE")
            assert len(pal.calls) == 1
        elif fault == "rejected":
            assert result["status"] == "partial" and result["error"]["code"] == "DEADLINE_EXCEEDED", result
            assert result["error"]["dispatch"] == "sent" and not result["effects_verified"]
            assert len(pal.calls) == 3 and not any(s.get("op") == "replay" and s.get("verification") == "met" for s in result["steps"])
        elif fault == "uncertain_click":
            assert result["status"] == "unknown" and not result["effects_verified"], result
            assert len(pal.calls) == 2 and result["steps"][-1]["dispatch"] == "unknown"
        else:
            assert result["status"] == "completed", result
            assert result["effects_verified"], "Accepted replay must verify the sequence, not pretend each click was independently observed"
            observed = next(step["output"] for step in result["steps"] if step["id"] == "demonstration")
            assert observed["sequence"] == ["red", "red"]
            assert observed["observation_mode"] == "continuous"
            assert len(pal.calls) == 3
            assert result["steps"][0]["verification"] == "unobservable"
            assert [s["verification_scope"]["kind"] for s in result["steps"] if "verification_scope" in s] == ["triggered_demonstration", "sequence_acceptance"]
        assert not pal.observer.is_alive()
    finally:
        rt.close()
