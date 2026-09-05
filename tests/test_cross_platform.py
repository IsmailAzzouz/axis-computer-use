"""Unit tests for Cross-Platform Abstraction Layer and Factories."""
import unittest
from cu_suite.models import PlatformType, WindowInfo, BoundingBox
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
from cu_suite.platforms.macos.input_controller import MacOSInputController
from cu_suite.agent_facade import ComputerUseSuite

class TestCrossPlatformAbstractions(unittest.TestCase):
    def test_detect_platform(self):
        plat = detect_platform()
        self.assertIn(plat, [PlatformType.WINDOWS, PlatformType.MACOS, PlatformType.LINUX])
        # On this runner, it should detect WINDOWS
        self.assertEqual(plat, PlatformType.WINDOWS)

    def test_interfaces_prevent_direct_instantiation(self):
        with self.assertRaises(TypeError):
            IWindowManager()
        with self.assertRaises(TypeError):
            ITreeInspector()
        with self.assertRaises(TypeError):
            IInputController()
        with self.assertRaises(TypeError):
            IVisualFallback()

    def test_windows_providers_compliance(self):
        wm = get_window_manager(PlatformType.WINDOWS)
        self.assertIsInstance(wm, IWindowManager)

        ti = get_tree_inspector(PlatformType.WINDOWS)
        self.assertIsInstance(ti, ITreeInspector)

        inp = get_input_controller(PlatformType.WINDOWS)
        self.assertIsInstance(inp, IInputController)

        vf = get_visual_fallback(PlatformType.WINDOWS)
        self.assertIsInstance(vf, IVisualFallback)

    def test_macos_providers_compliance(self):
        wm = get_window_manager(PlatformType.MACOS)
        self.assertIsInstance(wm, IWindowManager)

        ti = get_tree_inspector(PlatformType.MACOS)
        self.assertIsInstance(ti, ITreeInspector)

        inp = get_input_controller(PlatformType.MACOS)
        self.assertIsInstance(inp, IInputController)

        vf = get_visual_fallback(PlatformType.MACOS)
        self.assertIsInstance(vf, IVisualFallback)

    def test_linux_providers_compliance(self):
        wm = get_window_manager(PlatformType.LINUX)
        self.assertIsInstance(wm, IWindowManager)

        ti = get_tree_inspector(PlatformType.LINUX)
        self.assertIsInstance(ti, ITreeInspector)

        inp = get_input_controller(PlatformType.LINUX)
        self.assertIsInstance(inp, IInputController)

        vf = get_visual_fallback(PlatformType.LINUX)
        self.assertIsInstance(vf, IVisualFallback)

    def test_macos_key_translation(self):
        mac_input = MacOSInputController()
        translated = mac_input._translate_keys(("ctrl", "l"))
        self.assertEqual(translated, ["command", "l"])

        translated_win = mac_input._translate_keys(("win", "r"))
        self.assertEqual(translated_win, ["command", "r"])

    def test_facade_platform_overrides(self):
        suite_mac = ComputerUseSuite(platform_override=PlatformType.MACOS)
        self.assertEqual(suite_mac.platform, PlatformType.MACOS)
        self.assertIsInstance(suite_mac.wm, IWindowManager)

        suite_linux = ComputerUseSuite(platform_override=PlatformType.LINUX)
        self.assertEqual(suite_linux.platform, PlatformType.LINUX)
        self.assertIsInstance(suite_linux.wm, IWindowManager)

if __name__ == "__main__":
    unittest.main()
