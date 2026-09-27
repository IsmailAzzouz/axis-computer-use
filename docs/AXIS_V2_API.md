# AXIS v2 development API

The public MCP/CLI/SDK entrypoints now use v2. `axis`, `axis-cu`, `cu-suite`,
`python -m cu_suite` and `python -m cu_suite.cli` share the CLI. `axis-mcp`,
`python -m cu_suite.mcp` and `python -m cu_suite.mcp.server` start its MCP adapter.
Explicit `cu_suite.v2` imports remain the same implementation, not another engine.
See [migration and client setup](AXIS_V2_MIGRATION.md). Version 0.1.0 is an alpha:
V1 internals are removed; native/model qualification remains open.

## Small-agent quickstart

Call `axis.help({})`: short English, minimal grammar, one copyable multi-step plan.
Replace its session and field placeholders with observed values. For exact action
arguments use `axis.help({"action":"click"})`; topics `run`, `actions`, `errors`
give only the requested details. Examples are returned as JSON data, not executed.
Common actions (`focus`, `click`, `type_text`, `paste_text`, `keys`, `scroll`,
`open_app`, `close_window`) include a complete `axis.run` call, not just an argument
schema. Copy `example.arguments`; replace placeholders from observations. The click
example verifies field focus only. Shortcut/scroll examples are explicitly
unverified; a following observation does not automatically certify their effects.

The same guide is available without a host through `axis help` or
`AxisClient.help()`. This does not grant desktop authority or prove host readiness.
Six tools now include this read-only help alongside the five runtime operations.

Host adapters must satisfy the [PAL contract](AXIS_V2_PAL.md). Malformed capability
declarations or missing advertised ports return `ADAPTER_CONTRACT_ERROR`; an
absent supported feature returns `CAPABILITY_UNAVAILABLE`. These are operator
configuration/backend issues, not reasons for a model to invent another backend.
MCP run schemas share definitions rather than repeat every field per operation;
strict per-operation validation, verification and idempotency remain unchanged.

Windows edit controls without ValuePattern/RangeValuePattern can expose their
exact text through UIA TextPattern (`value_source: uia_text_pattern`). This includes
Excel's in-progress cell/formula editors. Reads are bounded to 4096 UTF-16 units;
overflow returns `OBSERVATION_INCOMPLETE`, never a silently truncated value.
Password controls remain redacted. Document text is not treated as a scalar value.
In Excel, verify the formula-bar buffer after typing, then the cell value after
Enter; typing alone does not commit a cell or prove that a workbook was saved.

Selection is separate from keyboard focus. Elements may expose `selected` as
true/false; absent/null means unavailable, not false. The portable predicate
`{"kind":"selected","selector":{"automation_id":"A1"},"expected":true}`
can verify selection through `await` or a postcondition. An unavailable state
returns `UNOBSERVABLE`; selection changes appear in semantic diffs. Checking a
few selected cells does not prove the complete selection of a whole worksheet.

## Start the host once

The host chooses allowed applications, target identities and optional forced-
termination authority. A model cannot change them through tool arguments.

### Plan and step budgets

`axis.run.timeout` bounds execution (default 60 seconds, capped by host policy).
Each step has a `timeout` (default 10 seconds), starting before target binding.
It includes selector resolution, preconditions, input and verification. Nested
`if`/`repeat` steps and temporal replay clicks inherit the parent's remaining
budget; they do not each receive a fresh parent timeout. Operation-specific
`await`/`await_visual` timeouts and `watch.duration` may shorten it further.

The runner checks again after provider reads and before native dispatch. A late
positive observation is not accepted as an on-time result. A known input ACK
remains `sent` on timeout or cancellation; an acknowledged launch retains its
returned target for reconciliation. Never assume timeout means nothing happened.
Read `axis.job` with the original key before deciding what to do next.

These are runner admission/verification budgets, not a hard real-time guarantee:
an in-flight native call and mandatory input cleanup can outlast them. Worker
admission now shares the original absolute deadline. The Windows adapter checks
its remaining action budget/cancellation before new input batches, pointer moves,
window mutations, process launch/termination and slider writes. Key/button release
and clipboard rollback/restoration are cleanup, and remain allowed after expiry.
Clipboard preparation rechecks immediately before its first write. These guards
have isolated adapter-logic tests; live native qualification remains separate.

