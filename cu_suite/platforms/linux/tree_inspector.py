"""Linux Accessibility Tree Inspector using AT-SPI2 / pyatspi."""
import re
from typing import List, Dict, Optional, Set

from cu_suite.interfaces import ITreeInspector
from cu_suite.models import UIElement, BoundingBox, WindowInfo

LINUX_ROLE_MAP: Dict[str, str] = {
    "push button": "Button",
    "text": "Edit",
    "entry": "Edit",
    "password text": "Edit",
    "link": "Hyperlink",
    "check box": "CheckBox",
    "radio button": "RadioButton",
    "combo box": "ComboBox",
    "menu item": "MenuItem",
    "page tab": "TabItem",
    "document web": "Document",
    "label": "Text",
    "section": "Group",
    "panel": "Group",
    "list": "List",
    "list item": "ListItem",
}

class LinuxTreeInspector(ITreeInspector):
    """Extracts and indexes UI elements on Linux using AT-SPI2."""

    def __init__(self, max_depth: int = 20, max_elements: int = 150):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.current_elements: Dict[int, UIElement] = {}
        self._pyatspi = None
        try:
            import pyatspi
            self._pyatspi = pyatspi
        except ImportError:
            self._pyatspi = None

    def inspect_window(self, target: WindowInfo, focus_document: bool = True) -> List[UIElement]:
        """Traverses the AT-SPI2 tree for the target application."""
        self.current_elements.clear()
        elements: List[UIElement] = []

        if not self._pyatspi:
            return elements

        try:
            reg = self._pyatspi.Registry
            desktop = reg.getDesktop(0)

            # Find matching app by name or PID
            target_app = None
            for app in desktop:
                try:
                    if app.get_process_id() == target.process_id or target.title.lower() in (app.name or "").lower():
                        target_app = app
                        break
                except Exception:
                    continue

            if not target_app:
                return elements

            next_id = 1

            def traverse(node, depth: int):
                nonlocal next_id
                if depth > self.max_depth or len(elements) >= self.max_elements:
                    return

                try:
                    role_name = node.getRoleName()
                    name = (node.name or "").strip()
                    norm_type = LINUX_ROLE_MAP.get(role_name, role_name.title())

                    bbox = BoundingBox(0, 0, 0, 0)
                    try:
                        comp = node.queryComponent()
                        if comp:
                            rect = comp.getExtents(self._pyatspi.DESKTOP_COORDS)
                            bbox = BoundingBox(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
                    except Exception:
                        pass

                    val_str = None
                    try:
                        val = node.queryValue()
                        if val:
                            val_str = str(val.currentValue)
                    except Exception:
                        pass

                    is_actionable = norm_type in {"Button", "Edit", "Hyperlink", "CheckBox", "ComboBox", "Document", "Text"}
                    if is_actionable and (name or val_str or norm_type in {"Button", "Edit"}):
                        if bbox.width > 0 and bbox.height > 0:
                            elem = UIElement(
                                id=next_id,
                                name=name if name else f"[{norm_type}]",
                                control_type=norm_type,
                                class_name=role_name,
                                automation_id="",
                                bbox=bbox,
                                is_enabled=True,
                                is_focused=False,
                                value=val_str,
                                raw_control=node
                            )
                            elements.append(elem)
                            self.current_elements[next_id] = elem
                            next_id += 1

                    for idx in range(node.childCount):
                        traverse(node.getChildAtIndex(idx), depth + 1)
                except Exception:
                    return

            traverse(target_app, 1)
        except Exception:
            pass

        return elements

    def get_element_by_id(self, elem_id: int) -> Optional[UIElement]:
        return self.current_elements.get(elem_id)

    def find_elements(self, name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]:
        results: List[UIElement] = []
        regex = re.compile(name_pattern, re.IGNORECASE)
        for elem in self.current_elements.values():
            if regex.search(elem.name):
                if control_type is None or elem.control_type.lower() == control_type.lower():
                    results.append(elem)
        return results

    def format_tree_text(self, window_title: str) -> str:
        lines = [f"=== Active Window: {window_title} ({len(self.current_elements)} elements) ==="]
        for elem in self.current_elements.values():
            details = [f"[{elem.id}] {elem.control_type}"]
            if elem.name:
                details.append(f'"{elem.name}"')
            if elem.value:
                details.append(f'val="{elem.value}"')
            details.append(f"bbox=({elem.bbox.left},{elem.bbox.top},{elem.bbox.width}x{elem.bbox.height})")
            lines.append("  " + " ".join(details))
        return "\n".join(lines)
