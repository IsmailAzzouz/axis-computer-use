"""Windows Input Controller implementation."""
import random
import time
from typing import Optional, List, Tuple
import pyperclip
import pyautogui
import uiautomation as auto

from cu_suite.interfaces import IInputController
from cu_suite.models import UIElement, ActionResult
from cu_suite.human_kinematics import HumanKinematics

class WindowsInputController(IInputController):
    """Dispatches deterministic or humanized inputs on Windows."""

    def __init__(self, action_delay: float = 0.2, human_mode: bool = True):
        self.action_delay = action_delay
        self.human_mode = human_mode
        self.kinematics = HumanKinematics()
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

    def click_element(self, element: UIElement, force_coordinate: bool = False) -> ActionResult:
        """Clicks an element using UIA pattern invocation or bounding box center click."""
        if not force_coordinate and not self.human_mode and element.raw_control:
            try:
                invoke_pat = element.raw_control.GetPattern(auto.PatternId.InvokePattern)
                if invoke_pat:
                    invoke_pat.Invoke()
                    time.sleep(self.action_delay)
                    return ActionResult(
                        success=True,
                        action="invoke",
                        target_id=element.id,
                        target_name=element.name,
                        message=f"Invoked pattern on element [{element.id}] {element.name}"
                    )
            except Exception:
                pass

        cx, cy = element.bbox.center
        if element.bbox.width > 0 and element.bbox.height > 0:
            return self.click_at(cx, cy, target_id=element.id, target_name=element.name)

        return ActionResult(
            success=False,
            action="click",
            target_id=element.id,
            target_name=element.name,
            error="Element has invalid bounding box and no invoke pattern"
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
                message=f"Clicked coordinate ({x}, {y}) (human_mode={self.human_mode})"
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
        """Sets element text via ValuePattern or clipboard paste fallback."""
        if not self.human_mode and element.raw_control:
            try:
                val_pat = element.raw_control.GetPattern(auto.PatternId.ValuePattern)
                if val_pat:
                    val_pat.SetValue(text)
                    time.sleep(self.action_delay)
                    return ActionResult(
                        success=True,
                        action="set_value_pattern",
                        target_id=element.id,
                        target_name=element.name,
                        message=f"Set value pattern on element [{element.id}]"
                    )
            except Exception:
                pass

        try:
            self.click_element(element)
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "a")
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
        """Safely pastes text using system clipboard to bypass layout mismatches."""
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="paste_text",
                message=f"Pasted {len(text)} characters from clipboard"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="paste_text",
                error=str(e)
            )

    def press_keys(self, *keys: str) -> ActionResult:
        """Dispatches key combinations with slight natural human hold duration."""
        try:
            hold_time = random.uniform(0.04, 0.08) if self.human_mode else 0.0
            if len(keys) == 1:
                pyautogui.keyDown(keys[0])
                time.sleep(hold_time)
                pyautogui.keyUp(keys[0])
            else:
                for k in keys:
                    pyautogui.keyDown(k)
                    time.sleep(0.02)
                time.sleep(hold_time)
                for k in reversed(keys):
                    pyautogui.keyUp(k)
                    time.sleep(0.02)
            time.sleep(self.action_delay)
            return ActionResult(
                success=True,
                action="press_keys",
                message=f"Pressed key combination: {keys}"
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
