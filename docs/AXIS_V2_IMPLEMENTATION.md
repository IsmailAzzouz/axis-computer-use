# AXIS v2 — implementation and acceptance ledger

Status: **in development, not a completed/certified v2 release**. Updated 2026-09-24.
The full approved plan remains the objective. Passing a subset of tests does not
waive the remaining requirements below.

## Current implementation

- `cu_suite/v2/contracts.py`: one canonical six-tool contract (including `axis.help`), operation-discriminated
  JSON Schema, strict argument validation, bounded recursive plan compilation.
- `runtime.py`: host policy, contextual sessions/references/frames, SQLite durable
  intention/result journal, idempotency, short/async jobs, cancellation, paging,
  execution/postcondition separation, input lease, bounded caches.
- `worker.py`: persistent supervised native process, bounded RPC, out-of-band
  cancellation, owned-key notifications and emergency cleanup without retry.
- `pal.py` / `pal_contract.py`: separate portable feature protocols, validated
  capability snapshots and host adapter admission; native conformance still open.
- `platforms/windows.py`: process-start/window identity, geometry/DPI, actual
  foreground checks, owned popup/dialog surfaces, native click/right/double,
  Unicode input, clipboard paste, keys, hover/move, scroll, drag/swipe and range
  slider. No desktop switching or security-level bypass.
- `windows_events.py`: bounded WinEvent hooks; independent semantic polling still
  checks outcomes. Closed-window subscriptions are pruned. HWND lifetime generations
  distinguish native destroy/recreate events within the worker lifetime.
- `windows_accessibility.py`: lazy, native-filtered query walker with raw ancestry
  guards. Target-root inclusion prevents a filtered sibling search escaping to the
  desktop. No unbounded Python `GetChildren` list. Queries retain their coverage.
- `windows_focus.py`: explicit `focus(method=caption_click)` uses an exposed,
  native-confirmed caption; never a hidden Alt/AttachThreadInput workaround.
- `pages.py`: thread-safe immutable target/OCR snapshots with bounded output pages.
- `job_pages.py`: job-scoped result cursors, structured large-list pages and exact
  JSON fragments for oversized individual values/metadata; no empty-page loop.
- `windows_ocr.py/.ps1`: local WinRT OCR, explicit unavailable-language/backend
  errors, word boxes with crop offsets, no fabricated confidence.
- `perception.py`: semantic/pixel differences, masks, visual waits, hysteresis
  transitions, gap rejection, calibration, watch/replay, one-round Simon recipe.
- `temporal_worker.py`: independent read-only capture/detection process, bounded
  event history and checkpoints; Windows source wired, native qualification open.
- `transport.py`, `mcp.py`, `cli.py`: authenticated loopback JSON broker, six-tool
  MCP adapter, SDK and CLI clients sharing one resident runtime. No pickle over
  the client boundary; host authority cannot be supplied as tool arguments.
- `framing.py`: bounded UTF-8 JSON parsing/serialization and absolute socket frame
  deadlines. Broker/MCP admission is capped, with a separate job-control lane;
  CLI exposes host limits and bounds stdin before parsing.
- `testbench/native_fixture_v2.py`: isolated Win32 controls, context menu, slider,
  drag surface and pixel-only Simon demonstration, with an independent JSON oracle.

The package root now exports the v2 SDK without loading legacy native modules.
Its previous contents are preserved in `output/axis-v2-migration/legacy-init.py.txt`.
Public CLI/MCP/SDK module paths now route to v2. Historical implementations used
by regression tests live in test-only fixtures, not the distribution. Internal
legacy-provider retirement and full native qualification remain open.

## Evidence collected, not general certification

- Before implementation: `python -m pytest -q -p no:cacheprovider`:
  **213 tests + 33 subtests passed**. This baseline is mainly mocked.
- Previous v2-only suite: `python -m pytest tests/v2 -q -p no:cacheprovider`:
  **207 v2 tests passed in 14.76 seconds** on 2026-09-16.
  Includes actual TCP, subprocess worker fault injection, schema
  consistency, contextual coordinates, journal/idempotency and simulated clipboard.
- Previous full combined suite (2026-09-11): **393 tests passed in 20.23 seconds**, including
  the visibility, capability-admission, semantic-point, interrupted-job recovery
  and bounded-result pagination regressions.
  `compileall` also passed for v2, its tests and the native fixture. This includes
  legacy unit tests and is not a substitute for native acceptance coverage.
- Earlier combined suite (2026-09-16): `python -m pytest tests testbench/test_server.py
  -q -p no:cacheprovider`: **420 tests and 33 subtests passed in 34.23 seconds**.
  An earlier root invocation stopped at collection because generated
  `output/pytest-temp` and `output/pytest_temp` denied access. Pytest discovery is
  now explicitly scoped to `tests` and `testbench`, the source test directories;
  no failed test was deselected. The default root command then passed all
  **420 tests and 33 subtests in 33.28 seconds**. Compilation passed. Repository-wide `diff --check`
  still flags unrelated pre-existing whitespace in legacy files, left untouched.
- `python -m tests.v2.native_probe`: sandbox has zero interactive targets. Running
  the same read-only probe with session authorization returned 14 targets. No
  desktop attachment workaround was used.
- `output/axis-v2-native/initial/report.json`: native Unicode batch and drag passed;
  fixture oracle had an intermediate UTF-16 surrogate serialization exception,
  fixed by escaped JSON recording. Later runs did not report that exception.
- `output/axis-v2-native/gestures/report.json`: one real trial passed Unicode,
  right-click/menu, slider, drag and Simon.
- `output/axis-v2-native/perception/report.json`: one real trial also passed native
  value/name events and WinRT OCR. Simon used zero returned model images.
- `output/axis-v2-native/clipboard/report.json`: one real trial passed native paste
  and the basic gestures/events. Clipboard restoration is unit-tested separately;
  independently checking real clipboard restoration remains an acceptance task.
- `output/axis-v2-native/lifetime-check-2/report.json`: eight scenarios passed once
  after the HWND-lifetime/focus corrections; not a repeated-trial certification.
- `output/axis-v2-native/targeted-accessibility/report.json`: six scenarios passed,
  paste refused rich clipboard formats and Simon rejected a sampling gap. Both
  failures remain in the report (zero reported false successes); this run predates
  the filtered-walker root-boundary performance correction.
- Excel manual trials exposed incomplete-tree verification and native foreground
  denial. The user confirmed closing the first two Excel instances manually;
  their disappearance is NOT evidence of an Excel crash or proven launch defect.
  Native filtered reads succeed on Excel's start screen and cells.
- `output/axis-v2-native/excel-workflow-2/model-trace.jsonl`: model-directed native
  MCP/TCP execution opened a blank workbook, addressed a range, entered Unicode,
  numbers and a formula in one nine-step call, saved via the native file dialog,
  closed normally, reopened and re-read Unicode/42 before closing. Zero model
  images and no COM/Office authoring APIs. Individual typing steps intentionally
  use dispatch-only until their following Enter/postcondition, so the batch does
  not falsely mark every intermediate step independently verified.
  `persisted-oracle.json` independently verified raw saved OOXML, including the
  formula and Excel's cached result, without recalculating or rewriting the file.
  This is **one successful model-directed smoke exercise**, not 99/100 certification.
- Seven new adversarial cases first failed, then passed: property predicates on
  incomplete trees, lost step outcomes after acknowledged dispatch, releasing
  another owner's inputs after lease denial, and skipped cleanup after key-release
  failure. Replaying a sequence without a postcondition is now rejected up front.
- `output/axis-v2-native/lifecycle-negative-3/report.json`: seven native checks
  passed once: homonyms, physical caption activation, correct window, Ctrl release
  on cancellation, save dialog without forced closure, explicit fixture discard,
  normal cleanup. Two prior failed runs remain preserved.
- `output/axis-v2-native/lifecycle-window-states/report.json`: all previous checks
  plus actual maximize/minimize/normal placement and focus restoring prior bounds
  passed once (nine checks). Seven new unit regressions first exposed false success
  in state verification; the runtime now polls explicit PAL `window_state`.
- Native desktop-switching edits discovered locally were preserved in
  `output/axis-v2-migration/*-before-desktop-guard.py.txt` before removal. An AST
  regression rejects desktop switching and input-queue attachment throughout v2.
- Broker/MCP/SDK malformed-envelope tests exposed dropped connections, uncaught
  type errors, and falsy arguments silently coerced to objects. They now fail
  structurally before dispatch. Lost/malformed acknowledgements retain `unknown`
  status through MCP/CLI; clients never retry automatically.
