"""Browser Autofill and Credential Management for Computer Use Suite."""
import time
from typing import Optional, Tuple
from cu_suite.models import ActionResult, UIElement
from cu_suite.input_controller import InputController

class AutofillHandler:
    """Manages browser credential autofill popup detection and selection."""

    def __init__(self, input_controller: InputController):
        self.input = input_controller

    def select_autofill_credential(
        self,
        trigger_coord: Optional[Tuple[int, int]] = None,
        target_element: Optional[UIElement] = None,
        credential_index: int = 1,
        submit: bool = True,
        submit_coord: Optional[Tuple[int, int]] = None,
        submit_delay: float = 0.5
    ) -> ActionResult:
        """Triggers browser credential popup, selects the specified saved credential, and optionally submits.
        
        Args:
            trigger_coord: Absolute screen coordinates (x, y) to click to trigger the autofill menu.
            target_element: Optional UIElement representing the username/login input field.
            credential_index: 1-based index of the credential in the dropdown (1 for first/default).
            submit: Whether to submit the form after applying credentials.
            submit_coord: Optional (x, y) coordinates of the submit/login button.
            submit_delay: Seconds to wait before submitting.
        """
        try:
            # 1. Trigger the autofill menu
            if target_element:
                self.input.click_element(target_element)
            elif trigger_coord:
                self.input.click_at(trigger_coord[0], trigger_coord[1])
            time.sleep(0.5)

            # 2. Navigate dropdown using Down Arrow
            for _ in range(max(1, credential_index)):
                self.input.press_keys("down")
                time.sleep(0.2)

            # 3. Apply credential with Enter
            self.input.press_keys("enter")
            time.sleep(submit_delay)

            # 4. Submit form
            if submit:
                if submit_coord:
                    self.input.click_at(submit_coord[0], submit_coord[1])
                else:
                    self.input.press_keys("enter")
                time.sleep(1.0)

            return ActionResult(
                success=True,
                action="select_autofill_credential",
                message=f"Applied autofill credential index {credential_index} (submit={submit})"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="select_autofill_credential",
                error=str(e)
            )
