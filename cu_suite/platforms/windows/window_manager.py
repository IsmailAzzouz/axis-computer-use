"""Windows Window Manager implementation using Win32 and UI Automation."""
import re
import ctypes
from typing import List, Optional
import uiautomation as auto

from cu_suite.interfaces import IWindowManager
from cu_suite.models import WindowInfo, BoundingBox

user32 = ctypes.windll.user32

class WindowsWindowManager(IWindowManager):
    """Discovers and manipulates Windows desktop application windows."""

    def __init__(self):
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    def list_windows(self, include_empty_titles: bool = False) -> List[WindowInfo]:
        """Lists top-level windows on the Windows desktop."""
        windows: List[WindowInfo] = []
        root = auto.GetRootControl()
        active_handle = user32.GetForegroundWindow()

        for child in root.GetChildren():
            try:
                handle = child.NativeWindowHandle
                title = child.Name or ""
                class_name = child.ClassName or ""
                pid = child.ProcessId

                if not include_empty_titles and not title.strip():
                    continue

                rect = child.BoundingRectangle
                if rect is None:
                    continue

                bbox = BoundingBox(
                    left=rect.left,
                    top=rect.top,
                    right=rect.right,
                    bottom=rect.bottom
                )

                if bbox.width <= 0 or bbox.height <= 0:
                    continue

                is_active = (handle == active_handle)
                windows.append(WindowInfo(
                    handle=handle,
                    title=title,
                    class_name=class_name,
                    process_id=pid,
                    bbox=bbox,
                    is_active=is_active
                ))
            except Exception:
                continue

        return windows

    def find_window(self, query: str, regex: bool = False) -> Optional[WindowInfo]:
        """Finds a window by title substring or regex pattern."""
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
        """Returns the currently focused foreground window."""
        windows = self.list_windows(include_empty_titles=True)
        active_handle = user32.GetForegroundWindow()
        for win in windows:
            if win.handle == active_handle:
                return win
        return None

    def activate_window(self, target: WindowInfo) -> bool:
        """Brings the specified window to the foreground and restores if minimized."""
        try:
            control = auto.ControlFromHandle(target.handle)
            if control and control.Exists(0, 0):
                SW_RESTORE = 9
                user32.ShowWindow(target.handle, SW_RESTORE)
                control.SetActive()
                control.SetFocus()
                return True
        except Exception:
            try:
                user32.ShowWindow(target.handle, 9)
                user32.SetForegroundWindow(target.handle)
                return True
            except Exception:
                return False
        return False