- `output/axis-v2-native/edge-workflow-1/model-trace.jsonl`: native, model-directed
  Edge guest exercise passed address-bar navigation, Unicode customer editing and
  plan selection, explicit cross-process file dialog upload, context-menu rename,
  and nested scrolling with bounded repeat/local pixel stability. Zero returned
  images. `persisted-oracle.json` independently verifies customer state and exact
  uploaded bytes through read-only local HTTP and a fixture hash.
  This exercise is NOT an all-pass trial: immediate customer reopen showed stale
  data, parent-target file-picker input was refused, and the first visual wait
  wrongly requested a new change after the scroll. All remain in the trace.
  The testbench closes the customer dialog before refreshing its state
  (`app.js`, `bindForm`); immediate reopen can populate stale values. A later
  observed dismissal/reopen succeeded without re-submitting the save. This fixture
  race was corrected with dedicated deferred-read regressions on 2026-09-23;
  see the testbench form-save entry below. The original failed attempt remains
  part of the native trace and is not retroactively counted as a success.
  The file picker ran in another PID with a valid native owner. Explicitly targeting
  it succeeded. PAL ownership now follows contextual owner IDs across processes;
  six unit tests pass, but the parent-target route needs a new native run.
  `await_visual(require_change=false)` then allowed four scroll/stability iterations
  and verified the final delivery. First unsuccessful wait is not excluded.
  The planned tab test was NOT dispatched: the session expired during a several-hour
  interruption and the target then no longer existed. No cause of closure is proven.
  Both harness and disposable HTTP server were stopped afterward.
  The initial non-guest test profile displayed automatic sync confirmation; no
  confirmation was clicked and that test window was closed normally. Temporary
  browser profiles are excluded from Git; review raw traces before publishing.
- `visible` and `window_state` predicates now distinguish offscreen presence from
  actionability and expose native window state without requiring accessibility.
  The capabilities preflight checks semantic reads, local capture and replay's
  native clicks before earlier effects. The schema documents `await_visual`'s
  change-required default and its stability-only option.
- Semantic locators now carry their resolved bounds and query to the worker.
  Before native clicks, input focus clicks, and slider value changes, it re-reads
  the native element and checks the UIA hit-test ancestry (including text children).
  Same-window overlays, moved/replaced controls and incomplete readback are refused.
  Drag destinations are rechecked before button down, periodically while held,
  and at the final move; deadlines stop the gesture with owned-input cleanup.
  Slider lookup no longer materializes an unbounded `GetChildren()` list.
  These remain best-effort native checks, not atomic UI transactions; postconditions
  are still necessary. Unit regressions cover the portable guard and metadata.
  The new guard has NOT passed native qualification yet: `semantic-point-guard`
  stopped on `FOCUS_DENIED`; `semantic-point-guard-caption` stopped on
  `ACTIVATION_UNAVAILABLE` (no exposed confirmed caption). Both test windows closed
  normally, no scenario was counted as passed, and both reports remain preserved.
  Older native successes do not certify these latest worker changes.
- Durable job recovery now accepts either the job ID or its original idempotency
  key, without an observation session or native target lookup. Interrupted rows
  remain queryable as `unknown`; journal intentions never imply `not_sent`.
  Three real subprocess exits after intention, simulated input and acknowledgement
  are covered, with no replay during read-only recovery. These simulate effects;
  they are not native worker-held-key crash qualification.
- Result pagination retains job identity/status for large Unicode and escaped
  JSON values, binds cursors to their job and preserves every list entry. A real
  MCP/TCP test recovers and pages a large durable result after runtime restart,
  with no sessions and zero PAL dispatches. Invalid cursors and cross-job reuse
  are rejected. SDK/MCP/CLI use compact text serialization for the 12 KiB budget.
- A first native rejection with `dispatch: not_sent` is now `failed`, not an
  apparent partial execution. Prior verified progress or sent effects still
  produce a partial result when a subsequent action fails.
- Worker shutdown now drains ownership/clipboard notifications before accepting
  its cleanup acknowledgement. An emergency helper runs at most once for the
  reported ownership; failure/crash/timeout retains unresolved ownership and
  leaves that worker unusable. Jobs persist a separate cleanup summary (state,
  input count, clipboard pending), without clipboard contents. Eight new tests
  use simulated ownership, including real process crashes: this is NOT yet
  native held-key/clipboard crash certification or cross-host quarantine.
