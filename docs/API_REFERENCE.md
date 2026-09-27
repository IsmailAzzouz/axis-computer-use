# AXIS API reference

AXIS distribution **0.1.0 alpha** implements JSON contract version **2.0**. The
public MCP surface contains six tools. This page is a compact index; the
[V2 API details](AXIS_V2_API.md) describe schemas, execution, recovery, and host
behavior.

## MCP tools

| Tool | Required input / purpose |
| --- | --- |
| `axis.help` | Optional `topic` or `action`; offline guide and examples |
| `axis.targets` | Optional pagination `cursor`; discover authorized targets |
| `axis.observe` | Target/session plus an optional scope, query, or action; read state and capabilities |
| `axis.run` | `session_id`, fresh `idempotency_key`, and ordered `steps` or a supported recipe |
| `axis.job` | `job_id` or original `idempotency_key`, plus `action` (`status`, `result`, or `cancel`) |
| `axis.capture` | `session_id`; optional region and `include_image` |

Action operations are expressed as `steps` in `axis.run`, not as standalone MCP
tools. Use `axis.help({"action":"click"})` for the exact current arguments.
Use `axis.observe` with `scope: "capabilities"` to discover operations
advertised by the connected host. Syntax does not guarantee a backend supports
an operation.

## Python SDK

```python
from cu_suite import AxisClient

client = AxisClient(token="<host token>", port=8769, timeout=15)
targets = client.targets()
```

`AxisClient` also provides `observe`, `run`, `job`, `capture`, and offline
`help` methods. The same tools are available through `client.call(name,
arguments)`. Supply the host token through the process environment in real
applications rather than embedding it in source.

## Result interpretation

Inspect the overall status, each step's verification, and `effects_verified`.
Dispatch confirms that input was sent; it does not prove the intended UI effect.
After an unknown response or lost acknowledgement, query `axis.job` with the
original idempotency key and inspect the result before making a new plan. A
cancel request stops future work where possible; it does not undo completed
effects.

## Host and client setup

See [installation and MCP configuration](AXIS_V2_MIGRATION.md), the
[usage guide](USAGE_GUIDE.md), and the detailed [V2 API](AXIS_V2_API.md).
