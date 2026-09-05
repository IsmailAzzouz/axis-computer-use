"""Abstract interfaces for cross-platform Computer Use providers."""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Tuple
from PIL import Image

from cu_suite.models import WindowInfo, UIElement, ActionResult

class IWindowManager(ABC):
    """Abstract interface for desktop window discovery and manipulation."""

    @abstractmethod
    def list_windows(self, include_empty_titles: bool = False) -> List[WindowInfo]:
        """Lists all visible, actionable windows on the desktop."""
        pass

    @abstractmethod
    def find_window(self, query: str, regex: bool = False) -> Optional[WindowInfo]:
        """Finds a window by title substring or regex."""
        pass

    @abstractmethod
    def get_active_window() -> Optional[WindowInfo]:
        """Returns the currently active / foreground window."""
        pass

    @abstractmethod
    def activate_window(self, target: WindowInfo) -> bool:
        """Brings the window to the foreground and focuses it."""
        pass

class ITreeInspector(ABC):
    """Abstract interface for extracting and indexing UI accessibility trees."""

    @abstractmethod
    def inspect_window(self, target: WindowInfo, focus_document: bool = True) -> List[UIElement]:
        """Traverses the UI tree and returns indexed actionable elements."""
        pass

    @abstractmethod
    def get_element_by_id(self, elem_id: int) -> Optional[UIElement]:
        """Retrieves a cached UIElement by its numeric ID."""
        pass

    @abstractmethod
    def find_elements(self, name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]:
        """Finds elements matching name regex pattern and optional control type."""
        pass

    @abstractmethod
    def format_tree_text(self, window_title: str) -> str:
        """Formats indexed elements into a token-efficient text block."""
        pass

class IInputController(ABC):
    """Abstract interface for cross-platform mouse, keyboard, and pattern input."""

    @abstractmethod
    def click_element(self, element: UIElement, force_coordinate: bool = False) -> ActionResult:
        """Clicks an element via accessibility pattern invocation or coordinates."""
        pass

    @abstractmethod
    def click_at(self, x: int, y: int, target_id: Optional[int] = None, target_name: Optional[str] = None) -> ActionResult:
        """Clicks at absolute screen coordinates."""
        pass

    @abstractmethod
    def set_element_value(self, element: UIElement, text: str) -> ActionResult:
        """Sets element text value."""
        pass

    @abstractmethod
    def paste_text(self, text: str) -> ActionResult:
        """Safely inputs text using clipboard paste."""
        pass

    @abstractmethod
    def press_keys(self, *keys: str) -> ActionResult:
        """Presses key combination with platform key translation."""
        pass

    @abstractmethod
    def scroll(self, clicks: int) -> ActionResult:
        """Scrolls mouse wheel."""
        pass

class IVisualFallback(ABC):
    """Abstract interface for screen capture and perceptual change tracking."""

    @abstractmethod
    def capture_fullscreen(self, save_path: Optional[str] = None) -> Image.Image:
        """Captures the full virtual desktop."""
        pass

    @abstractmethod
    def capture_window(self, window: WindowInfo, save_path: Optional[str] = None) -> Optional[Image.Image]:
        """Captures only the target window bounds."""
        pass

    @abstractmethod
    def has_screen_changed(self, img: Image.Image) -> bool:
        """Compares image with previous state to detect visual modifications."""
        pass
