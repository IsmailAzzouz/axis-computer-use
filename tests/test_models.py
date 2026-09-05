"""Unit tests for models."""
import unittest
from cu_suite.models import BoundingBox, WindowInfo, UIElement, ActionResult

class TestModels(unittest.TestCase):
    def test_bounding_box_calculations(self):
        bbox = BoundingBox(left=100, top=200, right=300, bottom=500)
        self.assertEqual(bbox.width, 200)
        self.assertEqual(bbox.height, 300)
        self.assertEqual(bbox.center, (200, 350))

        d = bbox.to_dict()
        self.assertEqual(d["left"], 100)
        self.assertEqual(d["width"], 200)
        self.assertEqual(d["center_x"], 200)

    def test_window_info_serialization(self):
        bbox = BoundingBox(left=0, top=0, right=1920, bottom=1080)
        win = WindowInfo(
            handle=12345,
            title="Test Window",
            class_name="Chrome_WidgetWin_1",
            process_id=999,
            bbox=bbox,
            is_active=True
        )
        d = win.to_dict()
        self.assertEqual(d["handle"], 12345)
        self.assertEqual(d["title"], "Test Window")
        self.assertTrue(d["is_active"])

    def test_ui_element_serialization(self):
        bbox = BoundingBox(left=10, top=20, right=60, bottom=50)
        elem = UIElement(
            id=1,
            name="Submit",
            control_type="Button",
            class_name="Btn",
            automation_id="btn_submit",
            bbox=bbox,
            is_enabled=True,
            is_focused=False,
            value="Click me"
        )
        d = elem.to_dict()
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["name"], "Submit")
        self.assertEqual(d["control_type"], "Button")
        self.assertEqual(d["value"], "Click me")

if __name__ == "__main__":
    unittest.main()
