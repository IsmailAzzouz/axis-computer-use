"""Platform Abstraction Layer (PAL) and Provider Factory."""
import sys
import platform
from typing import Optional

from cu_suite.models import PlatformType
from cu_suite.interfaces import (
    IWindowManager,
    ITreeInspector,
    IInputController,
    IVisualFallback,
)

def detect_platform() -> PlatformType:
    """Identifies the host operating system."""
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return PlatformType.WINDOWS
    elif sys_name == "darwin":
        return PlatformType.MACOS
    elif sys_name == "linux":
        return PlatformType.LINUX
    return PlatformType.UNKNOWN

def get_window_manager(platform_override: Optional[PlatformType] = None) -> IWindowManager:
    """Factory creating the window manager for the current or specified platform."""
    plat = platform_override or detect_platform()
    if plat == PlatformType.WINDOWS:
        from cu_suite.platforms.windows.window_manager import WindowsWindowManager
        return WindowsWindowManager()
    elif plat == PlatformType.MACOS:
        from cu_suite.platforms.macos.window_manager import MacOSWindowManager
        return MacOSWindowManager()
    elif plat == PlatformType.LINUX:
        from cu_suite.platforms.linux.window_manager import LinuxWindowManager
        return LinuxWindowManager()
    else:
        raise NotImplementedError(f"Unsupported operating system platform: {plat}")

def get_tree_inspector(
    platform_override: Optional[PlatformType] = None,
    max_depth: int = 20,
    max_elements: int = 150
) -> ITreeInspector:
    """Factory creating the tree inspector for the current or specified platform."""
    plat = platform_override or detect_platform()
    if plat == PlatformType.WINDOWS:
        from cu_suite.platforms.windows.tree_inspector import WindowsTreeInspector
        return WindowsTreeInspector(max_depth=max_depth, max_elements=max_elements)
    elif plat == PlatformType.MACOS:
        from cu_suite.platforms.macos.tree_inspector import MacOSTreeInspector
        return MacOSTreeInspector(max_depth=max_depth, max_elements=max_elements)
    elif plat == PlatformType.LINUX:
        from cu_suite.platforms.linux.tree_inspector import LinuxTreeInspector
        return LinuxTreeInspector(max_depth=max_depth, max_elements=max_elements)
    else:
        raise NotImplementedError(f"Unsupported operating system platform: {plat}")

def get_input_controller(
    platform_override: Optional[PlatformType] = None,
    action_delay: float = 0.2,
    human_mode: bool = True
) -> IInputController:
    """Factory creating the input controller for the current or specified platform."""
    plat = platform_override or detect_platform()
    if plat == PlatformType.WINDOWS:
        from cu_suite.platforms.windows.input_controller import WindowsInputController
        return WindowsInputController(action_delay=action_delay, human_mode=human_mode)
    elif plat == PlatformType.MACOS:
        from cu_suite.platforms.macos.input_controller import MacOSInputController
        return MacOSInputController(action_delay=action_delay, human_mode=human_mode)
    elif plat == PlatformType.LINUX:
        from cu_suite.platforms.linux.input_controller import LinuxInputController
        return LinuxInputController(action_delay=action_delay, human_mode=human_mode)
    else:
        raise NotImplementedError(f"Unsupported operating system platform: {plat}")

def get_visual_fallback(platform_override: Optional[PlatformType] = None) -> IVisualFallback:
    """Factory creating the visual fallback provider for the current or specified platform."""
    plat = platform_override or detect_platform()
    if plat == PlatformType.WINDOWS:
        from cu_suite.platforms.windows.visual_fallback import WindowsVisualFallback
        return WindowsVisualFallback()
    elif plat == PlatformType.MACOS:
        from cu_suite.platforms.macos.visual_fallback import MacOSVisualFallback
        return MacOSVisualFallback()
    elif plat == PlatformType.LINUX:
        from cu_suite.platforms.linux.visual_fallback import LinuxVisualFallback
        return LinuxVisualFallback()
    else:
        raise NotImplementedError(f"Unsupported operating system platform: {plat}")
