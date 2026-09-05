# AXIS Computer Use Suite (`axis-computer-use` / `cu_suite`) API Reference

**AXIS** (`cu_suite` / `axis-computer-use`) provides a sovereign, cross-platform, semantic accessibility-first desktop automation framework designed for autonomous AI agents and programmatic desktop interaction.

> *"Action is the Evidence."*

---

## 1. Core Architecture & Philosophy

The suite transitions desktop automation from fragile vision-only guessing to a **Semantic Accessibility-First (A11y) Hybrid Model**:
1. **Primary Interface (A11y Tree):** Queries the OS-native accessibility tree (Windows UI Automation, macOS AXUIElement, Linux AT-SPI2). Interactive controls (buttons, inputs, links) are indexed with sequential integer IDs (`[1]`, `[2]`, `[3]`) and bounding boxes.
2. **Kinematic Input Engine:** Simulates natural human motor control using cubic Bézier curves, minimum-jerk velocity easing, micro-tremor jitter, and pre-click dwell times to pass behavioral anti-bot checks.
3. **Cross-Layout Text Safety:** Defaults to clipboard-based injection (`Ctrl+V` / `Command+V`) to prevent character distortion on international layouts (e.g., AZERTY vs. QWERTY), with keystroke typing fallbacks when paste is blocked (`onpaste="return false;"`).
4. **Targeted Visual Fallback:** Bounds screen captures to specific windows or coordinates and detects frame changes via perceptual hash comparisons before invoking expensive multimodal vision models.

---

## 2. Data Models (`cu_suite.models`)

### `PlatformType`
Enum identifying the target operating system.
* Values: `WINDOWS = "windows"`, `MACOS = "macos"`, `LINUX = "linux"`, `UNKNOWN = "unknown"`

### `BoundingBox`
Represents an element or window coordinate rectangle.
* Attributes:
  * `left: int`: X-coordinate of left edge.
  * `top: int`: Y-coordinate of top edge.
  * `right: int`: X-coordinate of right edge.
  * `bottom: int`: Y-coordinate of bottom edge.
* Properties:
  * `width -> int`: `max(0, right - left)`
  * `height -> int`: `max(0, bottom - top)`
  * `center -> Tuple[int, int]`: Center point `(left + width // 2, top + height // 2)`.
* Methods:
  * `to_dict() -> Dict[str, int]`: Returns dictionary with keys `left`, `top`, `right`, `bottom`, `width`, `height`, `center_x`, `center_y`.

### `WindowInfo`
Metadata describing a top-level desktop application window.
* Attributes:
  * `handle: int`: Native window handle (HWND on Windows, CGWindowID on macOS, XID on Linux).
  * `title: str`: Window title bar text.
  * `class_name: str`: Window class identifier (e.g., `Chrome_WidgetWin_1`, `NSWindow`).
  * `process_id: int`: Process ID (PID) owning the window.
  * `bbox: BoundingBox`: Window bounding box coordinates.
  * `is_active: bool`: True if the window is the current foreground window.
  * `is_minimized: bool = False`: Minimized state flag.
  * `is_maximized: bool = False`: Maximized state flag.
* Methods:
  * `to_dict() -> Dict[str, Any]`: Serializes window info to dictionary.

### `UIElement`
Represents an actionable control in the accessibility tree.
* Attributes:
  * `id: int`: Sequential interaction integer assigned during tree traversal (`1, 2, 3...`).
  * `name: str`: Accessible label or descriptive name.
  * `control_type: str`: Normalized control type (`Button`, `Edit`, `Hyperlink`, `CheckBox`, `Document`, `Text`).
  * `class_name: str`: Native framework class or role name.
  * `automation_id: str`: Unique automation ID if provided by the application.
  * `bbox: BoundingBox`: Absolute screen bounding box.
  * `is_enabled: bool`: True if the element can accept user input.
  * `is_focused: bool`: True if the element has keyboard focus.
  * `value: Optional[str]`: Current text value if element supports ValuePattern.
  * `raw_control: Any`: Underlying native COM/AX/AT-SPI object (omitted in repr).
