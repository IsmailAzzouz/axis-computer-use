"""Windows Visual Fallback implementation."""
import hashlib
from typing import Optional
from PIL import Image
import pyautogui

from cu_suite.interfaces import IVisualFallback
from cu_suite.models import WindowInfo

class WindowsVisualFallback(IVisualFallback):
    """Provides targeted visual snapshots and change detection on Windows."""

    def __init__(self):
        self.last_hash: Optional[str] = None

    def capture_fullscreen(self, save_path: Optional[str] = None) -> Image.Image:
        """Captures the full virtual desktop."""
        img = pyautogui.screenshot()
        if save_path:
            img.save(save_path)
        return img

    def capture_window(self, window: WindowInfo, save_path: Optional[str] = None) -> Optional[Image.Image]:
        """Captures only the target window area."""
        bbox = window.bbox
        if bbox.width <= 0 or bbox.height <= 0:
            return None

        left = max(0, bbox.left)
        top = max(0, bbox.top)
        width = bbox.width
        height = bbox.height

        img = pyautogui.screenshot(region=(left, top, width, height))
        if save_path:
            img.save(save_path)
        return img

    def has_screen_changed(self, img: Image.Image) -> bool:
        """Determines if the visual frame changed compared to the previous snapshot."""
        thumbnail = img.resize((64, 64)).convert("L")
        current_hash = hashlib.sha256(thumbnail.tobytes()).hexdigest()
        changed = (self.last_hash is None or self.last_hash != current_hash)
        self.last_hash = current_hash
        return changed
