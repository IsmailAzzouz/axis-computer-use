"""Data models for Computer Use Suite."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

class PlatformType(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"

@dataclass
class BoundingBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def to_dict(self) -> Dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
            "center_x": self.center[0],
            "center_y": self.center[1],
        }

@dataclass
class WindowInfo:
    handle: int
    title: str
    class_name: str
    process_id: int
    bbox: BoundingBox
    is_active: bool
    is_minimized: bool = False
    is_maximized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handle": self.handle,
            "title": self.title,
            "class_name": self.class_name,
            "process_id": self.process_id,
            "is_active": self.is_active,
            "bbox": self.bbox.to_dict(),
        }

@dataclass
class UIElement:
    id: int
    name: str
    control_type: str
    class_name: str
    automation_id: str
    bbox: BoundingBox
    is_enabled: bool
    is_focused: bool
    value: Optional[str] = None
    children_count: int = 0
    raw_control: Any = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "control_type": self.control_type,
            "automation_id": self.automation_id,
            "is_enabled": self.is_enabled,
            "is_focused": self.is_focused,
            "bbox": self.bbox.to_dict(),
        }
        if self.value:
            d["value"] = self.value
        return d

@dataclass
class ActionResult:
    success: bool
    action: str
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
