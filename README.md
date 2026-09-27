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

### Quickstart: one-process MCP

For the quickest broad-access MCP setup, run:

```powershell
axis-mcp --allow-all --journal axis-v2.sqlite3
```

Configure your MCP client to launch `axis-mcp` with arguments
`["--allow-all", "--journal", "axis-v2.sqlite3"]`. The adapter runs the
runtime in-process over MCP stdio; it does not connect to a TCP broker and does
not require `AXIS_TOKEN`. `--allow-all` permits all apps, window mutation, and
app termination. The journal stores request and effect records for recovery; it
is not an access-control setting.

### Two-process broker (optional)

Use a separate resident host when multiple clients or the Python SDK should share
one runtime. In PowerShell, create a random token of at least 32 characters and
start the host:

```powershell
$env:AXIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
axis serve --journal axis-v2.sqlite3 --allow-app notepad
```

In another process that inherits the same `AXIS_TOKEN`, launch `axis-mcp` with
`["--port", "8769"]`. PowerShell environment variables set with `$env:` are
inherited by child processes, but separately launched terminals/processes do not
automatically share later changes; set the variable in each process environment
or launch the client as a child of the host's environment. The broker token
authenticates access to the host. It does not grant desktop permissions: the
host's policy flags do that. The host requires a random token of at least 32
characters (up to 4096); the default environment variable is `AXIS_TOKEN`, or
select another name with `--token-env` on both host and adapter. Keep the token
out of prompts, request JSON, and source control. Installing AXIS alone
authorizes no applications.

For a restricted standalone adapter, for example, use
`axis-mcp --standalone --journal axis-v2.sqlite3 --allow-app notepad`. This
permits AXIS to launch Notepad and authorizes the target it creates; it does not
automatically authorize already-open Notepad windows. To authorize an existing
window, specify its ID with `--allow-target`; `--read-all` permits discovery and
observation of otherwise unauthorized targets but does not permit mutations on
them. See
[client setup and migration](docs/AXIS_V2_MIGRATION.md) for checkout, SDK, and
MCP client configuration.

### CLI arguments

`axis` accepts the two global options before its subcommand. `axis-mcp` is a
dedicated MCP entrypoint: it accepts the MCP startup and policy options below,
but not the `axis` utility subcommands.

| Argument | Applies to | Meaning |
| --- | --- | --- |
| `--port PORT` | `axis` global; `axis-mcp` | Loopback broker port; default `8769`. Set the same value for host and broker-connected adapter. |
| `--token-env NAME` | `axis` global; `axis-mcp` | Local environment variable holding the broker token; default `AXIS_TOKEN`. Host and client must use the same token value. |
| `--help` | `axis`, `axis-mcp` | Show command or entrypoint usage and exit. |

`axis serve` starts the resident runtime and authenticated loopback broker.
These flags follow `serve`:

| Argument | Meaning |
| --- | --- |
| `--journal PATH` | Required SQLite journal path used for request idempotency and effect recovery. |
| `--allow-app APP` | Permit AXIS to launch the named app with `open_app`; repeat for multiple apps. The created target is authorized, but existing windows of that app are not automatically authorized. |
| `--allow-target ID` | Authorize the named existing target for operations; repeat for multiple targets. |
| `--read-all` | Permit discovery and observation of otherwise unauthorized targets; it does not grant mutation authority over them. |
| `--allow-terminate` | Permit application termination. This does not itself grant access to a target. |
| `--allow-all` | Permit all apps, window mutation, and termination; implies broad reading and target access. |
| `--max-connections N` | Maximum simultaneous broker connections; default `16`. |
| `--max-calls N` | Maximum concurrent normal tool calls; default `8`. Control calls have a separate pool. |
| `--control-calls N` | Concurrent-call slots reserved for control calls such as `axis.job`; default `2`. |
| `--request-timeout SECONDS` | Total deadline for receiving an incoming frame; default `5`. |
| `--response-timeout SECONDS` | Total deadline for writing a response; default `5`. |

`axis-mcp` runs the stdio MCP adapter. Its policy options match the host policy
above (`--allow-app`, `--allow-target`, `--read-all`, `--allow-terminate`, and
`--allow-all`), with the same meanings; they apply locally only when standalone
mode is selected. `--port` and `--token-env` apply only when connecting to the
broker and are unused in standalone mode. Other startup options are:

| Argument | Meaning |
| --- | --- |
| `--standalone` | Create and own a runtime inside the adapter process, without a broker token. |
| `--journal PATH` | Standalone SQLite journal path; default `axis-v2.sqlite3`. Ignored when connected to a separate broker. |
| `--max-calls N` | Maximum concurrent normal MCP tool calls; default `8`. Control calls have a separate pool. |
| `--control-calls N` | Concurrent-call slots reserved for `axis.job` and ping/control calls; default `2`. |

`--allow-all` and a true `AXIS_ALLOW_ALL` environment setting both select
standalone mode and enable the broad policy. `AXIS_ALLOW_ALL` accepts `1` or
`true`, case-insensitively. In broker mode, the policy belongs to `axis serve`;
adapter policy flags do not change the host's permissions.

Other `axis` subcommands are `safety`, `help`, `targets`, `observe`, `run`,
`job`, and `capture`. Each of the six tool subcommands (`help`, `targets`,
`observe`, `run`, `job`, and `capture`) accepts `--json OBJECT` for its
argument object; use `--json -` to read that JSON from stdin.

`axis safety` inspects and reconciles persistent native-input quarantine. Its
operator-only options are:

| Argument | Meaning |
| --- | --- |
| `--reconcile-owner OWNER` | Identify the quarantined input owner to reconcile. |
| `--confirm-inputs-released` | Confirm that held native inputs have been released. |
| `--confirm-clipboard-reviewed` | Confirm that clipboard state has been reviewed. |

Reconciling an owner requires both confirmation flags after the operator has
checked the inputs and clipboard. These utility commands are not MCP server
startup options.

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
