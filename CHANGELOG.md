# Changelog

## 0.1.0 — 2026-09-27 (alpha)

- Makes V2 the only implementation: removes the V1 facade, providers, native
  adapters, obsolete fixtures, and legacy documentation. Prior tracked versions
  remain available in Git history.
- Introduces the breaking AXIS v2 MCP, CLI, and SDK contract, including compact
  `axis.help` guidance and bounded multi-step runs.
- Adds a Windows-first runtime with target identity checks, action deadlines,
  cancellation cleanup, accessibility observations, and explicit effect status.
- Limits UI Automation root reacquisition to the exact
  `UIA_E_ELEMENTNOTAVAILABLE` failure, with a short bounded retry and no input
  replay. Other provider errors are surfaced directly.
- Documents that native app and model qualification is incomplete. This alpha
  is not certified for production; see `docs/AXIS_V2_QUALIFICATION.md`.

This release breaks compatibility with the earlier MCP, CLI, and SDK contracts.
Do not run old and new AXIS hosts against the same desktop session.
