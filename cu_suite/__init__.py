"""Computer Use Suite - Cross-Platform Semantic Desktop Automation."""
from cu_suite.models import (
    PlatformType,
    UIElement,
    WindowInfo,
    BoundingBox,
    ActionResult,
)
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
from cu_suite.autofill import AutofillHandler
from cu_suite.human_kinematics import HumanKinematics
from cu_suite.agent_facade import ComputerUseSuite

# Backward-compatible convenience aliases for default platform
WindowManager = get_window_manager
TreeInspector = get_tree_inspector
InputController = get_input_controller
VisualFallback = get_visual_fallback

__all__ = [
    "PlatformType",
    "UIElement",
    "WindowInfo",
    "BoundingBox",
    "ActionResult",
    "IWindowManager",
    "ITreeInspector",
    "IInputController",
    "IVisualFallback",
    "detect_platform",
    "get_window_manager",
    "get_tree_inspector",
    "get_input_controller",
    "get_visual_fallback",
    "WindowManager",
    "TreeInspector",
    "InputController",
    "VisualFallback",
    "AutofillHandler",
    "HumanKinematics",
    "ComputerUseSuite",
]
