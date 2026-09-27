import pytest
import itertools
from types import SimpleNamespace
from PIL import Image
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.perception import TransitionDetector, tree_diff, visual_diff


def test_repeated_same_color_is_preserved():
    detector = TransitionDetector({"red": [0, 0, 0]}, max_gap=.1)
    for t, red in [(1, 0), (1.02, 60), (1.04, 60), (1.06, 0), (1.08, 60), (1.1, 0)]:
        detector.feed(t, {"red": [red, 0, 0]})
    assert detector.sequence == ["red", "red"]
    assert [e["state"] for e in detector.events] == ["on", "off", "on", "off"]


@pytest.mark.parametrize("timestamp", [1, .5, 1.2])
def test_missing_or_nonmonotonic_samples_rejected(timestamp):
    detector = TransitionDetector({"x": [0, 0, 0]}, max_gap=.1)
    detector.feed(1, {"x": [0, 0, 0]})
    with pytest.raises(AxisError, match="coverage"):
        detector.feed(timestamp, {"x": [100, 0, 0]})


def test_hysteresis_not_cooldown():
    detector = TransitionDetector({"x": [0, 0, 0]}, on_threshold=30, off_threshold=10)
    for t, red in [(1, 35), (1.01, 25), (1.02, 15), (1.03, 9)]: detector.feed(t, {"x": [red, 0, 0]})
    assert len(detector.events) == 2


def test_visual_change_not_effect_success():
    result = visual_diff(Image.new("RGB", (20, 20), "black"), Image.new("RGB", (20, 20), "white"))
    assert result["changed"] and result["verification"] == "unobservable"


def test_mask_ignores_unstable_pixels():
    result = visual_diff(Image.new("RGB", (20, 20), "black"), Image.new("RGB", (20, 20), "white"), masks=[[0, 0, 20, 20]])
    assert not result["changed"]


def test_diff_does_not_invent_disappearance():
    before = {"target_id": "a", "identity": "a", "epoch": "d", "coverage": "complete", "elements": [{"native_id": "x"}]}
    after = {**before, "coverage": "truncated", "elements": []}
    assert tree_diff(before, after)["disappeared"] is None


@pytest.mark.parametrize("operation", ["calibrate", "watch"])
def test_temporal_sampling_does_not_use_a_coarse_deadline_clock(monkeypatch, operation):
    from cu_suite.v2 import perception
    # Deterministic reproduction of sub-tick captures on Windows/Python 3.12:
    # deadline time stays constant while the capture counter advances.
    ticks = itertools.count(1.001, .001)
    monkeypatch.setattr(perception, "time", SimpleNamespace(monotonic=lambda: 100.0, perf_counter=lambda: next(ticks)))
    target = {"target_id": "test", "identity": "process", "geometry_id": "geometry"}
    settings = {"probes": [{"name": "red", "region": [0, 0, 20, 20]}],
                "interval": .005, "max_gap": .02, "min_pulse": .1}
    colors = iter(["black"]*4 if operation == "calibrate" else ["black", "red", "black", "red", "black", "black"])
    captured = []
    def capture(_):
        captured.append(True)
        return Image.new("RGB", (20, 20), next(colors))
    runtime = SimpleNamespace(_pal=SimpleNamespace(capture=capture),
        _check=lambda *_: None, _bind=lambda *_: target,
        _predicate=lambda *_: len(captured) == 5,
        _bounded_store=lambda store, key, value, limit: store.__setitem__(key, value),
        _profiles={"profile": {"session_id": "session", **target,
            "baseline": {"red": [0, 0, 0]}, "settings": settings}})
    job = SimpleNamespace(cancel=SimpleNamespace(wait=lambda _: False))
    args = {"profile": settings} if operation == "calibrate" else {"profile_id": "profile", "until": {"kind": "exists"}}
    result = perception.execute_temporal(runtime, job, "session", target, {"op": operation}, args, {}, 200.0)
    assert result["verification"] == "met"
    if operation == "watch":
        assert result["output"]["sequence"] == ["red", "red"]
        assert result["output"]["sample_clock"] == "performance_counter"
