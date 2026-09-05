"""Unit tests for AutofillHandler."""
import unittest
from unittest.mock import MagicMock
from cu_suite.autofill import AutofillHandler
from cu_suite.models import ActionResult

class TestAutofill(unittest.TestCase):
    def test_select_autofill_credential(self):
        mock_input = MagicMock()
        mock_input.click_at.return_value = ActionResult(success=True, action="click")
        mock_input.press_keys.return_value = ActionResult(success=True, action="press")

        handler = AutofillHandler(mock_input)
        res = handler.select_autofill_credential(
            trigger_coord=(500, 300),
            credential_index=1,
            submit=True,
            submit_coord=(500, 400)
        )

        self.assertTrue(res.success)
        mock_input.click_at.assert_any_call(500, 300)
        mock_input.press_keys.assert_any_call("down")
        mock_input.press_keys.assert_any_call("enter")
        mock_input.click_at.assert_any_call(500, 400)

    def test_autofill_multiple_index(self):
        mock_input = MagicMock()
        mock_input.click_at.return_value = ActionResult(success=True, action="click")
        mock_input.press_keys.return_value = ActionResult(success=True, action="press")

        handler = AutofillHandler(mock_input)
        res = handler.select_autofill_credential(
            trigger_coord=(500, 300),
            credential_index=3,
            submit=False
        )

        self.assertTrue(res.success)
        self.assertEqual(mock_input.press_keys.call_count, 4)  # 3 'down' + 1 'enter'

if __name__ == "__main__":
    unittest.main()
