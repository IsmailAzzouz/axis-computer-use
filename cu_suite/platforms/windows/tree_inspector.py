"""Windows UI Automation Tree Inspector with RootWebArea fast-path."""
import re
from typing import List, Dict, Optional, Set
import uiautomation as auto

from cu_suite.interfaces import ITreeInspector
from cu_suite.models import UIElement, BoundingBox, WindowInfo

INTERACTIVE_CONTROL_TYPES: Set[str] = {
    "ButtonControl",
    "EditControl",
    "HyperlinkControl",
    "CheckBoxControl",
    "RadioButtonControl",
    "ComboBoxControl",
    "MenuItemControl",
    "TabItemControl",
    "ListItemControl",
    "DocumentControl",
    "SplitButtonControl",
    "TreeItemControl",
    "ToolBarControl",
    "SpinnerControl",
    "SliderControl",
}

class WindowsTreeInspector(ITreeInspector):
    """Extracts, filters, and formats actionable accessibility trees using Windows UIA."""

    def __init__(self, max_depth: int = 20, max_elements: int = 150):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.current_elements: Dict[int, UIElement] = {}

    def inspect_window(self, target: WindowInfo, focus_document: bool = True) -> List[UIElement]:
        """Traverses the UI tree of a window and returns indexed interactive elements.
        
        If focus_document is True and a browser RootWebArea exists,
        the traversal fast-paths to the active web page content.
        """
        self.current_elements.clear()
        elements: List[UIElement] = []

        window_control = auto.ControlFromHandle(target.handle)
        if not window_control or not window_control.Exists(0, 0):
            return elements

        root_to_traverse = window_control

        # Fast-path for Chromium / Web browsers: find RootWebArea
        if focus_document:
            try:
                root_web = window_control.DocumentControl(searchDepth=12, AutomationId="RootWebArea")
                if root_web.Exists(0, 0):
                    root_to_traverse = root_web
            except Exception:
                pass

        next_id = 1

        def traverse(control: auto.Control, depth: int):
            nonlocal next_id
            if depth > self.max_depth or len(elements) >= self.max_elements:
                return

            try:
                rect = control.BoundingRectangle
                if rect is not None:
                    bbox = BoundingBox(
                        left=rect.left,
                        top=rect.top,
                        right=rect.right,
                        bottom=rect.bottom
                    )
                else:
                    bbox = BoundingBox(0, 0, 0, 0)

                ctrl_type = control.ControlTypeName
                name = (control.Name or "").strip()
                class_name = control.ClassName or ""
                auto_id = control.AutomationId or ""
                is_enabled = control.IsEnabled
                is_focused = control.HasKeyboardFocus

                # Value inspection if supported
                value = None
                try:
                    val_pat = control.GetPattern(auto.PatternId.ValuePattern)
                    if val_pat:
                        value = val_pat.Value
                except Exception:
                    pass

                # Actionable check
                is_standard_interactive = ctrl_type in INTERACTIVE_CONTROL_TYPES
                has_pattern = False
                try:
                    has_pattern = (
                        control.GetPattern(auto.PatternId.InvokePattern) is not None or
                        control.GetPattern(auto.PatternId.TogglePattern) is not None or
                        control.GetPattern(auto.PatternId.SelectionItemPattern) is not None
                    )
                except Exception:
                    pass

                is_text_content = (ctrl_type == "TextControl" and len(name) > 0)
                is_clickable_group = (
                    ctrl_type in {"GroupControl", "PaneControl"} and 
                    ("button" in class_name.lower() or "wrapper" in class_name.lower() or "check" in class_name.lower())
                )

                is_actionable = (
                    is_standard_interactive or
                    has_pattern or
                    is_text_content or
                    is_clickable_group
                )

                if is_actionable and (name or value or is_standard_interactive or is_clickable_group):
                    if bbox.width > 0 and bbox.height > 0:
                        display_name = name if name else f"[{class_name or ctrl_type}]"
                        elem = UIElement(
                            id=next_id,
                            name=display_name,
                            control_type=ctrl_type.replace("Control", ""),
                            class_name=class_name,
                            automation_id=auto_id,
                            bbox=bbox,
                            is_enabled=is_enabled,
                            is_focused=is_focused,
                            value=value,
                            raw_control=control
                        )
                        elements.append(elem)
                        self.current_elements[next_id] = elem
                        next_id += 1

                for child in control.GetChildren():
                    traverse(child, depth + 1)

            except Exception:
                return

        traverse(root_to_traverse, 1)
        return elements

    def get_element_by_id(self, elem_id: int) -> Optional[UIElement]:
        """Retrieves a cached element by its interaction ID."""
        return self.current_elements.get(elem_id)

    def find_elements(self, name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]:
        """Finds elements matching a name regex pattern and optional control type."""
        results: List[UIElement] = []
        regex = re.compile(name_pattern, re.IGNORECASE)
        for elem in self.current_elements.values():
            if regex.search(elem.name):
                if control_type is None or elem.control_type.lower() == control_type.lower():
                    results.append(elem)
        return results

    def format_tree_text(self, window_title: str) -> str:
        """Formats the currently indexed elements into a compact text block for LLMs."""
        lines = [f"=== Active Window: {window_title} ({len(self.current_elements)} elements) ==="]
        for elem in self.current_elements.values():
            details = [f"[{elem.id}] {elem.control_type}"]
            if elem.name:
                details.append(f'"{elem.name}"')
            if elem.value:
                details.append(f'val="{elem.value}"')
            details.append(f"bbox=({elem.bbox.left},{elem.bbox.top},{elem.bbox.width}x{elem.bbox.height})")
            if elem.is_focused:
                details.append("[FOCUSED]")
            if not elem.is_enabled:
                details.append("[DISABLED]")
            lines.append("  " + " ".join(details))
        return "\n".join(lines)
