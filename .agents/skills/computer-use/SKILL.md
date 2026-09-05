---
name: computer-use
description: Cross-platform desktop and browser automation skill using AXIS (axis-computer-use), featuring semantic accessibility trees (A11y), anti-bot human kinematics, layout-safe text injection, and visual fallback.
---

# AXIS Computer Use Skill Guide

This skill guides autonomous agents in performing desktop and browser automation reliably across Windows, macOS, and Linux using the **AXIS** (`axis-computer-use` / `cu_suite`) framework.

> *"Action is the Evidence."*

---

## 1. Core Operating Principles

When instructed to interact with desktop applications or web pages:
1. **Never guess coordinates blindly.** Always inspect the native accessibility tree (`suite.inspect()`) first to identify controls, roles, and exact bounding boxes.
2. **Use Semantic Targets First.** Interact by numeric Element ID (`suite.click_id(4)`) or accessibility patterns (`Invoke`, `Value`) rather than raw screen clicking whenever available.
3. **Handle Non-US Keyboard Layouts via Clipboard.** Standard typing (`pyautogui.write()`) corrupts symbols (e.g. `:`, `/`, `@`, numbers) on French/Belgian AZERTY and German QWERTZ keyboards. Use `suite.input.paste_text(url)` or clipboard pasting by default.
4. **Bypass Anti-Bot Detection with Kinematics.** When interacting with CAPTCHAs, verification forms, or bot-sensitive applications, set `human_mode=True` to dispatch non-linear cubic Bézier mouse paths, variable pre-click dwell times (60–140ms), and natural mouse hold durations (45–95ms).
5. **Fall Back to Virtual Keystrokes for Anti-Paste Forms.** When forms implement `onpaste="return false;"`, fall back to character-by-character virtual typing (`pyautogui.write(text, interval=0.08)`).
6. **Resolve Browser Password Popups.** When opening login forms with saved credentials, do not press Enter blindly (which submits blank fields). Use `suite.login_with_autofill()`.

---

## 2. Standard Automation Procedures

### Step 1: Pre-Flight & Window Activation
Find and bring the target application to the foreground:
```python
from cu_suite import ComputerUseSuite

suite = ComputerUseSuite(human_mode=True)

# Find by substring or regex
win = suite.focus_window("Brave")
if not win:
    raise RuntimeError("Target window not found")
```

### Step 2: Semantic UI Inspection
Retrieve the structured accessibility tree:
```python
# Returns token-efficient YAML representation:
# [id] Role "Name" val="value" bbox=(x,y,w,h)
tree_text = suite.inspect()
print(tree_text)
```
*Note: For Chromium browsers (Chrome, Brave, Edge), `suite.inspect()` automatically fast-paths to the active `RootWebArea`, bypassing native browser toolbar and tab chrome buttons.*

### Step 3: Action Execution
Dispatch targeted actions:
```python
# Option A: Click by indexed ID
suite.click_id(4)

# Option B: Humanized coordinate click
suite.input.click_at(1307, 588)

# Option C: Relative offset within active window
suite.click_relative(486, 347)
```

### Step 4: Browser Navigation
Navigate browsers cleanly with platform key translation (`Command+L` on Mac, `Ctrl+L` on Windows/Linux):
```python
suite.navigate_browser("https://home.azzouz.be", wait_seconds=3.0)
```

### Step 5: Password Autofill Resolution
Log in using browser-saved credentials:
```python
suite.login_with_autofill(
    rel_trigger_coord=(486, 347),  # Relative coordinate of username input
    credential_index=1,           # First saved account
    rel_submit_coord=(486, 445),   # Relative coordinate of submit button
    wait_seconds=3.0
)
```

### Step 6: Targeted Visual Snapshot & Verification
Verify visual outcomes using bounding-box snapshots and multimodal inspection:
```python
# Capture active window bounds only
suite.capture_snapshot("step_verification.png")

# Use explain_media tool on step_verification.png to inspect visual confirmation
```

---

## 3. Platform Specifics & Permissions

* **Windows:**
  * Requires interactive desktop session (Session 1).
  * If automating elevated (Administrator) windows, ensure the executing terminal/Python process is also elevated to satisfy UIPI (User Interface Privilege Isolation).
* **macOS:**
  * Uses `AXUIElement` for accessibility and `Quartz` for windowing.
  * Translates `Ctrl` to `Command` (`Cmd+L`, `Cmd+V`, `Cmd+A`).
  * Requires `Accessibility` and `Screen Recording` permissions granted in System Settings.
* **Linux:**
  * Uses `AT-SPI2` over D-Bus for accessibility.
  * Uses `wmctrl` and `xdotool` on X11 / XWayland.
