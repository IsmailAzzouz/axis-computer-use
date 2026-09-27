# AXIS V2 setup and migration

Distribution version **0.1.0 alpha** implements JSON API contract version
**2.0**. The public MCP, CLI, and Python SDK use the V2 contract. V1 tool names
and call shapes are not supported.

## Public entrypoints

| Entry | Purpose |
| --- | --- |
| `axis`, `axis-cu`, `cu-suite`, `python -m cu_suite`, `python -m cu_suite.cli` | CLI |
| `axis-mcp`, `python -m cu_suite.mcp`, `python -m cu_suite.mcp.server` | MCP stdio adapter |
| `from cu_suite import AxisClient` | Authenticated broker SDK |

The six MCP tools are `axis.help`, `axis.targets`, `axis.observe`, `axis.run`,
`axis.job`, and `axis.capture`. Actions such as `click` are plan steps inside
`axis.run`. Start with `axis.help({})`; get operation arguments with
`axis.help({"action":"click"})`. Host capabilities are reported by
`axis.observe` with `scope: "capabilities"`.

## Install and launch on Windows

Download the wheel attached to the [v0.1.0 GitHub release](https://github.com/IsmailAzzouz/axis-computer-use/releases/tag/v0.1.0), then install it:

```powershell
python -m pip install "axis-computer-use[windows] @ https://github.com/IsmailAzzouz/axis-computer-use/releases/download/v0.1.0/axis_computer_use-0.1.0-py3-none-any.whl"
```

For development from a checkout:

```powershell
python -m pip install --no-build-isolation -e '.[windows]'
```

Set a random token and start a resident host with explicit app permissions:

```powershell
$env:AXIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
axis serve --journal axis-v2.sqlite3 --allow-app notepad
```

Start the MCP adapter in another process inheriting the token:

```powershell
axis-mcp --port 8769
```

The host owns permissions, sessions, and job recovery. Installing the package
does not grant desktop access. Do not put the token in model-visible messages or
request JSON. If a reply is lost after a request may have been sent, recover the
job with its original idempotency key; do not resubmit with a new key.

## Standalone MCP mode

An operator may instead run the host inside the MCP process:

```powershell
axis-mcp --standalone --journal C:\axis-data\runtime.sqlite3 --allow-app notepad
```

This mode uses the specified durable journal and ends when the MCP process exits.
Sessions do not persist across process exit; inspect/reconcile old jobs before
starting new work. Do not share one standalone journal between concurrent hosts.
`--allow-all` grants broad application, window mutation, and forced-termination
authority; use it only as an explicit operator policy choice.

## Codex MCP configuration

Configure the installed Python interpreter and ensure the Codex process inherits
`AXIS_TOKEN`:

```toml
[mcp_servers.axis]
command = 'C:\path\to\python.exe'
args = ['-m', 'cu_suite.mcp.server', '--port', '8769']
env_vars = ['AXIS_TOKEN']
startup_timeout_sec = 15
tool_timeout_sec = 75
```

After changing the process environment or server configuration, restart the MCP
client and check initialization, `tools/list`, and an authorized `axis.targets`
call. Tool discovery alone does not prove that desktop access is ready.

## Qualification status

This is an alpha release. Windows is the current target; macOS/Linux behavior,
complete native application coverage, and model usability are not qualified.
Simulated tests and tool discovery are not native certification. See the
[qualification record](AXIS_V2_QUALIFICATION.md) for the remaining evidence
gates and the [V2 API details](AXIS_V2_API.md) for runtime semantics.
