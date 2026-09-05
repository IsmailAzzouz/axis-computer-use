"""Linux Window Manager implementation using X11/EWMH and wmctrl fallback."""
import re
import subprocess
from typing import List, Optional

from cu_suite.interfaces import IWindowManager
from cu_suite.models import WindowInfo, BoundingBox

class LinuxWindowManager(IWindowManager):
    """Discovers and manipulates Linux windows via X11 / EWMH / wmctrl."""

    def __init__(self):
        self._xlib = None
        self._is_linux = False
        try:
            import Xlib
            import Xlib.display
            self._xlib = Xlib
            self._is_linux = True
        except ImportError:
            self._is_linux = False

    def list_windows(self, include_empty_titles: bool = False) -> List[WindowInfo]:
        """Lists on-screen Linux windows using wmctrl or Xlib."""
        windows: List[WindowInfo] = []

        # Try wmctrl CLI first (standard across Linux desktop distros)
        try:
            out = subprocess.check_output(["wmctrl", "-lGpx"], text=True, stderr=subprocess.DEVNULL)
            # Format: 0x03a00003  0 12345 100 200 800 600 Class.Name Hostname Window Title
            for line in out.strip().splitlines():
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    wid_hex, desktop, pid_str, x_str, y_str, w_str, h_str, wm_class, title = parts
                    handle = int(wid_hex, 16)
                    pid = int(pid_str)
                    x, y, w, h = int(x_str), int(y_str), int(w_str), int(h_str)

                    if not include_empty_titles and not title.strip():
                        continue

                    bbox = BoundingBox(left=x, top=y, right=x + w, bottom=y + h)
                    windows.append(WindowInfo(
                        handle=handle,
                        title=title.strip(),
                        class_name=wm_class,
                        process_id=pid,
                        bbox=bbox,
                        is_active=False
                    ))

            # Determine active window via xdotool if available
            try:
                active_out = subprocess.check_output(["xdotool", "getactivewindow"], text=True, stderr=subprocess.DEVNULL).strip()
                active_id = int(active_out)
                for win in windows:
                    if win.handle == active_id:
                        win.is_active = True
            except Exception:
                pass

            return windows
        except Exception:
            pass

        return windows

    def find_window(self, query: str, regex: bool = False) -> Optional[WindowInfo]:
        windows = self.list_windows()
        for win in windows:
            if regex:
                if re.search(query, win.title, re.IGNORECASE):
                    return win
            else:
                if query.lower() in win.title.lower():
                    return win
        return None

    def get_active_window(self) -> Optional[WindowInfo]:
        windows = self.list_windows(include_empty_titles=True)
        for win in windows:
            if win.is_active:
                return win
        return windows[0] if windows else None

    def activate_window(self, target: WindowInfo) -> bool:
        """Brings the Linux window to the foreground via wmctrl or xdotool."""
        try:
            # Try wmctrl -i -a <hex_id>
            hex_id = hex(target.handle)
            res = subprocess.run(["wmctrl", "-i", "-a", hex_id], stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return True

            # Fallback to xdotool
            res2 = subprocess.run(["xdotool", "windowactivate", str(target.handle)], stderr=subprocess.DEVNULL)
            return res2.returncode == 0
        except Exception:
            return False
