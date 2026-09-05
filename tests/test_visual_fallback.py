"""Unit tests for VisualFallback."""
import unittest
from PIL import Image
from cu_suite.visual_fallback import VisualFallback

class TestVisualFallback(unittest.TestCase):
    def setUp(self):
        self.vf = VisualFallback()

    def test_screen_change_detection(self):
        # Create two identical test images
        img1 = Image.new("RGB", (100, 100), color="red")
        img2 = Image.new("RGB", (100, 100), color="red")
        img3 = Image.new("RGB", (100, 100), color="blue")

        # First image should register as changed (initial state)
        self.assertTrue(self.vf.has_screen_changed(img1))
        # Identical image should register as not changed
        self.assertFalse(self.vf.has_screen_changed(img2))
        # Different image should register as changed
        self.assertTrue(self.vf.has_screen_changed(img3))

if __name__ == "__main__":
    unittest.main()
