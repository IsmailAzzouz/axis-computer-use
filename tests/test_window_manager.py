"""Unit tests for WindowManager."""
import unittest
from cu_suite.window_manager import WindowManager

class TestWindowManager(unittest.TestCase):
    def setUp(self):
        self.wm = WindowManager()

    def test_list_windows(self):
        windows = self.wm.list_windows()
        self.assertIsInstance(windows, list)
        self.assertGreater(len(windows), 0, "Should detect at least one open window")

        first = windows[0]
        self.assertGreater(first.handle, 0)
        self.assertIsInstance(first.title, str)
        self.assertGreater(first.bbox.width, 0)
        self.assertGreater(first.bbox.height, 0)

    def test_find_window(self):
        windows = self.wm.list_windows()
        target = windows[0]
        # Query first word of title
        query = target.title.split()[0] if target.title else ""
        if query:
            found = self.wm.find_window(query)
            self.assertIsNotNone(found)

if __name__ == "__main__":
    unittest.main()
