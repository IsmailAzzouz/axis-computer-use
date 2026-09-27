"""Opt-in, read-only caption diagnostic for an explicitly identified test window.

No activation, input, window modification or desktop switching. Native hit tests
are queried only on the supplied HWND after its process birth is verified.
"""
import argparse
import ctypes
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwnd", required=True, type=int)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--birth", required=True)
    args = parser.parse_args()
    import win32api
    import win32gui
    import win32process
    from ctypes import wintypes
    from cu_suite.v2.platforms.windows import user32, ULONG_PTR
    user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    _, pid = win32process.GetWindowThreadProcessId(args.hwnd)
    handle = win32api.OpenProcess(0x1000, False, pid)
    try:
        birth = str(win32process.GetProcessTimes(handle)["CreationTime"])
    finally:
        handle.Close()
    if pid != args.pid or birth != args.birth:
        raise RuntimeError("Test window identity changed; no probes performed")
    bounds = win32gui.GetWindowRect(args.hwnd)
    left, top, right, bottom = bounds
    samples = []
    for offset in (12, 24, 36, 48):
        for fraction in (.25, .5, .65, .4, .15):
            x, y = round(left+(right-left)*fraction), top+offset
            if y >= bottom or not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
                continue
            hit = ULONG_PTR()
            ok = user32.SendMessageTimeoutW(args.hwnd, 0x84, 0,
                    (x & 0xffff) | ((y & 0xffff) << 16), 2, 100, ctypes.byref(hit))
            samples.append({"point": [x, y], "hit": hit.value if ok else None,
                            "exposed_root": user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)})
    print(json.dumps({"hwnd": args.hwnd, "pid": pid, "birth": birth,
                      "bounds": bounds, "foreground": win32gui.GetForegroundWindow(), "samples": samples}))


if __name__ == "__main__":
    main()