```powershell
$env:AXIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
python -m cu_suite.v2.cli serve --journal output/axis-v2-runtime.sqlite3 --read-all --allow-app notepad
```

`--read-all` permits discovery/observation, not mutation of all existing windows.
Launched authorized applications and explicitly `--allow-target`-bound windows
can receive input. Their native-owned dialogs/menus inherit scoped permission;
unrelated windows sharing a process do not. Allowing an interpreter as an app is
broad launch authority and should be limited to trusted test hosts.

Other clients must inherit the same token and connect to the same broker port.
The token is never printed or stored by AXIS. Do not put it in model-visible JSON.

### Persistent Windows input quarantine (operator only)

Windows arms a durable input-ownership marker before granting its native lease.
It clears the marker only after key/button release and clipboard reconciliation.
The marker is independent of the run journal, shared by AXIS processes for the
same Windows session/desktop, and stored under
`%LOCALAPPDATA%/AXIS/v2/desktop-safety.sqlite3`. Changing `--journal` or restarting
does not clear it. An abandoned native mutex also arms the quarantine.

After a crash, even confirmed emergency release does not automatically clear this
marker. Stop the old host/worker, reconcile its effects with `axis.job`, manually
ensure all inputs are released, and review/set the desired clipboard state.
Then the operator can inspect and acknowledge the exact owner:

```powershell
axis safety
axis safety --reconcile-owner OWNER_FROM_STATUS --confirm-inputs-released --confirm-clipboard-reviewed
```

The second command refuses while the input mutex is held, any key/button is down,
or the owner differs. It records an acknowledgement, sends no input, does not
restore lost clipboard content, undo task effects, or replay anything. Restart
the authorized host afterwards if its in-memory safety interlock is still set.
There is no MCP/SDK action for clearing quarantine. Models must ask the operator.
Do not delete the safety database or change its environment path to bypass it.
Stop old pre-marker AXIS builds before upgrading; mixed versions are not certified.

### Transport admission and deadlines

The host defaults to 16 accepted TCP connections, 8 concurrent ordinary calls and
2 reserved `axis.job` calls. MCP stdio independently admits 8 ordinary calls and
2 reserved job/ping calls, with no waiting action queue. Overload is
`RESOURCE_LIMIT/not_sent` when its rejection reaches the client. If the connection
is lost instead, the client remains conservative: reconcile an unknown run using
its original idempotency key. Disconnecting never cancels or replays submitted work.

```powershell
python -m cu_suite.v2.cli serve --journal output/axis-v2-runtime.sqlite3 --allow-app notepad --max-connections 16 --max-calls 8 --control-calls 2 --request-timeout 5 --response-timeout 5
python -m cu_suite.v2.cli mcp --max-calls 8 --control-calls 2
```

Concurrency settings accept integers 1–256; timeouts must be finite, positive,
and at most 3600 seconds. Keep connection capacity above ordinary-call capacity
to leave room for control requests. Reserved execution capacity does not make the
service immune to unauthenticated clients occupying every connection.

Incoming broker frames have a **total** 5-second read deadline, not a timeout
reset by each arriving byte; response writes have a separate 5-second deadline.
The SDK's default 15-second budget covers connect/send/read together. Worker RPC
admission counts toward its deadline: expiry before submission reports
`WORKER_BUSY/not_sent` without killing the occupied worker. Cancellation uses the
existing out-of-band worker signal.

For dispatch, the supervisor sends the original monotonic deadline through its
private local-process channel. The child rejects expired/cancelled actions before
calling the adapter, which receives only the remaining duration. The 0.5-second
response grace is reserved for ACK/cleanup, not lock admission or new execution.
Queued ownership reports are drained after a stopped worker exits, before any
emergency release. Incomplete/excessive backlog keeps cleanup unconfirmed and
blocks new actions; it never authorizes a replay.

Private pipe send/full-frame receive now use a bounded wait around one tracked I/O
operation per channel. Readiness alone is not treated as a complete response.
Timeout stops the worker; an outstanding receive's result is retained for draining
ownership reports, not abandoned or replaced by a racing reader. Drain waiting has
one total 1-second budget; incomplete cleanup stays explicitly unconfirmed.
Frames are limited to 64 MiB for local raw images/clipboard data. Pickle stays on
the trusted inherited process pipe; public MCP/CLI/broker data remains JSON.
This bounds I/O waiting, not CPU serialization, OS scheduling, arbitrary native
calls or mandatory cleanup time. There is no hard real-time guarantee.

