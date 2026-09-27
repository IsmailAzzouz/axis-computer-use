"""Isolated native Win32 test surface, with an independent read-only JSON oracle.

Run only in an explicitly authorized interactive session. No browser/CDP or
application APIs are exposed to the AXIS runner. --oracle is test-harness only.
"""
import argparse
import ctypes
import json
from pathlib import Path
import random
import time

import win32api
import win32con
import win32gui


class Fixture:
    PAD_REGIONS = {"red": (30, 270, 130, 370), "green": (150, 270, 250, 370),
                   "blue": (270, 270, 370, 370), "yellow": (390, 270, 490, 370)}
    COLORS = {"red": (100, 20, 20), "green": (20, 100, 20), "blue": (20, 20, 100), "yellow": (100, 100, 20)}

    def __init__(self, oracle, *, seed=1, title="AXIS v2 Native Fixture", x=120, y=120, save_dialog=False):
        self.oracle = Path(oracle)
        self.save_dialog = save_dialog
        self.state = {"text": "", "submitted": False, "context": False, "slider": 0,
                      "dragged": False, "round_accepted": False, "closed": False, "save_prompted": False, "saved": False}
        self.sequence = [random.Random(seed).choice(list(self.COLORS)), "red", "red", "green"]
        self.phase, self.lit, self.played, self.schedule = "idle", None, [], []
        self.drag_start = None
        self.hwnd = None
        self.edit = self.status = None
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "AxisV2NativeFixture"
        wc.lpfnWndProc = self.wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW+1
        win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindowEx(0, wc.lpszClassName, title, win32con.WS_OVERLAPPEDWINDOW,
                                           x, y, 620, 540, 0, 0, wc.hInstance, None)
        self.edit = self.child("EDIT", "", 101, 20, 20, 400, 30, win32con.WS_BORDER | win32con.ES_AUTOHSCROLL)
        self.child("BUTTON", "Submit", 102, 440, 20, 120, 30)
        self.status = self.child("STATIC", "Ready", 103, 20, 65, 540, 25)
        self.child("BUTTON", "Start sequence", 104, 20, 105, 160, 30)
        self.child("STATIC", "Drag the square into the outline. Right-click anywhere below.", 105, 20, 145, 550, 25)
        ctypes.windll.comctl32.InitCommonControls()
        self.slider = self.child("msctls_trackbar32", "Value", 106, 210, 105, 300, 30)
        win32gui.SendMessage(self.slider, 0x406, 1, 100 << 16)  # TBM_SETRANGE, 0..100
        self.publish()
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(self.hwnd)
        ctypes.windll.user32.SetTimer(self.hwnd, 1, 20, None)

    def child(self, cls, text, ident, x, y, w, h, style=0):
        return win32gui.CreateWindowEx(0, cls, text, win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP | style,
                                      x, y, w, h, self.hwnd, ident, win32api.GetModuleHandle(None), None)

    def publish(self):
        self.oracle.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.oracle.with_suffix(".tmp")
        # EDIT sends EN_CHANGE between UTF-16 surrogate units; JSON escaping also
        # safely records that transient state until the next notification.
        temporary.write_text(json.dumps({**self.state, "pid": __import__("os").getpid()}, ensure_ascii=True), encoding="utf-8")
        temporary.replace(self.oracle)

    def set_status(self, text):
        if self.status: win32gui.SetWindowText(self.status, text)

    def start(self):
        self.phase, self.played, self.lit = "demo", [], None
        self.state["round_accepted"] = False
        start = time.monotonic()+.3
        self.schedule = []
        for i, name in enumerate(self.sequence):
            self.schedule.extend([(start+i*.8, name), (start+i*.8+.4, None)])
        self.schedule.append((start+len(self.sequence)*.8, "player"))
        self.set_status("Demonstration")
        self.publish()

    def wndproc(self, hwnd, msg, wp, lp):
        if msg == win32con.WM_COMMAND:
            ident, notice = wp & 0xffff, wp >> 16
            if ident == 101 and notice == win32con.EN_CHANGE and self.edit:
                self.state["text"] = win32gui.GetWindowText(self.edit)
                self.publish()
            elif ident == 102:
                self.state["submitted"] = True
                self.set_status("Submitted")
                self.publish()
            elif ident == 104:
                self.start()
            elif ident == 201:
                self.state["context"] = True
                self.set_status("Context accepted")
                self.publish()
            return 0
        if msg == win32con.WM_HSCROLL and hasattr(self, "slider"):
            self.state["slider"] = win32gui.SendMessage(self.slider, 0x400, 0, 0)
            self.publish()
            return 0
        if msg == win32con.WM_CONTEXTMENU:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, 201, "Accept context")
            x, y = win32gui.GetCursorPos()
            try: win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, x, y, 0, hwnd, None)
            finally: win32gui.DestroyMenu(menu)
            return 0
        if msg == win32con.WM_LBUTTONDOWN:
            x, y = lp & 0xffff, (lp >> 16) & 0xffff
            if 30 <= x < 90 and 185 <= y < 235:
                self.drag_start = (x, y)
                win32gui.SetCapture(hwnd)
            if self.phase == "player":
                for name, (l, t, r, b) in self.PAD_REGIONS.items():
                    if l <= x < r and t <= y < b:
                        self.played.append(name)
                        if self.played != self.sequence[:len(self.played)]:
                            self.phase = "failed"
                            self.set_status("Wrong sequence")
                        elif self.played == self.sequence:
                            self.phase = "accepted"
                            self.state["round_accepted"] = True
                            self.set_status("Round accepted")
                        self.publish()
            return 0
        if msg == win32con.WM_LBUTTONUP and self.drag_start:
            x, y = lp & 0xffff, (lp >> 16) & 0xffff
            self.state["dragged"] = 390 <= x < 490 and 180 <= y < 245
            self.drag_start = None
            win32gui.ReleaseCapture()
            self.set_status("Drop accepted" if self.state["dragged"] else "Drop rejected")
            self.publish()
            win32gui.InvalidateRect(hwnd, None, True)
            return 0
        if msg == win32con.WM_TIMER:
            position = win32gui.SendMessage(self.slider, 0x400, 0, 0)
            if self.state["slider"] != position:
                self.state["slider"] = position
                self.publish()
            while self.schedule and self.schedule[0][0] <= time.monotonic():
                _, event = self.schedule.pop(0)
                if event == "player":
                    self.phase, self.lit = "player", None
                    self.set_status("Your turn")
                else:
                    self.lit = event
                win32gui.InvalidateRect(hwnd, None, False)
            return 0
        if msg == win32con.WM_PAINT:
            dc, ps = win32gui.BeginPaint(hwnd)
            try:
                for name, rect in self.PAD_REGIONS.items():
                    rgb = self.COLORS[name]
                    if self.lit == name: rgb = tuple(min(255, c+140) for c in rgb)
                    brush = win32gui.CreateSolidBrush(win32api.RGB(*rgb))
                    win32gui.FillRect(dc, rect, brush)
                    win32gui.DeleteObject(brush)
                win32gui.Rectangle(dc, 390, 180, 490, 245)
                brush = win32gui.CreateSolidBrush(win32api.RGB(80, 80, 80))
                win32gui.FillRect(dc, (410, 190, 470, 240) if self.state["dragged"] else (30, 185, 90, 235), brush)
                win32gui.DeleteObject(brush)
            finally:
                win32gui.EndPaint(hwnd, ps)
            return 0
        if msg == win32con.WM_CLOSE:
            if self.save_dialog and self.state["text"] and not self.state["saved"]:
                self.state["save_prompted"] = True
                self.publish()
                choice = win32gui.MessageBox(hwnd, "Save changes to this AXIS test document?", "AXIS save test",
                                            win32con.MB_YESNOCANCEL | win32con.MB_ICONQUESTION)
                if choice == win32con.IDCANCEL:
                    return 0
                self.state["saved"] = choice == win32con.IDYES
            self.state["closed"] = True
            self.publish()
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wp, lp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--title", default="AXIS v2 Native Fixture")
    parser.add_argument("--x", type=int, default=120)
    parser.add_argument("--y", type=int, default=120)
    parser.add_argument("--save-dialog", action="store_true")
    args = parser.parse_args()
    Fixture(args.oracle, seed=args.seed, title=args.title, x=args.x, y=args.y, save_dialog=args.save_dialog)
    win32gui.PumpMessages()


if __name__ == "__main__":
    main()
