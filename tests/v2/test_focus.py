import pytest
from cu_suite.v2.contracts import AxisError, ACTION_ARGS, validate
from cu_suite.v2.platforms.windows_focus import caption_point, await_foreground


def test_caption_click_requires_native_hit_and_same_window():
    candidates = []
    def hit(x, y):
        candidates.append((x, y))
        return 2 if x == 500 else 1
    assert caption_point([0, 0, 1000, 700], hit, lambda *_: True) == (500, 12)
    assert candidates == [(250, 12), (500, 12)]


def test_occluding_window_never_receives_activation_click():
    with pytest.raises(AxisError, match="No exposed"):
        caption_point([0, 0, 1000, 700], lambda *_: pytest.fail("Foreign point must not be hit-tested"), lambda *_: False)


def test_native_buttons_and_client_area_are_not_caption():
    with pytest.raises(AxisError):
        caption_point([-1000, -100, 0, 500], lambda *_: 1, lambda *_: True)


def test_focus_method_is_explicit_and_bounded():
    validate({"method": "caption_click"}, ACTION_ARGS["focus"])
    with pytest.raises(AxisError):
        validate({"method": "alt_hack"}, ACTION_ARGS["focus"])


def test_submitted_activation_waits_for_other_input_queue_without_retry():
    reads = iter([22, 22, 11])
    checks, sleeps = [], []
    await_foreground(11, lambda: next(reads), lambda: checks.append(True), 1,
                     clock=lambda: 0, sleep=sleeps.append)
    assert len(checks) == 3 and sleeps == [.01, .01]


def test_activation_deadline_is_unknown_not_a_rejected_request():
    clock = iter([0, .01, .015])
    sleeps = []
    with pytest.raises(AxisError) as error:
        await_foreground(11, lambda: 22, lambda: None, .015,
                         clock=lambda: next(clock), sleep=sleeps.append)
    assert error.value.code == "EFFECT_UNKNOWN"
    assert error.value.dispatch == "unknown"
    assert sleeps == pytest.approx([.01, .005])


@pytest.mark.parametrize("code", ["CANCELLED", "STALE_TARGET", "USER_INPUT_ACTIVE"])
def test_activation_wait_does_not_ignore_cancellation_or_identity_loss(code):
    def check():
        raise AxisError(code, "Stop")
    with pytest.raises(AxisError) as error:
        await_foreground(11, lambda: 11, check, 1, clock=lambda: 0)
    assert error.value.code == code


@pytest.mark.parametrize("accepted,late_foreground,expected", [
    (True, True, "native"), (True, False, "EFFECT_UNKNOWN"), (False, False, "FOCUS_DENIED"),
])
def test_windows_dispatch_tracks_one_native_activation(monkeypatch, accepted, late_foreground, expected):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows adapter integration; portable wait tested above")
    from cu_suite.v2.platforms import windows
    from cu_suite.v2.platforms import windows_focus
    platform = object.__new__(windows.WindowsPlatform)  # No native handles/input.
    platform._owns_lease = True
    platform.cancel = None
    target = {"handle": 11, "minimized": False}
    platform._fresh = lambda *a, **k: target
    platform._check_user_input = lambda: None
    releases = []
    platform.release = lambda: releases.append(True)
    submitted, polls = [], []
    def submit(hwnd):
        submitted.append(hwnd)
        return accepted
    def foreground():
        if submitted:
            polls.append(True)
            if late_foreground and len(polls) >= 3:
                return 11
        return 22
    monkeypatch.setattr(windows.user32, "SetForegroundWindow", submit)
    monkeypatch.setattr(windows.win32gui, "GetForegroundWindow", foreground)
    clock = iter([0, .01, .02, .03])
    def wait(hwnd, read, check, deadline):
        await_foreground(hwnd, read, check, .03, clock=lambda: next(clock), sleep=lambda _: None)
    monkeypatch.setattr(windows_focus, "await_foreground", wait)
    if expected == "native":
        assert platform.dispatch(target, "focus", {}, 1) == {"activation_method": "native"}
    else:
        with pytest.raises(AxisError) as error:
            platform.dispatch(target, "focus", {}, 1)
        assert error.value.code == expected
        assert error.value.dispatch == ("unknown" if accepted else "not_sent")
    assert submitted == [11] and releases == [True]
    assert platform._did_send == accepted