JSON requests are bounded to 256 KiB before parsing (including CLI stdin), depth
64, UTF-8 only, with duplicate fields and non-finite values rejected. Default
CLI/MCP stdio bypasses locale-dependent text decoding so Unicode does not depend
on the Windows console encoding. Broker and
MCP frames are bounded to 32 MiB including explicit images; normal text pages
still have the separate 12 KiB limit. An undeliverable post-dispatch response must
not be interpreted as an action that never happened. An oversized MCP input line
closes that stdio stream instead of interpreting its remaining bytes as commands.

Broker shutdown disconnects sockets and drains admitted handlers before the host
closes its runtime; it does not undo submitted jobs. Native runtime/worker bounds
still govern execution duration. Standard-output backpressure may block a stdio
writer, but does not create an unbounded response queue. Reconnect to the resident
broker and recover durable jobs if the stdio connection becomes unusable.

```powershell
python -m cu_suite.v2.cli targets
python -m cu_suite.v2.cli mcp
```

## Five tools

`axis.targets`, `axis.observe`, `axis.run`, `axis.job`, `axis.capture` are shared by
MCP, SDK and CLI. MCP `tools/list` returns their canonical JSON Schema.
`axis.observe` with `scope: capabilities` lists operations; add `action: click`
(or another operation name) to retrieve its argument schema without a large dump.

```python
import os
from cu_suite import AxisClient

client = AxisClient(token=os.environ['AXIS_TOKEN'])
desktop = client.observe()['session_id']
result = client.run(
    session_id=desktop,
    idempotency_key='open-notepad-001',
    steps=[
        {'id': 'open', 'op': 'open_app', 'args': {'app': 'notepad'}},
        {'id': 'focus', 'op': 'focus', 'target_from': 'open'},
    ],
)
```

Opening never selects an unrelated newly appearing window. A launcher that does
not yield a uniquely bound window reports `LAUNCH_UNRESOLVED`: inspect targets,
do not blindly launch again. This case still needs expanded app-specific testing.

Observe the resulting target, then use exact semantic selectors or returned
opaque refs. Two matching labels are ambiguous, not a reason to click the first.
`type_text` injects Unicode without using the clipboard. `paste_text` keeps a
clipboard lease until the plan's verification finishes and refuses unsupported
clipboard formats; no implicit Unicode fallback after a possibly sent paste.
Unsupported clipboard formats are detected before clicking/selecting in the UI.

Use `observe(query={"role": "Edit"})` for a targeted accessibility read. The Windows
adapter filters natively inside the authorized window and its owned dialogs.
The plan operation also accepts `{"op":"observe","id":"read","args":{"query":{"role":"Edit"}}}`.
Its result includes the immutable, redacted first snapshot page in the same
`axis.run` / `axis.job` response when retained in memory. Large readbacks follow
normal result pagination; the step's `output.cursor` can also retrieve the original
snapshot through `axis.observe` with `output.session_id`, without a new UI read.
These steps reuse the original window session or a job-scoped child session after
`target_from`, rather than creating a new session for every read.

Only opaque observation references are journaled. After cache eviction or host
restart, historical step completion remains queryable but `output.data_state` is
`unavailable` with reason `OBSERVATION_EXPIRED`, not an empty tree or a fresh read.
Continuing JSON/item fragments of an expired readback fails explicitly with
`OBSERVATION_EXPIRED`, so fragments from different snapshot states are not mixed.
Other observation scopes remain top-level operations; consult the step schema.
Explicit postconditions on local/control steps (`observe`, `if`, `repeat`,
`await`, visual waits, calibration and watch) are verified as well. An unmet
condition stops the plan and records `unmet`; a provider failure is `unobservable`,
never a verified step. Readback timestamps and postcondition-evidence timestamps
are separate: later verification does not change the earlier immutable snapshot.

Complete query coverage is not complete window coverage; semantic diffs require
the same query. Returned refs retain that query when revalidated. A value/state
postcondition needs a unique match and complete query coverage, not just the first
match in a truncated tree.
The native worker revalidates semantic element bounds and hit-test ancestry before
clicking. `STALE_ELEMENT_GEOMETRY` or `TARGET_OCCLUDED` means the earlier position
must not be reused; observe/reconcile rather than retrying a possibly sent action.