* Methods:
  * `to_dict() -> Dict[str, Any]`: Serializes element to dictionary.

### `ActionResult`
Standard return structure for all input, navigation, and inspection operations.
* Attributes:
  * `success: bool`: Whether the action completed successfully.
  * `action: str`: Action name (`invoke`, `click_coordinate`, `paste_text`, `navigate_browser`).
  * `target_id: Optional[int]`: Element ID targeted.
  * `target_name: Optional[str]`: Name of targeted element.
  * `message: str`: Informative diagnostic message.
  * `error: Optional[str]`: Error description if unsuccessful.

---

## 3. Abstract Interfaces (`cu_suite.interfaces`)

The Platform Abstraction Layer relies on four abstract base classes (ABCs):

### `IWindowManager(ABC)`
```python
def list_windows(self, include_empty_titles: bool = False) -> List[WindowInfo]: ...
def find_window(self, query: str, regex: bool = False) -> Optional[WindowInfo]: ...
def get_active_window(self) -> Optional[WindowInfo]: ...
def activate_window(self, target: WindowInfo) -> bool: ...
```

### `ITreeInspector(ABC)`
```python
def inspect_window(self, target: WindowInfo, focus_document: bool = True) -> List[UIElement]: ...
def get_element_by_id(self, elem_id: int) -> Optional[UIElement]: ...
def find_elements(self, name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]: ...
def format_tree_text(self, window_title: str) -> str: ...
```

### `IInputController(ABC)`
```python
def click_element(self, element: UIElement, force_coordinate: bool = False) -> ActionResult: ...
def click_at(self, x: int, y: int, target_id: Optional[int] = None, target_name: Optional[str] = None) -> ActionResult: ...
def set_element_value(self, element: UIElement, text: str) -> ActionResult: ...
def paste_text(self, text: str) -> ActionResult: ...
def press_keys(self, *keys: str) -> ActionResult: ...
def scroll(self, clicks: int) -> ActionResult: ...
```

### `IVisualFallback(ABC)`
```python
def capture_fullscreen(self, save_path: Optional[str] = None) -> Image.Image: ...
def capture_window(self, window: WindowInfo, save_path: Optional[str] = None) -> Optional[Image.Image]: ...
def has_screen_changed(self, img: Image.Image) -> bool: ...
```

---

## 4. Platform Providers & Factory (`cu_suite.platforms`)

### Factory Methods
* `detect_platform() -> PlatformType`: Evaluates `platform.system()` and returns `WINDOWS`, `MACOS`, or `LINUX`.
* `get_window_manager(platform_override=None) -> IWindowManager`: Returns provider instance for host or specified OS.
* `get_tree_inspector(platform_override=None, max_depth=20, max_elements=150) -> ITreeInspector`: Returns tree inspector.
* `get_input_controller(platform_override=None, action_delay=0.2, human_mode=True) -> IInputController`: Returns input controller.
* `get_visual_fallback(platform_override=None) -> IVisualFallback`: Returns visual snapshot provider.

### Platform Provider Matrix
| OS Target | Window Manager | Tree Inspector | Input Controller | Visual Fallback |
| :--- | :--- | :--- | :--- | :--- |
| **Windows** | `WindowsWindowManager` (Win32 DPI-aware `user32` + UIA) | `WindowsTreeInspector` (UIA v3 COM + `RootWebArea` fast-path) | `WindowsInputController` (Human Bézier + SendInput + Clipboard) | `WindowsVisualFallback` (Pillow + SHA256 diff) |
| **macOS** | `MacOSWindowManager` (Quartz `CGWindowList` + `NSWorkspace`) | `MacOSTreeInspector` (`AXUIElement` + role translation) | `MacOSInputController` (`Command` key map + Human Bézier) | `MacOSVisualFallback` (Pillow / screencapture) |
| **Linux** | `LinuxWindowManager` (X11 / `wmctrl` / EWMH) | `LinuxTreeInspector` (`AT-SPI2` via D-Bus / `pyatspi`) | `LinuxInputController` (Human Bézier + `Ctrl+V` / xclip) | `LinuxVisualFallback` (Pillow / scrot / grim) |

