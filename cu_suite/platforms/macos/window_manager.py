"""macOS Window Manager implementation using Quartz and NSWorkspace."""
import re
import subprocess
from typing import List, Optional

from cu_suite.interfaces import IWindowManager
from cu_suite.models import WindowInfo, BoundingBox

class MacOSWindowManager(IWindowManager):
    """Discovers and activates macOS application windows via Quartz / AppleScript."""

    def __init__(self):
        self._quartz = None
        self._appkit = None
        self._is_macos = False
        try:
            import Quartz
            import AppKit
            self._quartz = Quartz
            self._appkit = AppKit
            self._is_macos = True
        except ImportError:
            self._is_macos = False

    def list_windows(self, include_empty_titles: bool = False) -> List[WindowInfo]:
        """Lists on-screen macOS windows."""
        windows: List[WindowInfo] = []

        if not self._is_macos or not self._quartz:
            # Emulated / CLI fallback using osascript if on macOS shell without pyobjc
            try:
                cmd = """
                osascript -e 'tell application "System Events" to get name of every window of (every process whose background only is false)'
                """
                out = subprocess.check_output(["bash", "-c", cmd], text=True, stderr=subprocess.DEVNULL)
                titles = [t.strip() for t in out.split(",") if t.strip()]
                for idx, t in enumerate(titles, 1):
                    windows.append(WindowInfo(
                        handle=idx,
                        title=t,
                        class_name="NSWindow",
                        process_id=0,
                        bbox=BoundingBox(0, 0, 1920, 1080),
                        is_active=(idx == 1)
                    ))
                return windows
            except Exception:
                return windows

        # Native Quartz window enumeration
        try:
            opts = self._quartz.kCGWindowListOptionOnScreenOnly | self._quartz.kCGWindowListExcludeDesktopElements
            win_list = self._quartz.CGWindowListCopyWindowInfo(opts, self._quartz.kCGNullWindowID)

            active_pid = 0
            if self._appkit:
                front_app = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
                if front_app:
                    active_pid = front_app.processIdentifier()

            for w in win_list:
                title = w.get("kCGWindowName", "") or ""
                owner = w.get("kCGWindowOwnerName", "") or ""
                pid = int(w.get("kCGWindowOwnerPID", 0))
                wid = int(w.get("kCGWindowNumber", 0))
                layer = int(w.get("kCGWindowLayer", 0))

                # Normal application window layer is 0
                if layer != 0:
                    continue

                full_title = f"{title} - {owner}" if title and owner else (title or owner)
                if not include_empty_titles and not full_title.strip():
                    continue

                bounds = w.get("kCGWindowBounds", {})
                x = int(bounds.get("X", 0))
                y = int(bounds.get("Y", 0))
                width = int(bounds.get("Width", 0))
                height = int(bounds.get("Height", 0))

                if width <= 0 or height <= 0:
                    continue

                bbox = BoundingBox(left=x, top=y, right=x + width, bottom=y + height)
                is_active = (pid == active_pid)

                windows.append(WindowInfo(
                    handle=wid,
                    title=full_title,
                    class_name="NSWindow",
                    process_id=pid,
                    bbox=bbox,
                    is_active=is_active
                ))
        except Exception:
            pass

        return windows

    def find_window(self, query: str, regex: bool = False) -> Optional[WindowInfo]:
        """Finds a window by title substring or regex."""
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
        """Returns the currently focused frontmost window."""
        windows = self.list_windows(include_empty_titles=True)
        for win in windows:
            if win.is_active:
                return win
        return windows[0] if windows else None

    def activate_window(self, target: WindowInfo) -> bool:
        """Brings the macOS application containing the target window to the front."""
        if not self._is_macos:
            return False

        try:
            if self._appkit and target.process_id > 0:
                app = self._appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(target.process_id)
                if app:
                    app.activateWithOptions_(self._appkit.NSApplicationActivateIgnoringOtherApps)
                    return True

            # Fallback to AppleScript
            clean_title = target.title.replace('"', '\\"')
            cmd = f"""osascript -e 'tell application "{clean_title}" to activate'"""
            subprocess.run(["bash", "-c", cmd], check=True, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