`focus` defaults to `method: native`. If Windows denies it, the model can explicitly
request `method: caption_click`: AXIS requires an exposed point that Windows identifies
as the target's caption, performs one physical click and verifies foreground ownership.
This does not use Alt-key tricks or attach thread input, and never clicks an occluding
window. Custom/fullscreen windows without a confirmed caption may require user activation.
An accepted native activation is checked until the step deadline; its asynchronous
return is not treated as immediate success or rejection. If the effect remains
unverified, `EFFECT_UNKNOWN` requires observation/reconciliation, not another
activation request. A genuine native BOOL rejection returns `FOCUS_DENIED`.
Caption activation cannot guarantee exposing an occluded window: Windows can also
refuse the requested Z-order change when foreground permission is absent.

`maximize_window`, `minimize_window`, and `restore_window` verify the actual window
state; restore explicitly requests normal bounds. Focusing a minimized window
restores its prior state. These actions are not evidence of application data changes.
Use `{"kind":"window_state","expected":"normal"}` (no element selector) in a
precondition/await when needed. For scrolling, `visible` is an element predicate;
`exists` alone also matches offscreen accessible elements.

```json
{
  "session_id": "returned-session-id",
  "idempotency_key": "type-example-001",
  "steps": [{
    "id": "type",
    "op": "type_text",
    "args": {
      "at": {"selector": {"role": "Edit", "automation_id": "101"}},
      "text": "élève 中文 😀",
      "replace": true
    },
    "postcondition": {
      "kind": "value",
      "selector": {"role": "Edit", "automation_id": "101"},
      "expected": "élève 中文 😀"
    }
  }]
}
```

The selector above belongs to the native fixture, not every editor. Discover the
actual selector through `observe`; never hardcode it into generic client logic.

## Evidence and images

`dispatch` is `not_sent`, `sent` or `unknown`. `verification` is `met`, `unmet` or
`unobservable`. `completed` plus `effects_verified: false` does not prove the
desired application effect. A mutation normally requires a postcondition;
`verification: dispatch_only` is an explicit opt-out, unavailable for clipboard
paste or replay. Never retry an unknown effect with a new idempotency key.

Temporal composites can verify a group without claiming separate observations of
each physical click. A successful `watch` may include a `triggered_demonstration`
`verification_scope` for its one click/key trigger, and an accepted `replay` includes
`sequence_acceptance` for its exact internal clicks. Scopes use zero-based job-step
ordinals (`first_step`, `step_count`), not potentially repeated step names. Child
steps remain `unobservable`; the scope is explicit evidence of the aggregate
demonstration/round, not each intermediate effect. `effects_verified` accepts these
bounded groups only when their parent is verified and every member was acknowledged.
It never covers an unknown/failed member, arbitrary earlier dispatch-only input,
or a text/application edit hidden inside a watch trigger. Failed acceptance retains
`sent` evidence and does not authorize replay. Durable job recovery retains scopes.

`axis.capture` with `include_image: false` stores a local frame and returns its
transform/ID only. Points require either `space: frame` with a fresh `frame_id`,
or `space: client/desktop` with a current `geometry_id`. Old geometry is rejected.

`observe` scopes: `tree`, `diff`, `visual_diff`, `events`, `ocr`, `capabilities`.
Tree results carry coverage and page cursors. Missing data is never absence.
Target lists and OCR word boxes are also paginated immutable snapshots. OCR returns
`words` with line indices and a `text` view for each page; follow `next_cursor` for all
text. A native/provider failure is not represented as an empty successful observation.
`await_visual` can wait for change then stability with region masks; this proves
a visual predicate only, not a business result.
Its `require_change` default is `true`: a change must occur after its baseline.
For stabilization after a completed click/scroll, explicitly set
`require_change: false`. Do not infer a successful save from dialog disappearance;
wait for the application's saved-data/readback signal before dependent actions.

Plans support bounded `if`, `repeat`, `await`, `watch`, `replay` and `calibrate`.
`sequence-memory.play@1` observes/replays one calibrated round using local images
and a semantic player-turn/acceptance cue. It does not understand arbitrary games
or videos, and currently is not a certified multi-round recipe.

