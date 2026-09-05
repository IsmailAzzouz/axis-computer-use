"""Unit tests for human kinematics."""
import unittest
from cu_suite.human_kinematics import generate_human_path, cubic_bezier

class TestHumanKinematics(unittest.TestCase):
    def test_bezier_points(self):
        p0 = (0.0, 0.0)
        p1 = (50.0, 100.0)
        p2 = (150.0, 100.0)
        p3 = (200.0, 0.0)

        start = cubic_bezier(p0, p1, p2, p3, 0.0)
        mid = cubic_bezier(p0, p1, p2, p3, 0.5)
        end = cubic_bezier(p0, p1, p2, p3, 1.0)

        self.assertEqual(start, (0.0, 0.0))
        self.assertEqual(end, (200.0, 0.0))
        self.assertGreater(mid[1], 0.0)

    def test_generate_human_path(self):
        path = generate_human_path((100, 100), (500, 400), steps=30)
        self.assertEqual(len(path), 30)
        self.assertEqual(path[-1], (500, 400))

if __name__ == "__main__":
    unittest.main()
