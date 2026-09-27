"""A bounded caption search; every point must be natively hit-tested.

Used only for the explicit focus(method=caption_click), never as a hidden
retry of a client-area click or an Alt/AttachThreadInput focus workaround.
"""
import time

from ..contracts import AxisError


def await_foreground(hwnd, foreground, check, deadline, *, clock=time.monotonic, sleep=time.sleep):
    """Observe one submitted activation, without resubmitting it.

    SetForegroundWindow may return before the other input queue activates the
    window. Deadline expiry after submission is an unresolved effect, not proof
    that Windows rejected the request.
    """
    while True:
        check()  # Identity, cancellation and foreign input remain authoritative.
        remaining = deadline-clock()
        if remaining <= 0:
            raise AxisError("EFFECT_UNKNOWN", "Activation was requested but not verified before the deadline; observe before another action", dispatch="unknown")
        if foreground() == hwnd:
            return
        sleep(min(.01, remaining))


def caption_point(bounds, hit_test, belongs_to_target):
    left, top, right, bottom = bounds
    for offset in (12, 24, 36, 48):
        y = top+offset
        if y >= bottom:
            break
        for fraction in (.25, .5, .65, .4, .15):
            x = round(left+(right-left)*fraction)
            if not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
                continue
            if belongs_to_target(x, y) and hit_test(x, y) == 2:  # HTCAPTION
                return x, y
    raise AxisError("ACTIVATION_UNAVAILABLE", "No exposed, native-confirmed caption point; activate this window manually")