---

## 5. Human Kinematics Engine (`cu_suite.human_kinematics`)

### `generate_human_path(start, target, steps=35, deviation=0.25) -> List[Tuple[int, int]]`
Generates a realistic curved mouse trajectory between two points:
* Computes perpendicular normal vector to straight trajectory.
* Generates randomized cubic Bézier control points at 33% and 66% of the vector.
* Evaluates trajectory along sinusoidal minimum-jerk acceleration and deceleration easing curves.
* Injects micro-tremor noise that naturally decays upon approaching the target.

### `HumanKinematics`
* `move_to(target_x, target_y, duration_range=(0.25, 0.45))`: Moves cursor along human Bézier curve.
* `human_click(target_x, target_y)`:
  1. Applies ±2px sub-pixel landing jitter.
  2. Moves cursor via `move_to()`.
  3. Pauses for pre-click hover hesitation (60–140ms).
  4. Presses `mouseDown()`, holds for variable dwell (45–95ms), releases `mouseUp()`.
  5. Settles for post-click stabilization (50–120ms).

---

## 6. Browser Autofill Handler (`cu_suite.autofill`)

### `AutofillHandler(input_controller)`
Automates native floating browser credential dropdowns (Chromium / Brave / Edge password popups):
* `select_autofill_credential(trigger_coord=None, target_element=None, credential_index=1, submit=True, submit_coord=None, submit_delay=0.5) -> ActionResult`
  * Clicks target input to trigger browser password popup.
  * Sends `Down Arrow` `credential_index` times to highlight saved account.
  * Sends `Enter` to apply credentials into username and password fields.
  * Submits form via button click or Enter.

---

## 7. High-Level Facade (`cu_suite.ComputerUseSuite`)

The primary developer entry point aggregating all components:

```python
from cu_suite import ComputerUseSuite, PlatformType

suite = ComputerUseSuite(
    platform_override=None,   # Optional: PlatformType.WINDOWS / MACOS / LINUX
    max_depth=20,             # Max A11y tree recursion depth
    max_elements=150,         # Element cap to protect LLM context windows
    action_delay=0.2,         # Delay between actions in seconds
    human_mode=True           # Enable anti-bot Bézier kinematics
)
```

### Methods Summary
* `list_windows() -> List[WindowInfo]`: Lists open desktop windows.
* `focus_window(query: str) -> Optional[WindowInfo]`: Finds and activates window by title substring or regex.
* `inspect(focus_document: bool = True) -> str`: Returns formatted compact text tree of active window. Fast-paths to web DOM if browser.
* `get_elements() -> List[UIElement]`: Returns list of currently indexed `UIElement` instances.
* `find_elements(name_pattern: str, control_type: Optional[str] = None) -> List[UIElement]`: Searches indexed elements by regex.
* `click_id(elem_id: int) -> ActionResult`: Clicks element by its numeric index `[1]`, `[2]`, etc.
* `click_relative(rel_x: int, rel_y: int, window: Optional[WindowInfo] = None) -> ActionResult`: Clicks at offset relative to window top-left.
* `click_percentage(pct_x: float, pct_y: float, window: Optional[WindowInfo] = None) -> ActionResult`: Clicks at percentage position (0.0–1.0).
* `set_value_id(elem_id: int, text: str) -> ActionResult`: Sets element value via ValuePattern or clipboard paste.
* `navigate_browser(url: str, wait_seconds: float = 3.0) -> ActionResult`: Dispatches cross-platform address bar focus (`Ctrl+L` / `Command+L`), pastes URL, presses Enter, and re-inspects DOM.
* `login_with_autofill(rel_trigger_coord=(486, 347), credential_index=1, rel_submit_coord=(486, 445), wait_seconds=3.0) -> ActionResult`: Executes credential autofill sequence.
* `capture_snapshot(path: str) -> bool`: Saves targeted window or desktop image.
