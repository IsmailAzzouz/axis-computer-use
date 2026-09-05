# Computer Use Suite (`cu_suite`) Practical Usage Guide

This guide provides practical workflows, code snippets, and best practices for automating desktop applications and web browsers across platforms using `cu_suite`.

---

## 1. Installation & Environment Setup

### Windows
```bash
python -m pip install --user uiautomation comtypes pyautogui pyperclip pillow
```
*Note: Ensure your Python terminal is running in the interactive desktop session (Session 1). If controlling applications running with Administrator privileges, launch the terminal as Administrator to satisfy Windows UIPI (User Interface Privilege Isolation).*

### macOS
```bash
pip install pyobjc-framework-Quartz pyobjc-framework-ApplicationServices pyautogui pyperclip pillow
```
*Note: Ensure Terminal / Python has been granted `Accessibility` and `Screen Recording` permissions in **System Settings → Privacy & Security**.*

### Linux
```bash
sudo apt-get install wmctrl xdotool xclip
pip install pyatspi pyautogui pyperclip pillow python-xlib
```

---

## 2. Quickstart: The 30-Second Example

```python
from cu_suite import ComputerUseSuite

# Initialize suite with human-like kinematics enabled
suite = ComputerUseSuite(human_mode=True)

# 1. Discover and focus an application window
win = suite.focus_window("Brave")
print(f"Focused: {win.title} (HWND: {win.handle})")

# 2. Inspect the UI tree
tree_text = suite.inspect()
print(tree_text)

# 3. Click an interactive element by ID
res = suite.click_id(4)
print(f"Click status: {res.success}")
```

---

## 3. Core Workflows

### A. Window Management
```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite()

# List all visible windows
windows = suite.list_windows()
for w in windows:
    active_flag = " [ACTIVE]" if w.is_active else ""
    print(f"[{w.handle}] \"{w.title}\" PID={w.process_id}{active_flag}")

# Find by substring or regex
chrome_win = suite.focus_window("Google Chrome")
discord_win = suite.focus_window("Discord.*general", regex=True)
```

---

### B. Browser Navigation & Web DOM Piercing
Chromium-based browsers (Brave, Chrome, Edge) nest web contents under deep native view layers. `cu_suite` automatically fast-paths to the active web DOM (`AutomationId="RootWebArea"`), filtering out hundreds of window frame buttons.

```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite()
suite.focus_window("Brave")

# Navigates address bar (Ctrl+L on Win/Linux, Cmd+L on macOS) and waits for load
suite.navigate_browser("https://home.azzouz.be", wait_seconds=3.0)

# Inspect directly returns web DOM nodes
print(suite.inspect())
```

Example Output:
```yaml
=== Active Window: Toolbox - Brave (12 elements) ===
  [1] Document "Toolbox" val="https://home.azzouz.be/" bbox=(955,116,957x908) [FOCUSED]
  [2] Button "Proxmox" bbox=(1012,310,180x90)
  [3] Button "Jellyfin" bbox=(1220,310,180x90)
  [4] Button "Torrent" bbox=(1436,437,180x90)
```

---

### C. Safe Text Typing (Anti-AZERTY & Anti-Bot)

International keyboard layouts (e.g., Belgian/French AZERTY) corrupt standard scan codes (e.g. `:` becoming `shift+/`, `@` requiring `AltGr`). Furthermore, anti-bot forms frequently block clipboard paste (`onpaste="return false;"`).

`cu_suite` handles this transparently:

```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite()

# 1. Standard Safe Input (Clipboard-based, bypasses layout corruption)
suite.input.paste_text("https://subdomain.example.com/login?token=abc")

# 2. Virtual Keystroke Fallback (When onpaste is blocked by anti-bot scripts)
# Clicks the field and types character-by-character with natural timing jitter
suite.click_id(6)
import pyautogui
pyautogui.write("my_secret_token", interval=0.08)
```

---

### D. Browser Password Autofill Resolution

When opening a login page with saved browser credentials, clicking the username field triggers a floating browser popup. Blindly pressing Enter submits blank fields. Use `login_with_autofill`:

```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite()
suite.focus_window("qBittorrent")

# Triggers credential popup on username box, selects account index 1 (admin), and submits
res = suite.login_with_autofill(
    rel_trigger_coord=(486, 347),  # Username field relative to window
    credential_index=1,           # 1 for first saved credential
    rel_submit_coord=(486, 445),   # Login button relative to window
    wait_seconds=3.0
)
print("Autofill login result:", res.success)
```

---

### E. Anti-Bot Kinematics & Humanized Clicking

Automated coordinate jumps in 0ms trigger velocity/acceleration checks on modern anti-bot systems (e.g., Turnstile, reCAPTCHA, CAPTCHA games).

Enable `human_mode=True` to route clicks through the cubic Bézier trajectory engine:

```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite(human_mode=True)

# 1. Humanized click on an element by ID
# Generates curved path, adds ±2px jitter, hovers 60-140ms, holds mouse down 45-95ms
suite.click_id(3)

# 2. Humanized coordinate click
suite.input.click_at(1307, 588)

# 3. Custom path control
from cu_suite.human_kinematics import HumanKinematics
kinematics = HumanKinematics()
kinematics.move_to(1200, 600, duration_range=(0.3, 0.5))
```

---

### F. Targeted Visual Snapshots & Change Detection

Avoid sending full-screen 4K/1080p images to vision models when only a small window or region changed:

```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite()
win = suite.focus_window("World's Hardest CAPTCHA")

# Saves cropped window bounds instead of full desktop
suite.capture_snapshot("active_window.png")

# Change detection comparison
current_img = suite.visual.capture_fullscreen()
if suite.visual.has_screen_changed(current_img):
    print("Screen state changed - invoking visual inspection")
else:
    print("Screen state unchanged - skipping vision call")
```

---

### G. Cross-Platform Runtime Testing

You can instantiate specific platform backends on any host for development and testing:

```python
from cu_suite import ComputerUseSuite, PlatformType

# Force macOS backend
suite_mac = ComputerUseSuite(platform_override=PlatformType.MACOS)
print("Mac address bar hotkey:", suite_mac.platform)

# Force Linux backend
suite_linux = ComputerUseSuite(platform_override=PlatformType.LINUX)
print("Linux window manager:", type(suite_linux.wm))
```

---

## 4. Standalone CLI Usage

The suite includes an interactive command-line interface:

```bash
# List all desktop windows
python -m cu_suite.cli list-windows

# Inspect UI tree of a specific window
python -m cu_suite.cli inspect --window "Brave"

# Navigate a browser window to a URL
python -m cu_suite.cli navigate "https://home.azzouz.be" --window "Brave"
```
