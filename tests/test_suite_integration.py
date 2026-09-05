"""Integration tests for ComputerUseSuite."""
import unittest
from cu_suite.agent_facade import ComputerUseSuite

class TestSuiteIntegration(unittest.TestCase):
    def setUp(self):
        self.suite = ComputerUseSuite()

    def test_suite_initialization(self):
        self.assertIsNotNone(self.suite.wm)
        self.assertIsNotNone(self.suite.inspector)
        self.assertIsNotNone(self.suite.input)
        self.assertIsNotNone(self.suite.visual)

    def test_suite_list_windows(self):
        windows = self.suite.list_windows()
        self.assertIsInstance(windows, list)
        self.assertGreater(len(windows), 0)

    def test_suite_inspect_format(self):
        # Inspect active window
        text = self.suite.inspect()
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)

if __name__ == "__main__":
    unittest.main()
