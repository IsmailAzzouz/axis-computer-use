"""macOS Input Controller implementation."""
import random
import time
from typing import Optional, List, Tuple
import pyperclip
import pyautogui

from cu_suite.interfaces import IInputController
from cu_suite.models import UIElement, ActionResult
from cu_suite.human_kinematics import HumanKinematics

KEY_MAP_MAC = {
    "ctrl": "command",
    "control": "command",
    "win": "command",
    "meta": "command",
}

class MacOSInputController(IInputController):
    """Dispatches inputs on macOS using Command keys and human kinematics."""

    def __init__(self, action_delay: float = 0.2, human_mode: bool = True):
        self.action_delay = action_delay
        self.human_mode = human_mode
        self.kinematics = HumanKinematics()
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

    def _translate_keys(self, keys: Tuple[str, ...]) -> List[str]:
        """Translates generic/Windows keys (ctrl/win) to macOS Command keys."""
        return [KEY_MAP_MAC.get(k.lower(), k) for k in keys]

    def click_element(self, element: UIElement, force_coordinate: bool = False) -> ActionResult:
        """Clicks an element using center bounding box coordinates."""
        cx, cy = element.bbox.center
        if element.bbox.width > 0 and element.bbox.height > 0:
            return self.click_at(cx, cy, target_id=element.id, target_name=element.name)

        return ActionResult(
            success=False,
            action="click",
            target_id=element.id,
            target_name=element.name,
            error="Element has invalid bounding box"
        )

    def click_at(self, x: int, y: int, target_id: Optional[int] = None, target_name: Optional[str] = None) -> ActionResult:
        """Clicks at specific absolute screen coordinates using natural kinematics if enabled."""
        try:
            if self.human_mode:
                self.kinematics.human_click(x, y)
            else:
                pyautogui.click(x, y)
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="click_coordinate_human" if self.human_mode else "click_coordinate",
                target_id=target_id,
                target_name=target_name,
                message=f"Clicked coordinate ({x}, {y}) (macOS human_mode={self.human_mode})"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="click_coordinate",
                target_id=target_id,
                target_name=target_name,
                error=str(e)
            )

    def set_element_value(self, element: UIElement, text: str) -> ActionResult:
        """Sets element text via selection and Command+V paste."""
        try:
            self.click_element(element)
            time.sleep(0.1)
            pyautogui.hotkey("command", "a")
            time.sleep(0.05)
            self.paste_text(text)
            return ActionResult(
                success=True,
                action="paste_fallback",
                target_id=element.id,
                target_name=element.name,
                message=f"Pasted text into element [{element.id}]"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="set_element_value",
                target_id=element.id,
                target_name=element.name,
                error=str(e)
            )

    def paste_text(self, text: str) -> ActionResult:
        """Safely pastes text using system clipboard with Command+V."""
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("command", "v")
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="paste_text",
                message=f"Pasted {len(text)} characters from clipboard (macOS Command+V)"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="paste_text",
                error=str(e)
            )

    def press_keys(self, *keys: str) -> ActionResult:
        """Dispatches key combinations with macOS key translation."""
        try:
            trans_keys = self._translate_keys(keys)
            hold_time = random.uniform(0.04, 0.08) if self.human_mode else 0.0
            if len(trans_keys) == 1:
                pyautogui.keyDown(trans_keys[0])
                time.sleep(hold_time)
                pyautogui.keyUp(trans_keys[0])
            else:
                pyautogui.hotkey(*trans_keys)
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="press_keys",
                message=f"Pressed key combination: {trans_keys}"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="press_keys",
                error=str(e)
            )

    def scroll(self, clicks: int) -> ActionResult:
        """Scrolls mouse wheel vertically."""
        try:
            pyautogui.scroll(clicks)
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="scroll",
                message=f"Scrolled {clicks} clicks"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="scroll",
                error=str(e)
            )
