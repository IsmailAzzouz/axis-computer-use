"""macOS Accessibility Tree Inspector using AXUIElement / ApplicationServices."""
import re
from typing import List, Dict, Optional, Set

from cu_suite.interfaces import ITreeInspector
from cu_suite.models import UIElement, BoundingBox, WindowInfo

MAC_ROLE_MAP: Dict[str, str] = {
    "AXButton": "Button",
    "AXTextField": "Edit",
    "AXTextArea": "Edit",
    "AXLink": "Hyperlink",
    "AXCheckBox": "CheckBox",
    "AXRadioButton": "RadioButton",
    "AXPopUpButton": "ComboBox",
    "AXComboBox": "ComboBox",
    "AXMenuItem": "MenuItem",
    "AXTab": "TabItem",
    "AXWebArea": "Document",
    "AXStaticText": "Text",
    "AXGroup": "Group",
    "AXList": "List",
    "AXRow": "ListItem",
}

class MacOSTreeInspector(ITreeInspector):
    """Extracts and indexes UI elements using macOS AXUIElement."""

    def __init__(self, max_depth: int = 20, max_elements: int = 150):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.current_elements: Dict[int, UIElement] = {}
        self._ax = None
        try:
            import ApplicationServices
            self._ax = ApplicationServices
        except ImportError:
            self._ax = None

    def inspect_window(self, target: WindowInfo, focus_document: bool = True) -> List[UIElement]:
        """Traverses the macOS AXUIElement hierarchy for the target process."""
        self.current_elements.clear()
        elements: List[UIElement] = []

        if not self._ax or target.process_id <= 0:
            return elements

        try:
            app_ref = self._ax.AXUIElementCreateApplication(target.process_id)
            if not app_ref:
                return elements

            next_id = 1

            def traverse(element_ref, depth: int):
                nonlocal next_id
                if depth > self.max_depth or len(elements) >= self.max_elements:
                    return

                try:
                    # Query role
                    err, role_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXRole", None)
                    role = str(role_val) if err == 0 and role_val else "AXGroup"

                    # Query title / value
                    title = ""
                    err, t_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXTitle", None)
                    if err == 0 and t_val:
                        title = str(t_val).strip()

                    val_str = None
                    err, v_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXValue", None)
                    if err == 0 and v_val:
                        val_str = str(v_val).strip()

                    # Query position and size
                    x, y, w, h = 0, 0, 0, 0
                    err, pos_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXPosition", None)
                    if err == 0 and pos_val:
                        # Convert AXValue to CGPoint
                        x, y = int(pos_val.x), int(pos_val.y)

                    err, size_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXSize", None)
                    if err == 0 and size_val:
                        w, h = int(size_val.width), int(size_val.height)

                    bbox = BoundingBox(left=x, top=y, right=x + w, bottom=y + h)
                    norm_type = MAC_ROLE_MAP.get(role, role.replace("AX", ""))

                    is_actionable = norm_type in {"Button", "Edit", "Hyperlink", "CheckBox", "ComboBox", "Document", "Text"}
                    if is_actionable and (title or val_str or norm_type in {"Button", "Edit"}):
                        if bbox.width > 0 and bbox.height > 0:
                            elem = UIElement(
                                id=next_id,
                                name=title if title else f"[{norm_type}]",
                                control_type=norm_type,
                                class_name=role,
                                automation_id="",
                                bbox=bbox,
                                is_enabled=True,
                                is_focused=False,
                                value=val_str,
                                raw_control=element_ref
                            )
                            elements.append(elem)
                            self.current_elements[next_id] = elem
                            next_id += 1

                    # Traverse children
                    err, children_val = self._ax.AXUIElementCopyAttributeValue(element_ref, "AXChildren", None)
                    if err == 0 and children_val:
                        for ch in children_val:
                            traverse(ch, depth + 1)
                except Exception:
                    return

            traverse(app_ref, 1)
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