- `excel-activation-20260916/model-trace.jsonl` reproduced a false negative:
  native focus returned `FOCUS_DENIED/not_sent`, then a read-only `axis.targets`
  showed the requested Excel in foreground. Windows activation across input
  queues is asynchronous. The adapter now retains the native BOOL result, submits
  once and polls identity/foreground within its deadline. Accepted-but-unverified
  activation is `EFFECT_UNKNOWN/unknown`, never permission to replay. Eight focus
  regressions cover delayed activation, denial, deadline, cancellation and identity.
  See [Microsoft's explanation](https://devblogs.microsoft.com/oldnewthing/20161118-00/?p=94745).
- The same manual run physically clicked `Nouveau classeur` successfully through
  the current semantic-point guard, with zero returned images. An invalid model
  request (`observe` step with unsupported `args.query`) was rejected before any
  effects and remains in the trace; it is not removed from usability evidence.
- `excel-focus-fixed-20260916/summary.json`: two test launches and the first real
  native switch verified; the reverse switch genuinely returned BOOL false and
  `FOCUS_DENIED/not_sent`. The harness stopped before later inputs and closed both
  blank instances normally. Overall smoke result is **failed**, not certified;
  no failed switch is excluded. A read-only observer checked foreground HWND.
  `caption_click` also remains conditional: another maximized window can obscure
  every confirmed caption point, and SetWindowPos cannot guarantee exposure when
  foreground permission is absent. No topmost/Alt/input-queue workaround was added.

All native runs used MCP -> authenticated TCP -> Runtime -> resident Windows
worker -> dedicated fixture. Only the test harness read the fixture oracle.
Fixtures were closed through AXIS. The separate Excel/Edge exercises above prove
only their stated smoke outcomes, not 100-trial reliability, arbitrary games, or
independent model-population usability.

## Remaining work / acceptance gates

### Transport hardening checkpoint (2026-09-16)

- Latest complete source suite: `python -m pytest -q -p no:cacheprovider`:
  **448 tests and 33 subtests passed in 34.02 seconds**, including 28 additional
  admission/framing/worker-wait regressions since the earlier 420-test checkpoint.
  `compileall` and the updated host/MCP CLI help commands also passed.
- Broker connection/thread counts are capped before handler creation. Runtime-call
  admission and job control use independent bounded slots; stdio has no unbounded
  pending-action queue. Closing the broker drains in-flight calls before releasing
  runtime resources; socket disconnects do not cancel or replay jobs.
- Incoming requests and outgoing socket frames have total deadlines; byte trickles
  cannot keep resetting them. SDK connection/send/read share one deadline. Worker
  RPC admission is also deadline-bounded, without terminating the current owner
  when a waiting request was never submitted.
- JSON byte/depth bounds, duplicate-field/non-finite rejection, CLI stdin bounds,
  oversized-line stream termination, unavailable stdout, and oversized post-effect
  responses are covered. Unknown delivery does not become `not_sent`.
  Default CLI/MCP stdio uses binary UTF-8 independently of the Windows console's
  text encoding. Tests inject ASCII-only wrappers and retain French/CJK/emoji
  unchanged; a broken CLI output is attempted once, never replaying its action.
- A real stdio -> TCP -> Runtime -> simulated PAL test saturated ordinary calls,
  rejected a second run before journaling/dispatch, cancelled the first through
  `axis.job` by its idempotency key, and recovered the cancelled durable result.
  Real socket tests cover idle-connection reclamation, request/response trickles,
  bounded admission and draining shutdown. These are engine integration proofs,
  **not native desktop qualification or process-memory/handle endurance evidence**.
- Reserved execution slots do not guarantee control availability if every TCP
  connection is occupied by unauthenticated senders or stdio output is blocked.
  Visual/native allocations and long-running resource endurance remain to audit.

### Contract, execution and safety

Runtime result/ownership checkpoint (2026-09-16):

- Latest complete source suite: **469 tests and 33 subtests passed in 35.92 seconds**
  with `python -m pytest -q -p no:cacheprovider`; `compileall` also passed.
- Initially **10 failing regressions** reproduced post-admission false failures,
  overwritten native acknowledgements, cleanup attribution races, cancellation
  route loss, and a phantom accepted job after executor startup failure.
- Result-envelope failures preserve unknown outcome and available job identity;
  idempotent result lookup failure is not reported as an unsubmitted request.
  Error paths and the versioned envelope obey the text budget as well.
- Native ACK persistence is separate from dispatch: journal failure cannot rewrite
  known `sent` evidence to an unknown dispatch. Transaction failures roll back
  under the same lock and disable new admissions; stored jobs remain readable.
  Three additional failing commit-injection regressions were reproduced and fixed.
- Cleanup snapshots are validated/sanitized and captured before releasing the
  local input lease. Rejected jobs do not inherit another owner's cleanup report.
  Unconfirmed cleanup blocks later runs in this runtime, but this is not yet a
  durable cross-host quarantine/reconciliation mechanism.
- Cancellation identity check/signal and owner handoff are serialized. A delayed
  cancellation cannot affect the next owner. Shutdown prevents a call validated
  earlier from admitting input afterward. Executor startup uses an admission gate;
  even a launcher raising after OS thread creation cannot start an action.
- `tests/v2/test_result_integrity.py` currently covers 21 fault/race cases with
  simulated effects. Native fault injection, multi-host quarantine, deployment,
  application endurance and independent-model qualification remain outstanding.

- [ ] Complete an independent-style adversarial audit of all public inputs and
  resource bounds (including capability/OCR/tree/diff output sizes and large frames).
- [ ] Pre-admit every statically knowable permission/capability and verify mutation
  failure phases; expand restart/pagination, nested dataflow and race tests.
  Static native-action/target admission is implemented. Post-dispatch verification
  failures preserve the sent step and do not cause an automatic retry.
- [ ] Verify strict identity under handle reuse, duplicate native IDs, truncated
  selector matches and document navigation; inspect native exceptions for false
  absence/success and premature cleanup reporting.
- [ ] Test supervisor recovery while an input/clipboard lease is held, including
  cleanup failure and stale clipboard ownership. Clipboard currently deliberately
  refuses unsupported rich/binary formats rather than discarding them.
- [ ] Verify cancellation/foreground/user-input interruption in actual native
  actions, including held keys, drag, native menus and save dialogs.
- [ ] Document and validate complete PAL conformance / OS plugin onboarding; no
  macOS/Linux certification until an actual adapter and environment pass.
  Structural gate and onboarding guide now exist in `AXIS_V2_PAL.md`; generic
  native fixture drivers and full OS-specific behavioral qualification remain.

### Complete workflows

- [ ] Finish any missing application/window lifecycle conveniences without unsafe
  title matching, shell fallback or automatic forced closure.
- [ ] Native Excel: range selection, values/formulas, locale, readback, file save
  and independently verified persisted workbook. Excel is registered locally.
  First smoke exercise passed save/close/reopen. Selection-pattern readback,
  repeated trials, settings/version capture and adversarial coverage remain.
- [ ] Native Edge: isolated profile/window, navigation, tabs, forms, scrolling,
  context menus and native file dialogs. Edge is registered locally.
  Guest smoke exercise covers all listed actions except tabs; native cross-process
  parent-target correction, repeat trials and recorded version/settings remain.
- [ ] Native file drag/drop and nested scrolling, multiple displays/DPI, dialogs
  and homonymous windows. Preserve the existing browser/CAPTCHA training surfaces.
- [ ] Broaden temporal tests: repeated rounds/continuous arming across phase
  transitions, variable speeds, lost samples, foreign input and failure outcomes.
  The current installed recipe is explicitly **one round**, not a multi-round claim.
- [ ] Exercise `await_visual`/mask/geometry behavior end-to-end and add focused
  automated tests; native OCR succeeds on the fixture, not universal text.

### Migration, packaging and qualification

2026-09-16 continuation — in-plan observation/readback: `observe` steps now accept
the same targeted `query` selector as tree reads. Step results include retained,
immutable redacted snapshot data without another model call or native re-read;
only opaque identifiers/cursors enter the durable journal. Window sessions are
reused, job-specific child sessions preserve identity after `target_from`, and
evicted/restarted observations explicitly report unavailable data. Fragment reads
of expired snapshots fail instead of silently changing their source. Existing v2
descriptors without the newly added cursor remain readable.

This work also reproduced four false-success cases: local `observe`, `repeat`,
`if` and `await` steps ignored explicit postconditions. Local/control step
postconditions now participate in verification, deadlines and failure reporting;
native/replay effect handling retains its existing verification path. The new
tests check both met/unmet conditions and an unexpected provider exception.

Checkpoint: **505 tests + 33 subtests passed in 41.99s**, including 25 new
observation/control regressions. The public real-stdio test now requires a
filtered Unicode readback in the same two-step call. Rebuilt wheel, installed
outside the source tree and reran four module plus four console entrypoints:
all passed against the deterministic PAL. Wheel SHA-256:
`b855ba88e6907fdbe426949eb4d3a4ae7ba81ea0ee7f17d3ba73ed7e107e2290`.
No native desktop input or new host authorization in this continuation; the
native corpus and independent model usability qualification remain open.

2026-09-16 MCP cutover: public `cu_suite.cli`, `cu_suite.mcp.server`, package
`__main__` launchers and `cu_suite.sdk.AxisClient` now use v2. Added `axis-mcp`;
distribution version is `2.0.0.dev0` and OCR PowerShell resources are packaged.
Original CLI/MCP/SDK code was moved intact to test-only legacy fixtures (not in
the wheel), preserving historical regression coverage without a production v1
dispatcher fallback. Legacy facade/provider internals and scripts still require
retirement, so the broader migration item below remains open.

Validation: 480 tests + 33 subtests passed in 40.50s including the additive MCP
error-version assertion and executable skill example. Eleven new public-entrypoint tests cover real stdio
processes, shared broker/session, two-step Unicode execution, job retrieval,
exactly five tools, removed commands and explicit host-not-configured results.
This count includes preserved legacy-fixture tests; it is not 480 native v2 cases.
Wheel smoke ran from outside the source checkout: four module launchers and four
installed console commands passed; OCR resource present, legacy fixtures absent.
The test venv isolates the AXIS distribution but inherits system dependencies;
it is not a fully hermetic dependency-install qualification.

The model-facing AXIS skill was also migrated to the five-tool v2 workflow with
host readiness, contextual targeting, evidence/recovery and calibrated temporal
guidance. The previous guide is preserved in `docs/legacy/AXIS_V1_SKILL.md`, not
loaded as active instructions. Its security-disable/desktop-bridge/forced-close
advice is not carried into v2. The new skill example is executable against the
shared broker and deterministic PAL; independent model validation remains open.

Local deployment: dedicated `.venv-axis` editable install, user Codex server
`axis` configured and confirmed enabled by the real user-context Codex CLI.
Configured-command handshake exposes all five v2 tools. No resident native host
or desktop permissions were started for this update; credentials are intentionally
absent and tool execution reports `HOST_NOT_CONFIGURED/not_sent`. Reload the client
and start a separately authorized host with the shared token before desktop use.
The user reports the laptop lid closed; rerun native checks with an available,
unlocked interactive desktop. This observation does not explain all prior bugs.

### 2026-09-20 — agent help, compact schemas and runnable examples

Added sixth public tool `axis.help` at the user's request, superseding the earlier
five-tool-only UX decision. Short English/caveman-style guide, a three-step
focus/write/readback example, per-action arguments, and run/actions/errors topics.
Available offline via MCP, CLI and static SDK help; no native reads, credentials
or permission changes. Host readiness is still separate. Tool descriptions and
the active skill are shortened; skill-creator validation passed. Missing-field
errors now name the missing parameter, including inside operation arguments.

The advertised run definition shrank from 65,352 to 12,840 JSON characters
(default json.dumps, including description), by factoring shared fields and
definitions. No loose action-argument fallback: both internal and published
schemas still reject unknown fields and wrong operation parameters. Independent
jsonschema 4.26.0 checked all six schemas, all 25 action-help schemas and 125
equivalence cases against the original unfactored contract. This does not
constitute a real small-model usability evaluation.

Root `run_simon.py` and `play_sequence.py` now use one bounded v2 broker request,
with dry-run validation, inert imports, no direct native dispatch and no retries.
Original bodies remain non-executable text in docs/legacy. Documentation includes
explicit JSON examples. Real broker/subprocess tests cover Unicode readback and
calibrated Simon with consecutive repeated colors, fast/slow pulses and an
injected sampling gap that refuses replay. All use a deterministic PAL, not a
native game or hidden game-state oracle for the engine.

Those tests exposed a Windows Python clock issue: GetTickCount64-backed monotonic
time can assign identical timestamps to distinct captures. Temporal sample times
now use perf_counter; runtime deadlines retain monotonic time. Real sampling-gap
checks remain. A synchronous trigger can still cause a genuine gap; this is not
a claim of continuous sampling during arbitrary long input calls.

Validation checkpoint: 573 tests + 33 subtests passed, including historical
fixtures (not 573 native v2 scenarios). Wheel installed outside the checkout:
four module entrypoints and four console commands passed; all expose six tools,
with offline help also exercised. Native desktop and actual-model qualification
remain open; no desktop input was sent during this update.

- [ ] Move every public CLI/MCP/SDK entrypoint to v2 and remove replaced dispatchers
  and unsafe public legacy action paths, preserving original user edits as needed.
- [ ] Migrate examples, `run_simon.py`, `play_sequence.py`, docs and AXIS skill;
  validate the skill with skill-creator tooling. No old alias layer in the release.
  MCP quickstart and active AXIS skill are now v2; skill validation passed.
  Historical API/usage documents are explicitly marked v1; root scripts now v2.
- [ ] Package `.ps1` resources, align version/entrypoints, build/install a wheel in
  isolation and test actual installed clients (not source-tree-only imports).
- [ ] Rerun all active unit/integration and testbench checks after migration.
- [ ] Run the preregistered 100-trial native corpus, publish failures/unknowns,
  false-success count, timing/resource/call/image metrics and confidence intervals.
  An asynchronous question was sent asking when this 10–15 minute desktop campaign
  may run; inspect the user's reply before occupying the desktop for it.
- [ ] Actual text-only and multimodal model usability exercises with exact model
  and settings, clearly separate from a deterministic scripted harness.
- [ ] Final hands-on demonstration on the completed engine and a requirement-by-
  requirement completion audit. Do not mark the thread goal complete before this.

### 2026-09-20 — inherited runner deadlines

Added 17 deterministic regression cases. The first 14 failed on the prior runtime:
binding/resolution/precondition/journal delays could lead to input after a step's
deadline; control steps passed the global rather than local deadline to children;
late successful reads/ACKs could still mark a plan completed. Temporal baseline
capture also ran outside the shorter observation budget, including before trigger.

The runner now starts the step clock before preparation, checks before dispatch
and after reads/ACKs, and passes the remaining local budget through nested and
temporal operations. Waits are capped by remaining time. Late acknowledged input
is still `sent`, never retried; an acknowledged app launch retains its target for
reconciliation. Added cancellation-after-ACK and bounded replay regressions.

At this checkpoint, the native worker added response grace to its
RPC timeout and forwarded a relative dispatch timeout; lock/IPC delay could
inflate the adapter's effective budget (fixed below). Native mutation boundaries also need a
separate audit. Runner tests do not certify those worker/native timing properties,
nor instantaneous interruption of synchronous native reads or cleanup.

Validation: 590 tests + 33 subtests passed in 53.59s; the rebuilt/installed wheel
passed four MCP module entrypoints and four console commands, including offline
help and shared-broker simulated execution. No native desktop input was sent.

### 2026-09-20 — worker admission and ownership backlog

Worker dispatch now transports an absolute monotonic deadline across lock/IPC
waits. The child checks expiry and cancellation before invoking the adapter and
passes only the remaining duration. Response grace no longer extends admission.
Ownership notifications cannot indefinitely extend the response polling loop.

Stopping after a reply timeout must not discard queued ownership notifications.
After confirmed child exit, the supervisor drains the finite backlog before
emergency cleanup. EOF is handled consistently on Windows; incomplete frames or
an excessive backlog leave cleanup failed/unconfirmed. A final empty ownership
report resolves pending cleanup; no emergency release is repeated.

Thirteen added tests cover fake-clock boundaries, real spawned-process expiry,
cancellation and reuse after a pre-dispatch refusal, lock contention, and real
queued simulated key/clipboard ownership followed by one emergency cleanup.
The deadline doubles never call desktop input APIs. Rebuilt wheel and all eight
installed MCP/console entrypoints passed.

Final checkpoint for this change: 603 tests + 33 subtests passed in 51.28s.
Includes legacy fixtures and simulated PALs; not a native qualification count.

Remaining: audit per-mutation boundaries in the Windows adapter and blocking IPC
send/full-frame receive behavior. No claim of hard real-time bounds for native
calls or cleanup, and no native/model qualification claim from these tests.

### 2026-09-21 — Windows mutation guards

Added action-local deadline/cancellation checks at Windows input, pointer,
focus/window-state/close, launch/termination and native slider boundaries, with
checks after potentially slow target reads. Unicode typing checks between batches;
key holds stop at budget. Cleanup key/button-up input bypasses the action guard
but still retains ownership on failure. Cleanup itself no longer changes the
original action's `_did_send` flag. Pointer movement now counts as sent even if
the following click cannot happen.

Clipboard preparation accepts a guard checked after snapshot/enumeration and
before EmptyClipboard. Expiry there leaves clipboard data and sequence unchanged;
rollback/restoration remain permitted after expiry.

Twenty-three new adapter-logic tests execute the actual Windows class with all OS
effects replaced by recording doubles (AST class extraction avoids native module
initialization). Two added clipboard tests likewise use a fake clipboard. They
cover late/cancelled input, late lookup/identity/handle/slider preparation,
second-click interruption with button release, long key holds, Unicode batch
cancellation, reservation notification delay and failed cleanup retaining ownership.
These are not native desktop qualification or end-to-end application evidence.

Remaining timing work includes blocking worker IPC send/full-frame receive and
live native qualification. No hard real-time guarantee for OS calls or cleanup.

Validation: 628 tests + 33 subtests passed in 54.98s, including historical fixtures.
Rebuilt and installed wheel passed four MCP module and four console entrypoints;
no native desktop input was sent during this update.

### 2026-09-21 — bounded worker pipe I/O

Added WorkerChannel around the existing private multiprocessing pipe. Send and
full-frame receive have deadline-bounded waits, with one tracked I/O operation per
channel. A timed-out receive retains its result for stopped-worker ownership
draining. No replacement reader or automatic resend; unresolved sends reject new
payloads. Startup and emergency-helper replies also use bounded full-frame reads.
Ownership draining has one total one-second wait budget. Frames are capped at
64 MiB; invalid pickle payloads are distinguished from clean stream EOF.

A socket-pair prototype failed the existing abrupt-stop ownership-recovery tests
and was replaced before delivery. The shipped implementation preserves the pipe
and its queued ownership reports. An I/O-thread launch gate prevents any transfer
if thread.start raises even after starting a thread.

Twelve new tests cover forced-ready-but-incomplete receive, retained-reader
resumption, blocked 16 MiB send, real spawned worker stalled during a large request,
frame limits/corruption, 1 MiB Unicode/binary roundtrip, failed I/O-thread launch
and 100 transfers without remaining I/O threads. Existing worker cleanup tests
remain unchanged in their safety expectations. No desktop input is used.

Limits: this bounds waiting on I/O, not serialization/deserialization CPU or OS
scheduling. A pathological kernel operation can leave one daemon I/O thread on a
broken channel; it is not reused. Native/resource/endurance and model qualification
remain open. Internal pickle has no public or model-selectable transport endpoint.

Validation: 640 tests + 33 subtests passed in 76.40s. Wheel rebuilt/reinstalled;
four MCP module launchers, four console commands and a spawned worker imported
from installed site-packages passed. The installed worker returned a simulated
PIL capture across the private channel. No real desktop input or capture used.

### 2026-09-21 — persistent native-input quarantine

Windows now durably arms a per-session/desktop safety latch before granting its
native input lease. Normal release clears it after key/button and clipboard
cleanup. It lives in LocalAppData independently of the request journal, so runtime
restart/new journal does not reset an unresolved owner. Abandoned mutex detection
also persists the block. No clipboard contents, keys or user text enter this DB.

The operator-only `axis safety` command inspects status. Clearing requires the
exact owner, explicit input/clipboard review confirmations, the native mutex and
a read-only check that no key/button is down. It cannot clear a live lease and
does not inject input, replay effects or restore lost clipboard data. No MCP tool
or model plan can invoke reconciliation. SDK model surface remains six tools.
Emergency helper success intentionally does not auto-clear this durable marker.

Sixteen tests cover real child-process death, concurrent claim, stale-owner CAS,
corrupt storage, abandoned/native lease integration with OS doubles, operator
refusal/acknowledgement, CLI routing and sharing across processes. The real user
safety database has not been created or reconciled by this update. Native crash
qualification remains open; mixed old/new host versions are not certified.

Validation: 656 tests + 33 subtests passed in 53.91s, including historical
fixtures. After the final CLI parsing refactor, 27 safety/public-MCP tests passed.
The rebuilt and reinstalled wheel passed four MCP module launchers, four console
commands and the installed spawned-worker smoke with simulated capture. No native
desktop input or operator reconciliation was performed.

### 2026-09-23 — temporal capture coverage

Reproduced false completion when the final capture was slow, the player-turn
semantic read exceeded the sampling budget, the target moved inside capture,
or a new flash started while reading the player cue. The initial calibration
capture previously had no measured duration either.

Temporal samples now carry a high-resolution start/end envelope. Gap rejection
bounds the worst possible acquisition interval, not only completion timestamps;
calibration includes its baseline capture. Target geometry is checked before and
after capture. A final sample covers the successful semantic cue read and refuses
new transitions before declaring the sequence complete. Successful watch results
include `samples` and `max_observed_gap` (seconds); images remain local.

Fifteen new deterministic tests cover delayed captures/cues, invalid envelopes,
geometry changes and a flash during the cue read. Four run through the actual
runner and durable job lookup, proving no replay is dispatched after these errors.
The synchronous input worker still cannot capture during a long trigger or UIA
call: such gaps are refused, not repaired. An independent continuous observation
channel and multi-round/native qualification remain required.

Validation: 671 tests + 33 subtests passed in 62.20s, including historical
fixtures. Compilation passed. Rebuilt/reinstalled wheel passed four MCP module
entrypoints, four console commands and the installed spawned-worker smoke with
simulated capture. No real desktop input was used for this update.

### 2026-09-23 — independent continuous observation

Added the optional `temporal_capture` PAL capability and `open_observer` port.
The Windows factory wires a separate read-only source; the input worker remains
the sole input owner. The observer accepts only fixed snapshot requests, retains
at most 4096 transitions, sends summaries instead of images, uses the original
watch deadline, and is explicitly stopped before replay. Capture hangs are
terminated without invoking input cleanup/replay. Cancellation interrupts pending
checkpoint reads. No automatic observer restart or fallback after failure.

Windows observation attaches by native process birth/HWND and geometry, then
retains its own tracked generation. The runner rebinds the original input-worker
identity after arming to close the attachment gap. Native event tracking and
foreground/geometry checks surround each read. The sampling loop never acquires
the input lease and its protocol cannot request input dispatch.

The runner now consumes continuous summaries when advertised; other PALs retain
explicit `polling` mode. A slow player-cue read overlapping a fully recorded
transition requires another read after it, never another trigger. One-round
recipes and the original six public tools are unchanged.

Twenty-one new tests include actual spawned capture workers: repeated red flashes
during a 1.6s blocked trigger, slow semantic cue reads, genuine sampling loss,
process crash, stuck capture, cancellation, invalid protocol messages, and target
replacement while attaching. The runner proves no own replay clicks are sampled.
Windows attachment/visibility tests double every native call; they are not native
desktop evidence. Native continuous capture, resource endurance and multi-round
phase handling remain unqualified.

Validation: 692 tests + 33 subtests passed in 80.18s. Compilation passed.
The rebuilt/installed wheel passed four MCP module launchers, four console
commands, the existing simulated input worker, and the new spawned observation
worker importing from installed site-packages. No real desktop input/capture was
used for this update.

### 2026-09-23 — observer resource endurance and cancellation

A real process/handle probe reproduced 58 additional Windows handles after eight
stopped readers retained by their caller. `join` waited for exit but did not close
the process handle or release the multiprocessing Event semaphores. Explicit
close now releases both after confirmed exit. Failed shutdown still disables
snapshots and reports failure, without pretending the reader is closed.

`test_temporal_resources.py` keeps 100 closed objects alive: 174 handles before,
174 after and at peak after each close; zero remaining child processes or I/O
threads. RSS delta 176128 bytes; mean lifecycle .14578s, maximum .25s. This is
synthetic idle capture, not application/native acceptance. Evidence is retained
in `output/axis-v2-observer-endurance.xml`.

The source also checks the input worker's shared cancellation event independently
of parent checkpoints. Two new process tests prove cancellation stops the reader
without another read, and normal reader shutdown cannot cancel the input worker.

Native qualification was attempted read-only: the local adapter reported
`interactive:false`, zero targets and no capture capability. The connected AXIS
MCP returned the updated `axis.help` successfully, but `axis.targets` returned
`HOST_NOT_CONFIGURED/not_sent`. No fixture was launched or input sent. The user
was asked to restore an interactive session and configure the authorized host;
no desktop switching, input fallback or automatic host authorization was used.

Validation: 695 tests + 33 subtests passed in 84.73s. Compilation and the rebuilt,
installed MCP/worker/observer smoke passed. The 100-cycle resource test is now
part of the cumulative suite; it is not counted as 100 native application trials.

### 2026-09-23 — testbench save/reopen race

Customer/ticket dialogs previously closed after PUT/POST acknowledgement but
before state refresh, exposing stale records on immediate reopen. Forms now stay
busy through readback; acknowledged normalized records enter the local cache and
invalidate older pending refreshes first. Failed readback is a separate warning,
not a reason to resubmit the write. New-record focus uses the server-issued ID.

Seven Node tests cover deferred reads, rejected writes, failed post-ACK reads,
immutable cache updates, new IDs, string ticket IDs and post-ACK rendering errors.
They run through a pytest wrapper (explicit skip if Node is absent). Targeted
backend/wrapper validation: 12 tests + 33 subtests passed; JS syntax checks passed.

Using the Browser skill on a disposable localhost run, customer save/reopen showed
the new email and Team plan; ticket save/reopen preserved `Export fiable — 中文`
and Done. Console warnings/errors were empty. The email input was visually checked
because the browser's read-only DOM projection returned an empty value for that
field. This is browser application QA, not AXIS native Edge qualification; no
CAPTCHA/provider challenge was operated. Existing exercises remain in place.
Both saved records remained visible after a full page reload. The agent-created
tab and disposable in-memory test server were closed after validation.

The testbench README now uses the six-tool v2 SDK surface instead of the removed
ComputerUseSuite facade and correctly describes the available training areas.

Full validation completed on 2026-09-24: 696 tests + 33 subtests passed in 82.77s.
The report is retained at `output/axis-v2-full-20260924.xml`; the earlier
interrupted invocation was not counted as a successful run.

### 2026-09-24 — portable adapter admission

Added separate PAL protocols for discovery, input, accessibility, capture, OCR,
events and continuous observation. Runtime capability reads now reject non-boolean
flags, invalid/duplicate/native-vs-engine action lists, non-finite/oversized JSON
metadata, dependency mismatches and missing advertised ports. Snapshots are copied
so callers cannot mutate the provider's live action list. Unsupported capture/tree
reads refuse before entering those methods, including visual differences.

The OS factory additionally requires physical input ownership/cancellation/cleanup
ports when native actions are advertised, rejects ambiguous plugin registrations,
and closes a rejected adapter. Test doubles now advertise native operations only;
engine-owned watch/replay/control-flow operations are not adapter actions.

Thirty new tests exercise malformed declarations, missing ports, immutable metadata,
first-effect preflight, unavailable reads, read-only adapters and rejected/ambiguous
plugins. `ADAPTER_CONTRACT_ERROR` recovery is included in the compact help.
`AXIS_V2_PAL.md` documents registration, data/behavioral obligations and the remaining
native/model qualification gates. Method existence is not behavioral conformance;
no new OS is announced supported or certified by this change.

Validation: 726 tests + 33 subtests passed in 89.12s; report retained at
`output/axis-v2-pal-contract-20260924.xml`. Compilation and the rebuilt/installed
MCP, input-worker and observation-worker smoke passed with synthetic backends.
No native desktop input was performed for these adapter-contract changes.

### 2026-09-24 — target binding and readback consistency

Fault injection reproduced a wrong-ID binding reaching native dispatch, focus
readback accepting a replacement window, duplicate discovery IDs granting an
arbitrary dialog's authority, mutable provider data rewriting retained identity,
and repeated discovery reads silently dropping owned dialogs on failure.

Runtime discovery/binding now validates independent JSON target snapshots,
identity and explicit finite geometry, refuses duplicate IDs and uses one
discovery snapshot for permission filtering. Focus readback compares the original
identity and preserves the acknowledged `sent` state on failed verification.
Close readback validates the original binding without requiring a closed owned
dialog to remain in discovery; only explicit original-window absence proves close.
Unchanged geometry IDs cannot accompany changed bounds/origin/DPI.

The new target-contract suite also covers malformed data, negative/collapsed
geometry, title truncation without provider mutation, discovery failure and
unknown versus confirmed missing windows. These are adapter-double regression
tests, not native qualification; the complete native/model gates remain open.

Validation: 32 new target-contract tests; complete final suite **758 tests + 33
subtests passed in 84.24s**, retained in
`output/axis-v2-target-contract-20260924-final.xml`. Compilation and rebuilt wheel
installation passed. Installed smoke confirmed four stdio modules, four console
commands and both worker types with synthetic sources; no native effects were
claimed. Wheel SHA-256:
`50ec59d3ee88a6fd5b8f1d5c591405d1a5aa5d37a102bb0558611702b9b234aa`.

Live read-only readiness recheck: connected `axis.targets({})` returned
`HOST_NOT_CONFIGURED/not_sent`; `python -m tests.v2.native_probe` returned Windows
`experimental`, `interactive:false`, no native actions/features and zero targets.
An authorized host/MCP token connection and an interactive Windows desktop are
still required before native Excel/Edge/Simon trials. No bypass or input was used.

### 2026-09-24 — qualification accounting, not certification

Auditing the fixture harness found that completed-but-unverified action results
could pass, scripted MCP calls were counted as model calls, and the aggregate
threshold measured whole-trial intersection rather than each declared scenario.
Setup/early-read failures could also leave no complete planned-corpus denominator.

`benchmarks/qualification.py` now separates verified/failed/abstained/unknown/not-run
outcomes, rejects duplicate/out-of-range trial IDs and keeps every scheduled trial
in each scenario's denominator. Only verified-effect claims contradicted by their
independent oracle count as false successes. A scoped 99%-per-scenario/100-trial
gate is distinct from full release certification, which remains false.

The native fixture harness integrates this accounting, independent launch/focus/
close checks, measured tool-call latency and explicit zero model calls. Fresh run
directories, preflight summaries, atomic reports and flushed request/response traces
preserve failures and original idempotency keys. Source/configuration fingerprints
are recorded; no benchmark token savings or unrun model results are invented.
`AXIS_V2_QUALIFICATION.md` describes the route, exact gate and application/model/
safety/resource evidence still missing. Native repeated qualification remains open.

Validation: 35 accounting/harness regressions pass, including real MCP-handler/
TCP/runtime integration with a synthetic PAL, deliberately lost post-dispatch
reply, unavailable independent oracle, rejected trial counts, protected previous
evidence and noninteractive setup. No native application is launched by these
tests. Complete suite: **793 tests + 33 subtests passed in 89.23s**, report retained
at `output/axis-v2-qualification-accounting-20260924.xml`. Compilation passed.
No 100-trial native run or actual model evaluation is claimed by this checkpoint.

### 2026-09-24 — authorized native smoke and temporal aggregate proof

A separately authorized read-only probe outside the isolated execution context
returned an interactive Windows desktop and 19 targets. The same default-context
probe still returns `interactive:false` and zero targets. The earlier absence was
therefore not evidence that the user's desktop itself was unavailable. No native
desktop switching, input-queue attachment or focus bypass was introduced.

Two fresh one-trial native fixture runs were performed with OCR, clipboard paste,
Simon and explicit caption-click activation enabled. Original evidence is retained:

- `output/axis-v2-native/qualification-20260924-current-01`: the game accepted its
  repeated-color round, but the global result remained unverified because trigger
  and replay clicks individually had no observable postconditions. Clipboard paste
  refused rich/binary formats before input and preserved the user's clipboard.
- `output/axis-v2-native/qualification-20260924-current-02`: after the fix, **10 of
  11 declared scenarios verified once**, including Simon and normal close. Paste
  remains an explicit `CLIPBOARD_UNSUPPORTED/not_sent` abstention, not an excluded
  scenario or a success. Exit code remains 1. The fixture closed, cleanup confirmed
  no held input/pending clipboard, 17 scripted tool calls and zero returned images.

`verification.py` now recognizes two purpose-built aggregate scopes: the completed
triggered demonstration for one click/key trigger, and an accepted replay for its
exact internal clicks. Children remain `unobservable`; no per-click observation is
invented. Scopes are engine-produced, ordinal-bound and persisted in job results;
model requests cannot supply them. Unknown/failed members, text/application edits,
nested arbitrary triggers and unrelated dispatch-only inputs remain unverified.
The polling and continuous observation paths retain their original sampling loop;
no blocking predicate was added inside a trigger to make a result appear verified.
Failed round acceptance now retains the already-acknowledged `sent` evidence.

The compact help/API/examples explain group proof and safe clipboard refusal.
Regression coverage includes rejected acceptance, lost click acknowledgement,
ordinal disambiguation across repeats, durable recovery and subprocess example
clients. Existing example assertions that deliberately expected the old global
false result were updated to assert the new exact scopes while retaining checks
that each physical click is still unobservable. The first failed full-suite report
is preserved; it was not reported as a passing run.

Final validation: **826 tests + 33 subtests passed in 89.92s**, report retained at
`output/axis-v2-native-effect-scopes-20260924-final.xml`. Compilation passed.
The rebuilt/installed wheel's four stdio modules, four console commands and both
worker types pass synthetic smoke. SHA-256:
`4cd1e594bd087cad14397ecced35e3f798277b8bb8a9945ee1e4dc05dab729c6`.
This is one native attempt per current configuration, not the 100-trial gate or
actual-model usability qualification. The existing connected MCP still needs its
authorized resident-host/token configuration; these runs used isolated test hosts.

## 2026-09-24 — compact action examples and native Excel edit-buffer fix

The connected MCP already exposed `axis.help`; its running process was still
serving an older loaded guide. The source guide now uses short numbered lines and
returns complete copyable run plans for eight common actions, not just argument
schemas. The default response remains small; advanced details are on demand.
These examples preserve idempotency and distinguish unverified shortcut/scroll
input from success. This is not yet measured tiny-model usability.

A fresh native Excel investigation reproduced a specific perception omission:
ValuePattern and RangeValuePattern were absent on CellEdit/FormulaBar while
TextPattern contained the exact in-progress Unicode text. The new UIA fallback is
limited to non-password Edit controls, preserves exact text (including newlines),
reports `value_source: uia_text_pattern`, and rejects overflow past 4096 UTF-16
units as `OBSERVATION_INCOMPLETE`. Provider failures are not empty values. No
application object-model writing or generic verification waiver was added.

`tests.v2.native_excel_smoke` now runs the real MCP handler/TCP/runtime/native-worker
path with a new French Excel `/x` instance and fresh workbook only. The first run,
`output/axis-v2-native/excel-text-pattern-20260924-01/report.json`, passed all stages:
new workbook, four cells, save, persisted-file oracle, close, reopen, reread, close.
All eight write/commit steps were submitted in one call and individually verified:
formula-bar buffer after typing, committed cell after Enter. Saved raw OOXML
independently confirms A1 Unicode, A2=21, B1=2, B2 formula A2*B1 and saved cache 42.
No returned images; zero model calls (scripted driver), not model evaluation.
Final cleanup confirmed no owned input or pending clipboard; both test instances
closed normally. No existing user documents were opened or modified.

The exploratory one-cell workbook is retained separately in
`excel-repro-20260924-01/AXIS-text-pattern-diagnostic.xlsx`; it proves Unicode only,
not the four-cell oracle (that oracle correctly failed its other checks).
The prior blank-window identity had disappeared; it was not reused or force-closed.
The manual test host was shut down after saving/closing its new diagnostic window.

The shared native harness now fsyncs requests before dispatch and responses after
receipt, preserving original keys if interrupted. The Excel driver checkpoints
each stage, refuses reused output directories and stops without blind retry or
forced discard. Range selection, 100 trials, other locales, independent per-action
oracles, resource endurance and actual-model usage remain unqualified.

Rebuilt wheel at `output/axis-v2-text-edit-package`:
`86030baee3d37b175ca17dab73c95519c7b80f38fa0c7cbddcc6579d6d9eddc3`.
Installed-package smoke passed four stdio modules, four console commands and both
worker types. This updates the test installation, not the already-running MCP
process or permanent resident-host policy. Those still require operator-approved
scope/configuration and a client reconnect. No permanent credentials were written.

Final cumulative suite: **857 tests + 33 subtests passed in 95.59s**;
`output/axis-v2-text-edit-20260924-final.xml`. Compileall passed. Default help is
1106 UTF-8 JSON bytes and click help is 1948 bytes (not measured token counts).
Repository-wide `git diff --check` still reports pre-existing whitespace in legacy
files not edited in this turn; those unrelated changes were preserved.

## 2026-09-24 — selection state and interrupted native range smoke

The native UIA reader now exposes nullable `selected`, sourced from
SelectionItemPattern rather than focus. Contracts accept the boolean `selected`
predicate; missing/null/nonboolean states return `UNOBSERVABLE`, never false.
Semantic diffs include selection changes. Unit/contract tests distinguish
selection, focus, unsupported providers, malformed values and strict predicates.

Excel's initial A1 SelectionItemPattern was true and neighbouring cells false,
while the sheet's SelectionPattern array was empty. The latter was therefore not
used as proof of a complete selection. `native_excel_smoke --selection` checks
A1:B2 members and neighbours, then independently checks the exact saved OOXML
selection (one view, no panes/disjoint ranges). This extension is not yet qualified.

The manual attempt in `excel-selection-20260924-01` stopped on FOCUS_LOST before
typing, then ACTIVATION_UNAVAILABLE after an explicit caption-focus request.
The still-blank test workbook closed normally and its host was stopped. A fresh
automated attempt in `excel-selection-smoke-20260924-01` stopped at write_A1 with
USER_INPUT_ACTIVE and dispatch sent; it was not retried. Its test window requires
reconciliation before further input. The user subsequently authorized resumption
of the already-open Excel test through a Luna subagent only.

Software validation before that delegation: **896 tests + 33 subtests passed in
96.36s**, `output/axis-v2-selection-20260924.xml`. This is not native range success.

### Luna native follow-up

User explicitly requested gpt-6-luna for Excel input. That subagent ran
`excel-selection-luna-20260924-01`: native selection predicates passed, but the
independent oracle failed because it also required `activeCell=A1`. Saved XML
contained the exact requested `sqref=A1:B2` without activeCell. The test was fixed
to verify the requested range without imposing an unrequested active-cell anchor;
23 targeted oracle/driver tests passed. The original failed report is preserved.

Luna's separate `excel-selection-luna-20260924-02` then passed: all six persisted
checks, range membership/neighbours, save, normal close, reopen, value and selection
rereads, final normal close. Parent independently inspected that report and the
saved workbook's presence. Cleanup confirmed zero owned input and no pending
clipboard; no lock file remained in this run directory. This is one scripted
native smoke operated by Luna, not 100-trial qualification or a measured model
usability benchmark. The agent reported older PIDs 18564/18644 still present with
zero main-window handles; these were not killed or treated as proven absent.

## 2026-09-25 — standalone lifecycle and allow-all regression checks

Preserved the user's newly added `--allow-all` / `--standalone` behavior without
enabling it in the installed client configuration. It grants all app/window and
termination authority only when the operator selects it; model requests cannot
supply the policy. Migration documentation now distinguishes the default shared
broker from process-owned standalone runtime and its durable-journal obligations.

Fixed an actual startup lifetime gap: both host and standalone CLI constructed
the native worker before Runtime/journal initialization, outside the cleanup
block. `_host_runtime` now closes that worker if initialization fails, and closes
the runtime exactly once after normal EOF, server failure or interruption.
Tests exercise missing journal directory, broker bind failure, invalid MCP
concurrency, missing credentials, EOF, exceptions and KeyboardInterrupt with
deterministic doubles. No native input or operator policy change was used.

A user-requested Luna subagent added portable allow-all tests for strict plans,
model authority rejection, dispatch-only honesty, uncertain-effect idempotency,
default deny and false environment values. Parent integrated the MCP stream test
using the actual concurrent `serve` path and matched replies by JSON-RPC ID,
without assuming reply order or depending on an installed Windows backend.
The initial local failures were capture-fixture/import mistakes, corrected before
the final targeted run: **16 passed**. No engine validation was weakened.

The rebuilt wheel in `output/axis-v2-standalone-package-20260925` has SHA-256
`e0e4101d3a55eff9abcb482f7bad4ee4fb5435b4292aee698985d17c9ba02760`.
Its isolated test installation passes four stdio modules, four console commands
and both worker-type synthetic checks. Compileall passed. This does not restart
the already-connected client or establish native/model qualification.

Final cumulative validation: **913 tests + 33 subtests passed in 98.45s**,
`output/axis-v2-standalone-lifecycle-20260925.xml`.

## 2026-09-25 — repeatable Edge driver and trial-bound persistence oracle

Added `tests/v2/native_edge_smoke.py` with Luna, then integrated and reviewed its
portable contracts. It uses an isolated guest Edge window and a fresh disposable
testbench, native UIA/inputs through MCP/TCP, Unicode customer editing, native
address-bar navigation and CSV file-dialog upload. Evidence is checkpointed and
requests are flushed before dispatch. Only the exact file-dialog trigger may
remain dispatch-only; that result is preserved as `unobservable`/unverified,
with a separate owned-dialog observation, never rewritten as a verified click.

Hardened `verify_edge_workflow`: the expected run ID must be recorded before
native input. It checks exact fixture size/hash and downloaded bytes, then rereads
the relevant state to detect a reset or changed evidence during verification.
It refuses redirects, proxy forwarding and decorated/nonlocal URLs. Fourteen
oracle tests cover synthetic evidence plus the real local HTTP/SQLite testbench;
these are not native-action trials.

The first Luna native attempt is retained at
`output/axis-v2-native/edge-luna-20260925-01/report.json`: launch/focus succeeded,
but the Customers click was sent and its predicate timed out. Cleanup confirmed
zero owned inputs and no pending clipboard restoration. No retry or forced close
was performed. Source inspection found the driver's missing UI search: customers
are alphabetically sorted in pages of eight; Maya Chen is not on the initial page.
Added a native search-field write/value check followed by the Edit-button wait.
The original failed trial remains failed and is not excluded or relabeled.

Cumulative validation before that search correction: **959 tests + 54 subtests**,
`output/axis-v2-edge-driver-20260925.xml`. After the correction: **47 targeted tests
+ 21 subtests** pass. Compileall passed. Native repeatability, the full Edge
interaction corpus, actual small-model evaluation and the 100-trial delivery
gate remain open. No installed MCP permissions or restart state were changed.

The corrected driver retains `testbench.sqlite3` in each fresh run directory;
startup-failure tests verify that evidence remains bound to the same run ID.
Luna's second independent attempt, `edge-luna-20260925-02`, verified the Customers
navigation, then stopped on `NATIVE_ERROR` / `COMError` during a read-only UIA
observation of the search field (`dispatch: not_sent`). No customer typing was
sent. This provider failure remains unresolved; it is not a passing trial or a
reason to replay input. The two attempts' reports remain unchanged. The driver
now reports the provider error code instead of mislabeling it as incomplete
coverage. Latest targeted validation: **49 tests + 21 subtests** pass.

The read-only reconciliation in `edge-luna-20260925-02/diagnostic.json` discovered
a fresh contextual binding for the same test PID and successfully observed the
visible, empty `customer-search` edit. No input was sent. This shows that the
control is present after the failure, but does not establish the original COM
HRESULT or root cause. The broad button read was paginated and is not evidence
of absence. Further diagnosis must retain provider error details before adding
any targeted, bounded read recovery; no mutation retry is justified by this read.
Failed test windows were left open, and no persistent MCP authority was changed.

## 2026-09-25 — sanitized UIA provider diagnostics

The Windows adapter now preserves a COM provider failure's numeric HRESULT and
fixed read stage (`root`, `walk`, `identity`, `value`, `selection`, `geometry`,
`properties`, `filter`) as `OBSERVATION_UNAVAILABLE`. It never emits native
exception strings/partial UI contents, invents an HRESULT, retries a read/input,
or interprets all COM errors as stale elements. Portable injected-provider tests
and actual adapter-method tests with OS doubles cover this boundary.

Validation: **964 tests + 54 subtests** in
`output/axis-v2-uia-diagnostics-20260925.xml` (excluding the concurrently added
provider-diagnostic file); that file separately passes **10 tests**, and the
combined adapter/provider subset passes **12 tests**. Rebuilt wheel:
`output/axis-v2-uia-package-20260925/axis_computer_use-2.0.0.dev0-py3-none-any.whl`,
SHA-256 `27f2bcbb943b91e79f70802e89206036972b149e9ce2a10f2a49ad32b28a2b7c`.
The isolated installed-package smoke passes four stdio modules, four console
commands and two synthetic worker types. This does not restart the connected MCP.

Luna's native `edge-luna-20260925-03` passed search, customer opening, email and
Unicode company edit predicates. It then stopped after the Plan click because
the scoped accessibility read was truncated, not because a COM error recurred.
The failure remains in the corpus. Read-only reconciliation found the Plan
ComboBox (`Starter`, not focused) and its three native list items (Starter
selected/focused), but both reads were truncated: approximately 8.026s and 4.193s.
No absence/uniqueness claim or mutation replay follows from those incomplete
reads. The original COM cause is still unproven; the new traversal problem is
under investigation. Test windows remain open, with no forced closure.

## 2026-09-25 — confirmed native accessibility cycles, guarded recovery

`edge-luna-20260925-03/traversal-diagnostic.json` proves a cyclic filtered sibling
walk: Starter -> Team -> Business -> Starter, with 511 next-sibling calls until
the 512-node limit. These were not missing controls. The bounded read-only probe
retains the native roots, capped runtime-ID navigation trace and counters.

Added sibling/ancestor cycle detection and one scoped raw-walker recovery. It
discards the failing root's partial snapshot, preserves completed roots, shares
the original deadline/node limit, and never repeats input or a COM failure.
Raw scope escapes and remaining cycles return `OBSERVATION_UNAVAILABLE`; budget
exhaustion stays truncated. Nine regression tests cover recovery, both kinds of
cycle, scope, shared budgets, existing roots and non-retry of provider errors.
The Edge driver now checks the popup's selected item (Starter, then Team) before
checking the committed ComboBox value; native evidence showed focus moves into
the popup, so the previous closed-ComboBox focus predicate was incorrect.

The fourth fresh Luna trial, `edge-luna-20260925-04/report.json`, still fails after
the Plan click: **the raw traversal also cycles**. The preceding search, email
and Unicode edits verify; input cleanup is confirmed. No save/retry/forced close
followed. This is NOT a native fix or a passing Edge trial. The three earlier
failed trial reports are retained unchanged. The attempted raw-only/reopen probes
on trial 03 did not establish finite traversal: the popup, then the exact window
binding, were no longer available, so they sent no input.

Cumulative validation after the cycle changes: **983 tests + 54 subtests**,
`output/axis-v2-uia-cycle-20260925.xml`. The rebuilt cycle-package wheel has SHA-256
`6d51727972ade122c1871ed87b6663ec7c671a0923135b12ab7b9d29922120ff`; its isolated
installation passes four stdio entrypoints, four console commands and the two
synthetic worker checks. The connected MCP configuration/restart and all native
delivery/model-evaluation gates remain unchanged. Do not treat a cyclic traversal
as successful absence or uniqueness merely to advance the workflow.

## 2026-09-25 — bounded search experiment and qualification-host cleanup

`tests/v2/native_uia_walk_probe.py` compares raw, control and filtered walkers
from the same UIA client that created each root. Trial 04's `view-probe-01.json`
shows cycles for both the adapter and library clients, including ControlView.
Changing client instances or using ControlView therefore did not fix this case.

Added `tests/v2/native_uia_search_probe.py`: read-only, explicitly PID-scoped
FindFirst / FindFirstBuildCache comparisons, typed SAFEARRAY(I4) runtime-ID
exclusions, scope checks, fixed node/time budgets, and a supervised diagnostic
child. Only the diagnostic child can be terminated on timeout; no application
inputs, launches or closure occur. A provider NULL ends that API query, not a
claim of comprehensive desktop coverage. The optional `--same-client` mode
brackets a raw-cache query with two live searches and records owned HWNDs.
The first run exposed a Windows Pipe.poll BrokenPipeError after a child had
already returned its terminal error; this is now handled and regression-tested.

Trial 05 again failed after the Plan click with the traversal-cycle error and
confirmed input cleanup. Its `search-probe-01.json` found Starter, Team and
Business through plain FindFirst in four calls (1.625s), but the subsequent
raw-cache query returned no list items. Both variants found the Plan ComboBox.
This discrepancy is unresolved: neither API equivalence nor stable UI state
across those separate child processes was established. The later same-client
probe could no longer identify the exact test window and sent no input.
Microsoft also documents that plain FindFirst omits raw-tree elements:
[FindFirst](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-findfirst),
[FindFirstBuildCache](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-findfirstbuildcache).
**No search fallback or narrower completeness claim was added to the engine.**

Trial 06 reproduced the Plan failure; its shell diagnostic wrapper then failed
on the reserved PowerShell PID variable, before invoking the read-only probe.
Trial 07 stopped at activation with `ACTIVATION_UNAVAILABLE`: no exposed,
native-confirmed caption point. Its wrapper correctly refused to probe a popup
that had never opened. Both reports remain in the native corpus; neither is a
passing Edge trial, and no uncertain gesture was replayed or forcibly closed.
Window disappearance between diagnostic calls remains unexplained.

The native harness itself could leak its worker after capabilities, journal,
broker or MCP initialization failed. ExitStack now transfers ownership to the
runtime only after construction, shuts down only a started server thread, closes
all acquired resources even if an earlier cleanup callback fails, and retains
the trace on teardown errors. Close is idempotent. Nine lifecycle tests cover
these paths; eight failed before the fix. The two probe modules have sixteen
portable tests. Cumulative validation: **1,008 tests + 54 subtests**, recorded in
`output/axis-v2-uia-search-20260925.xml`. The core reader/package was not changed
by this experiment. Native qualification, connected MCP restart/configuration,
100-trial and real-model usability gates are still open.

## 2026-09-25 — native cycle recovery through bounded raw-tree search

Trial 08 reproduced the cycle; its shell wrapper incorrectly rejected a valid
JSON PID represented as a PowerShell Int64. It sent no diagnostic input.
The optional `--diagnose-uia-cycle` is now part of the Python smoke driver:
it runs only after the exact sent Plan-click failure with confirmed cleanup,
before disposing the original runtime/UIA client. No input is retried.

Trial 09 establishes a consistent same-client comparison: live-before,
raw-cache and live-after each returned Starter/Team/Business with identical
runtime IDs; owned HWNDs remained `[394814, 394952]`. The raw-cache search
exhausted in four calls (1.469s in this diagnostic, not a performance gate).
This does not explain every earlier disappearing-window/cache discrepancy.

`windows_accessibility.py` now replaces the unsuccessful raw-walker recovery
with FindFirstBuildCache raw-tree search. It caches only each returned element,
excludes seen runtime IDs with SAFEARRAY(I4) conditions, checks window ancestry,
and shares the original node/time/cancellation budgets. It requires a real NULL
before completion; a late NULL is truncated. Duplicate results, malformed IDs,
scope escape, native provider errors, or missing matches already observed by
the failed walker remain errors. No FindAll, control-view narrowing, input
retry, or OS-specific code outside the Windows PAL was introduced.

Seventeen cycle/recovery tests replace the earlier nine raw-walker tests while
retaining their scope, cancellation, budget and error invariants. The focused
accessibility suite passes 54 tests; cumulative validation passes **1,027 tests
+ 54 subtests**, `output/axis-v2-bounded-search-20260925.xml`.
The new wheel in `output/axis-v2-bounded-search-package-20260925` has SHA-256
`25283b8baf433f4a7029e7ddcf103cbe65f7e39905fdab0816647111a8da29d3`;
its isolated installed smoke passes four stdio entrypoints, four console
commands and both synthetic worker checks. The connected MCP was not restarted.

Trial 10 now verifies the Plan opening and selected Starter option through the
real engine. It subsequently stops after the Down key: Team's selected predicate
is unmet at the plan deadline, with input cleanup confirmed. This proves progress
on the reproduced traversal failure, **not a passing Edge workflow**. The
optional `--diagnose-plan-state` reads the options and ComboBox in the original
session after this failure, before teardown; it never sends a replacement key
or changes the failed job result. Two additional portable tests cover that
read-only reconciliation.

Trial 11's reconciliation has complete coverage: Starter remains selected,
Team is focused, and the Plan ComboBox already reports Team. The Down key did
have an effect. The driver now checks focused Team before Enter and still checks
the committed ComboBox value after Enter; the persistent oracle is unchanged.
No keyboard-input implementation was changed based on this test assertion error.

Trial 12 stopped earlier, before the search input: `OBSERVATION_UNAVAILABLE`,
`Native accessibility root failed (HRESULT 0x80040201)`, dispatch `not_sent`.
Microsoft identifies this HRESULT as a unavailable/destroyed or virtualized UIA
element ([UIA error codes](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-error-codes)).
The precise root invalidation timing remains unproven. Root binding now retries
read-only root acquisition at most twice more, and only for `0x80040201`, inside
a two-second cap and the caller's action deadline. It revalidates the same
process/window binding before each read; other HRESULTs and partial tree reads
are never retried. Native qualification must establish whether this helps. No
input was replayed and this failure remains in the corpus. Final cumulative validation including diagnostic and corrected
predicate tests: **1,029 tests + 54 subtests**, recorded in
`output/axis-v2-bounded-search-final-20260925.xml`. Compileall passed; the core
wheel hash above is unchanged. Full native Edge success and delivery gates are
still unproven.

## Safe test commands

```powershell
python -m pytest tests/v2 -q -p no:cacheprovider
python -m tests.v2.native_probe
# Requires an authorized interactive session; opens only the dedicated fixture.
python -m tests.v2.native_acceptance --output output/axis-v2-native/check --trials 1 --temporal --ocr --paste
```

The native acceptance harness writes `summary.json`, counts missing scenarios as
`not_run` without removing them from the denominator, and requires every trial to
verify in smoke runs below 100 trials. At 100+ trials its exit code follows the
scoped per-scenario reliability gate. Earlier report directories predate this
stricter accounting; retain their raw evidence without treating them as new-format
certification reports. Always select a new output directory.
