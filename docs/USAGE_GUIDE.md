# AXIS usage guide

This guide uses distribution **0.1.0 alpha** and API contract **2.0**. AXIS
requires a resident authorized host for desktop operations. The examples use
Windows PowerShell and Notepad; replace the application with one explicitly
allowed by the operator.

## 1. Install and start the host

```powershell
python -m pip install "axis-computer-use[windows] @ https://github.com/IsmailAzzouz/axis-computer-use/releases/download/v0.1.0/axis_computer_use-0.1.0-py3-none-any.whl"
$env:AXIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
axis serve --journal axis-v2.sqlite3 --allow-app notepad
```

This installs the wheel attached to the [v0.1.0 GitHub release](https://github.com/IsmailAzzouz/axis-computer-use/releases/tag/v0.1.0), including its Windows extra.

Keep the host running. Start an MCP client adapter in another process with the
same environment:

```powershell
axis-mcp --port 8769
```

For source checkout installation, Codex configuration, and standalone MCP mode,
see [migration and setup](AXIS_V2_MIGRATION.md). Do not expose the token in
model-visible messages or request data.

## 2. Discover and observe

The MCP interface has six tools: `axis.help`, `axis.targets`, `axis.observe`,
`axis.run`, `axis.job`, and `axis.capture`. Begin with `axis.help({})`, then use
`axis.targets({})` to select an authorized `target_id`. Observe it:

```json
{"target_id":"TARGET_ID"}
```

The `axis.observe` response supplies a `session_id` and current element data.
Use observed names or references and check host capabilities before planning.

## 3. Submit one plan

Place each action in an ordered `steps` array. This example types into a uniquely
matching edit control and asks AXIS to verify its value:

```json
{
  "session_id": "SESSION_FROM_OBSERVE",
  "idempotency_key": "type-note-001",
  "steps": [
    {"id":"focus","op":"focus"},
    {
      "id":"write",
      "op":"type_text",
      "args":{"at":{"selector":{"role":"Edit","name":"Input"}},"text":"Hello","replace":true},
      "postcondition":{"kind":"value","selector":{"role":"Edit","name":"Input"},"expected":"Hello"}
    },
    {"id":"read","op":"observe","args":{"query":{"role":"Edit"}}}
  ]
}
```

Send this as one `axis.run` request. Replace the session and selector with values
from the current observation. Get exact operation arguments with
`axis.help({"action":"type_text"})`. Use a fresh idempotency key for each new
plan; retain the original request and key for recovery.

## 4. Check results and recover carefully

Inspect every step's `verification`, the overall status, and
`effects_verified`. A `dispatch_only` step is explicitly unverified. For a
running job, query `axis.job` by its `job_id`. If a response is lost or the
outcome is unknown, query by the original `idempotency_key` before submitting
anything else. Never treat a timeout or cancellation as proof that no effect
occurred.

Use `axis.capture` only when semantic observation is insufficient. An image or
successful tool listing does not certify the action effect or native behavior.
For detailed limits and qualification status, see the
[V2 API](AXIS_V2_API.md) and [qualification record](AXIS_V2_QUALIFICATION.md).
