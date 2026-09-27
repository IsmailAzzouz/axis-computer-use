---
name: computer-use
description: Use AXIS MCP to operate desktop apps, Excel, browsers and calibrated games. Text first; several actions per call.
---

# AXIS — small guide

New here? `axis.help({})`. Need action args? `axis.help({"action":"click"})`.
Use AXIS tools, not another computer-use implementation.

1. `axis.targets({})` → pick allowed target_id. Same title? Check identity.
2. `axis.observe({"target_id":"..."})` → keep session_id + element names.
3. `axis.run` → many steps, one call. Replace SESSION/Input below with observed values. Fresh key per NEW plan.

```json
{
  "session_id": "SESSION",
  "idempotency_key": "edit-001",
  "steps": [
    {"id":"focus","op":"focus"},
    {"id":"write","op":"type_text","args":{"at":{"selector":{"name":"Input"}},"text":"Hello","replace":true},"postcondition":{"kind":"value","selector":{"name":"Input"},"expected":"Hello"}},
    {"id":"read","op":"observe"}
  ]
}
```

Sent ≠ verified. Check steps + effects_verified. `dispatch_only` means unverified input, not task success.
Lost reply/unknown? `axis.job({"idempotency_key":"ORIGINAL-KEY","action":"result"})`. Never retry with new key.
Job running? Read job. More pages? Follow next_cursor. Cancel stops future work, not undo.

Text first. `axis.capture` only when needed. Use observed IDs; never guess coordinates.
New app? `axis.help({"topic":"run"})`. Games? `axis.help({"topic":"actions"})`; calibration needed, no video.
Error? `axis.help({"topic":"errors"})`. Host missing/focus denied/desktop locked? Ask operator; no bypass.
Help works offline. Does not prove desktop ready. Save dialog never means permission to force-close.
