# AXIS Computer Use Roadmap

This document outlines the architectural milestones, platform testing goals, and feature pipeline for **AXIS** (`axis-computer-use` / `cu_suite`).

---

## 🎯 Phase 1: Core Engine & Windows Hardening (✅ Completed)
- [x] **Semantic Accessibility Engine (A11y):** Native Windows UI Automation v3 inspection with interactive control pruning (`[1]`, `[2]`, `[3]`).
- [x] **Chromium Web DOM Piercing:** Automated `AutomationId="RootWebArea"` fast-pathing to bypass 300+ native browser chrome buttons.
- [x] **Humanized Anti-Bot Kinematics:** Curved cubic Bézier mouse paths, minimum-jerk acceleration/deceleration, micro-tremor noise, and pre-click hover dwell times.
- [x] **International Keyboard Safety:** Layout-agnostic clipboard pasting (`Ctrl+V`) to defeat AZERTY/QWERTZ scan-code distortion.
- [x] **Anti-Paste Fallback:** Automatic character-by-character virtual typing fallback when forms enforce `onpaste="return false;"`.
- [x] **Browser Password Autofill:** Synthetic arrow-key dropdown navigation and submission for floating browser credential popups.
- [x] **Targeted Visual Fallback:** Bounded window screenshots with SHA-256 perceptual diff change detection.
- [x] **Platform Abstraction Layer (PAL):** Abstract Base Classes (`IWindowManager`, `ITreeInspector`, `IInputController`, `IVisualFallback`) with runtime factory dispatch.

---

## 🚀 Phase 2: Native Hardware Testing & Multi-OS Validation (🟡 In Progress)
- [ ] **macOS Physical Device Testing:**
  - [ ] Validate `pyobjc-framework-Quartz` window bounds under macOS Retina scaling.
  - [ ] Validate `AXUIElement` accessibility traversal across native macOS apps (Safari, Finder, Preview).
  - [ ] Test macOS TCC privacy dialog handling (`Accessibility` & `Screen Recording` permissions).
  - [ ] Verify `Command` key hotkey translation across macOS keyboard layouts.
- [ ] **Linux Hardware & Desktop Environment Testing:**
  - [ ] Verify `AT-SPI2` D-Bus accessibility tree walking on GNOME and KDE desktops.
  - [ ] Validate `wmctrl` / `xdotool` on X11 display servers.
  - [ ] Test Wayland native support using `xdg-desktop-portal` (`org.freedesktop.portal.RemoteDesktop`) and `/dev/uinput` (`ydotool`).
  - [ ] Implement `wl-copy` / `wl-paste` clipboard integration under pure Wayland sessions.

---

## ⚡ Phase 3: CDP & Browser Extension Bridge (🔵 Planned)
- [ ] **Native Chrome DevTools Protocol (CDP) Adapter:**
  - [ ] Direct WebSocket connection to Chromium browsers running with `--remote-debugging-port`.
  - [ ] Sub-millisecond DOM tree serialization without traversing OS window handle hierarchies.
  - [ ] Direct JavaScript evaluation (`Runtime.evaluate`) for programmatic form fills and button clicks.
- [ ] **Companion Browser Extension:**
  - [ ] Lightweight unpacked extension to bypass browser security sandbox restrictions for agent interactions.
  - [ ] Bidirectional event streaming for page navigation, network idle, and DOM mutations.

---

## 🧠 Phase 4: Dynamic Event Streams & Game Solvers (🔵 Planned)
- [ ] **Web Audio API Event Interception:**
  - [ ] Passive capture of synthesized oscillator frequencies (e.g. Simon-Says memory puzzles, audio CAPTCHAs).
- [ ] **Dynamic Mutation Observer:**
  - [ ] Real-time CSS and attribute change listener to detect fast visual flashes without high-frequency screenshot polling.
- [ ] **60 FPS Video / Canvas Pipeline:**
  - [ ] Direct GPU / Direct3D / Metal frame grabber for non-accessible canvas and OpenGL/Vulkan game surfaces.

---

## 🌐 Phase 5: Agent Ecosystem & MCP Tool Packaging (🔵 Planned)
- [ ] **Official Model Context Protocol (MCP) Server:**
  - [ ] Expose `cu_suite` tools (`inspect_screen`, `click_element_id`, `type_text`, `navigate_url`) via stdio/SSE MCP.
- [ ] **LangChain / AutoGen / CrewAI Connectors:**
  - [ ] Pre-packaged toolkits for major autonomous agent orchestration frameworks.
- [ ] **Multi-Monitor Coordinate Normalizer:**
  - [ ] Seamless virtual desktop coordinate translation across mixed-DPI multi-monitor configurations.
