<p align="center">
  <img src="assets/header.svg" width="100%" alt="AXIS — a monochrome technical header with a fine grid, framed hexagonal reticle, the motto ‘Action is the evidence,’ and verification-focused labels." />
</p>

# AXIS Computer Use

AXIS is a Windows-first computer-use runtime exposed through MCP and a Python
client. Its public interface is the V2 contract: distribution version **0.1.0
alpha**, API contract version **2.0**. Native desktop and model qualification is
still in progress; this release is not certified for general use.

## Install

```powershell
python -m pip install "axis-computer-use[windows] @ https://github.com/IsmailAzzouz/axis-computer-use/releases/download/v0.1.0/axis_computer_use-0.1.0-py3-none-any.whl"
```

This installs the wheel attached to the [v0.1.0 GitHub release](https://github.com/IsmailAzzouz/axis-computer-use/releases/tag/v0.1.0), including its Windows extra.

Create a random host token and start the resident host with only the applications
you intend to authorize:

```powershell
$env:AXIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
axis serve --journal axis-v2.sqlite3 --allow-app notepad
```

In another process that inherits `AXIS_TOKEN`, start the MCP adapter:

```powershell
axis-mcp --port 8769
```

The host owns application permissions and runtime state. Installing AXIS does not
authorize applications. Keep the token out of prompts, request JSON, and source
control. See [client setup and migration](docs/AXIS_V2_MIGRATION.md) for checkout,
SDK, and MCP client configuration.

## Six MCP tools

Start with `axis.help({})`. The six public tools are:

| Tool | Purpose |
| --- | --- |
| `axis.help` | Offline guide and copyable request examples |
| `axis.targets` | List authorized desktop targets |
| `axis.observe` | Read target state and available capabilities |
| `axis.run` | Submit an ordered action plan |
| `axis.job` | Read, recover, or cancel a submitted job |
| `axis.capture` | Request a targeted image when observation text is insufficient |

Actions such as click and text entry are steps inside `axis.run`; they are not
individual MCP tools. Check `axis.observe` capabilities and `axis.help` for the
current action arguments. A dispatched action is not necessarily a verified
effect: inspect step verification and resulting UI state. For uncertain or lost
responses, recover with the original idempotency key before submitting new work.

## Python client

```python
import os
from cu_suite import AxisClient

client = AxisClient(token=os.environ["AXIS_TOKEN"])
print(client.targets())
```

The client connects to the resident host on loopback port 8769 by default.
Observe a target to obtain a session, then submit a plan with a fresh
`idempotency_key`; see the [usage guide](docs/USAGE_GUIDE.md).

## Scope and qualification

This alpha targets Windows. macOS/Linux support and complete native desktop and
model qualification are not established. Simulated tests and tool discovery do
not certify behavior in Excel, Edge, or other live applications. See the
[qualification record](docs/AXIS_V2_QUALIFICATION.md) for evidence and open work.

## License

MIT. See [LICENSE](LICENSE).