Temporal captures are measured as start/end intervals using the performance
counter. `max_gap` bounds the worst possible acquisition gap, including capture
latency. Calibration measures its first capture too. Geometry is revalidated
after each capture, and a final capture must cover the player-cue read without
new transitions. Lost coverage raises `SAMPLING_GAP`; an incomplete/changing tail
raises `INCOMPLETE_SEQUENCE`, and neither authorizes replay. Successful watch
outputs include `samples` and `max_observed_gap` in seconds, with no required model
images.

Windows' supervised adapter now advertises experimental `temporal_capture` and
uses an independent read-only capture process for `watch`. It is armed before
the trigger and keeps detecting transitions during input/semantic calls. Only
bounded detector summaries cross its private pipe; local images never reach the
model. The original target is rebound after reader startup, and both workers
track window lifetime/geometry independently. Lost coverage or a reader crash
aborts the watch: no reader restart or fallback during that execution.

The successful player cue is checked against a fresh capture checkpoint. If a
fully captured transition overlaps a slow semantic read, the cue is read again
after that transition; the trigger is never repeated. The reader is stopped
before replay, on cancellation, and on errors. It also observes the input
worker's shared cancellation signal while the caller is busy; closing the reader
never sets or resets that input signal. Confirmed shutdown closes process and
semaphore handles explicitly, even if a closed reader object remains referenced.
Native certification is still
pending. A PAL without this advertised capability retains bounded synchronous
sampling, which may reject long trigger/semantic calls as `SAMPLING_GAP`.
Results distinguish `observation_mode: continuous` from `polling` explicitly.

Long runs return a job ID; poll `axis.job` with `action: result` and follow
`next_cursor`. Alternatively, pass the original `idempotency_key` instead of
`job_id` to recover a lost acknowledgement. Neither lookup requires an active
observation session or a still-open target. An interrupted journal returns
`unknown`, preserving durable `sent` evidence but never inferring verification.
An intention without acknowledgement is `unknown`, not proof of no input.
Cancellation cannot undo sent effects or make an interrupted job known again.
Native jobs also expose `cleanup` separately: its state, owned input count and
whether a clipboard lease remains pending. Confirmed cleanup does not verify the
application effect. Failed emergency cleanup leaves the worker unavailable; the
same helper is not retried automatically. Windows now persists a session/desktop
quarantine across host processes (see operator safety above); native held-key
crash qualification remains unfinished.

Cleanup snapshots belong to the job that held the input lease. A job rejected
before acquisition reports `cleanup.state: not_required`, not another owner's
state. Inconsistent/unconfirmed cleanup prevents verified completion and blocks
new runs in that runtime with `INPUT_UNRECONCILED`; existing jobs remain queryable.
Arbitrary adapter cleanup details, including clipboard contents, are not persisted.
The in-process interlock supplements Windows' durable native-input quarantine.
Restarting alone is not evidence that previously held physical inputs were released.

Result-delivery failure after admission preserves `unknown` and the known job ID;
use `axis.job` with that ID or the original key. `RESULT_UNAVAILABLE` does not mean
the job failed to execute. A native `sent` acknowledgement remains `sent` even
when its journal write fails; the overall job cannot then claim verified completion.
Failed database transactions are rolled back under the journal lock. Subsequent
new runs are refused with `JOURNAL_UNAVAILABLE` until the host repairs/reopens the
journal; earlier job outcomes can still be inspected. No automatic restart/replay.

```json
{"idempotency_key":"type-example-001","action":"result"}
```

Treat page cursors as opaque and use them only with their original job. Large
lists inside `output` return a `{count, cursor}` descriptor; read its cursor with
`axis.job` to receive `output` pages. An oversized individual value uses
`item_data`, an oversized step uses `step_data`, and oversized job metadata uses
`result_data`. These explicit descriptors identify JSON fragments: concatenate
each returned `data` string in cursor order, then parse JSON once. Where provided,
check `utf8_bytes` and `sha256` against the concatenated UTF-8 JSON text. Fragment
offsets must not be constructed by clients. Full-result fragments are available
only after terminal status; step/list pages remain readable during progress.
Every text page stays within 12 KiB, including the version envelope, and the job
identity and execution status remain present even when an output is paginated.
