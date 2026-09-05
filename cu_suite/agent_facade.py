"""Computer Use Suite High-Level Facade using Platform Abstraction Layer."""
import time
from typing import List, Optional, Tuple

from cu_suite.models import WindowInfo, UIElement, ActionResult, PlatformType
from cu_suite.interfaces import (
    IWindowManager,
    ITreeInspector,
    IInputController,
    IVisualFallback,
)
from cu_suite.platforms import (
    detect_platform,
    get_window_manager,
    get_tree_inspector,
    get_input_controller,
    get_visual_fallback,
)
from cu_suite.autofill import AutofillHandler

class ComputerUseSuite:
    """Unified cross-platform agent facade for semantic-first desktop automation."""

    def __init__(
        self,
        platform_override: Optional[PlatformType] = None,
        max_depth: int = 20,
        max_elements: int = 150,
        action_delay: float = 0.2,
        human_mode: bool = True
    ):
        self.platform: PlatformType = platform_override or detect_platform()
        self.wm: IWindowManager = get_window_manager(self.platform)
        self.inspector: ITreeInspector = get_tree_inspector(self.platform, max_depth=max_depth, max_elements=max_elements)
        self.input: IInputController = get_input_controller(self.platform, action_delay=action_delay, human_mode=human_mode)
        self.visual: IVisualFallback = get_visual_fallback(self.platform)
        self.autofill = AutofillHandler(self.input)
        self.active_window: Optional[WindowInfo] = None

    def list_windows(self) -> List[WindowInfo]:
        """Lists currently open desktop windows."""
        return self.wm.list_windows()

    def focus_window(self, query: str) -> Optional[WindowInfo]:
        """Finds and activates a window by title substring or regex."""
        win = self.wm.find_window(query)
        if not win:
            win = self.wm.find_window(query, regex=True)
        if win:
            if self.wm.activate_window(win):
                time.sleep(0.5)
                self.active_window = win
                return win
        return None

    def inspect(self, focus_document: bool = True) -> str:
        """Inspects the active window and returns a token-efficient text representation."""
        if not self.active_window:
            self.active_window = self.wm.get_active_window()

        if not self.active_window:
            return "No active window found."

        elements = self.inspector.inspect_window(self.active_window, focus_document=focus_document)
        return self.inspector.format_tree_text(self.active_window.title)

    def get_elements(self) -> List[UIElement]:
        """Returns the list of currently indexed interactive elements."""
        return list(self.inspector.current_elements.values())

    def find_elements(self, name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]:
        """Finds elements matching name regex."""
        return self.inspector.find_elements(name_pattern, control_type)

    def click_id(self, elem_id: int) -> ActionResult:
        """Clicks an element by its indexed ID."""
        elem = self.inspector.get_element_by_id(elem_id)
        if not elem:
            return ActionResult(
                success=False,
                action="click_id",
                target_id=elem_id,
                error=f"Element ID {elem_id} not found in active tree"
            )
        return self.input.click_element(elem)

    def click_relative(self, rel_x: int, rel_y: int, window: Optional[WindowInfo] = None) -> ActionResult:
        """Clicks at coordinates relative to the target window top-left corner."""
        target = window or self.active_window or self.wm.get_active_window()
        if not target:
            return ActionResult(
                success=False,
                action="click_relative",
                error="No active window to calculate relative coordinates"
            )
        abs_x = max(0, target.bbox.left) + rel_x
        abs_y = max(0, target.bbox.top) + rel_y
        return self.input.click_at(abs_x, abs_y)

    def click_percentage(self, pct_x: float, pct_y: float, window: Optional[WindowInfo] = None) -> ActionResult:
        """Clicks at percentage (0.0 - 1.0) coordinates relative to target window dimensions."""
        target = window or self.active_window or self.wm.get_active_window()
        if not target:
            return ActionResult(
                success=False,
                action="click_percentage",
                error="No active window to calculate percentage coordinates"
            )
        rel_x = int(target.bbox.width * pct_x)
        rel_y = int(target.bbox.height * pct_y)
        return self.click_relative(rel_x, rel_y, target)

    def set_value_id(self, elem_id: int, text: str) -> ActionResult:
        """Sets the value of an element by ID."""
        elem = self.inspector.get_element_by_id(elem_id)
        if not elem:
            return ActionResult(
                success=False,
                action="set_value_id",
                target_id=elem_id,
                error=f"Element ID {elem_id} not found in active tree"
            )
        return self.input.set_element_value(elem, text)

    def navigate_browser(self, url: str, wait_seconds: float = 3.0) -> ActionResult:
        """Navigates an active browser to a URL using safe cross-platform keyboard shortcuts."""
        # 1. Focus address bar (Cmd+L on Mac, Ctrl+L on Windows/Linux)
        addr_key = "command" if self.platform == PlatformType.MACOS else "ctrl"
        res = self.input.press_keys(addr_key, "l")
        if not res.success:
            return res
        time.sleep(0.3)

        # 2. Paste URL safely
        res = self.input.paste_text(url)
        if not res.success:
            return res
        time.sleep(0.2)

        # 3. Press Enter
        res = self.input.press_keys("enter")
        if not res.success:
            return res

        time.sleep(wait_seconds)
        # Re-inspect active window
        if self.active_window:
            self.active_window = self.wm.get_active_window() or self.active_window
            self.inspector.inspect_window(self.active_window)

        return ActionResult(
            success=True,
            action="navigate_browser",
            message=f"Navigated to {url}"
        )

    def login_with_autofill(
        self,
        rel_trigger_coord: Tuple[int, int] = (486, 347),
        credential_index: int = 1,
        rel_submit_coord: Optional[Tuple[int, int]] = (486, 445),
        wait_seconds: float = 3.0
    ) -> ActionResult:
        """Triggers browser saved credentials dropdown, applies credential, and submits login."""
        target = self.active_window or self.wm.get_active_window()
        if not target:
            return ActionResult(
                success=False,
                action="login_with_autofill",
                error="No active window for autofill login"
            )

        abs_trigger = (max(0, target.bbox.left) + rel_trigger_coord[0], max(0, target.bbox.top) + rel_trigger_coord[1])
        abs_submit = None
        if rel_submit_coord:
            abs_submit = (max(0, target.bbox.left) + rel_submit_coord[0], max(0, target.bbox.top) + rel_submit_coord[1])

        res = self.autofill.select_autofill_credential(
            trigger_coord=abs_trigger,
            credential_index=credential_index,
            submit=True,
            submit_coord=abs_submit
        )
        time.sleep(wait_seconds)
        return res

    def capture_snapshot(self, path: str) -> bool:
        """Captures a snapshot of the active window or desktop."""
        if self.active_window:
            img = self.visual.capture_window(self.active_window, save_path=path)
            if img:
                return True
        img = self.visual.capture_fullscreen(save_path=path)
        return img is not None
