# AXIS v2 platform adapter contract

Status: structural admission is implemented; full native conformance remains
unqualified. No macOS/Linux adapter is certified by this document or by loading a
plugin. A capability is a promise to implement a port, not evidence of reliability.

## Host boundary

The runtime depends on the portable protocols in `cu_suite.v2.pal`. Native imports
and OS selection belong under `cu_suite.v2.platforms`, never in the runner,
perception algorithms or model transports. The built-in Windows host uses
`SupervisedPlatform`; the worker's raw Windows adapter is not the host-facing
port (its cancellation input is a shared Event, not the host's cancel method).

| Capability | Required host-facing methods |
| --- | --- |
| Always | `capabilities`, `targets`, `bind`, `release`, `close` |
| Nonempty `actions` | `dispatch`, `acquire_lease`, `release_lease`, `cancel`, `cleanup_status` |
| `accessibility` | `inspect` |
| `targeted_accessibility` | `accessibility` plus `inspect(target, query)` |
| `capture` | `capture` |
| `ocr` | `ocr` |
| `subscriptions` | `events` |
| `temporal_capture` | `capture` plus `open_observer` |

`pal_contract.validate_adapter` is the host-factory gate. It performs only reads
and method-shape checks, never test input. The runtime also uses
`read_capabilities` at discovery/admission/read/dispatch boundaries. Embedders
constructing Runtime directly are responsible for host-level `validate_adapter`
and for native resource ownership; in-process deterministic doubles are not
certified physical-input implementations.

Capability flags must be actual booleans. `actions` must be a unique list of
known native operations: never advertise engine-owned `observe`, `await`,
`await_visual`, `if`, `repeat`, `calibrate`, `watch` or `replay` as native actions.
The runtime provides these through the same runner. Capability metadata must be
finite JSON of at most 8 KiB, returned as an independent snapshot. Platform,
backend/language availability and qualification metadata may be included, but
are not accepted as proof that the qualification scenarios have passed.

An invalid profile or missing advertised port returns
`ADAPTER_CONTRACT_ERROR/not_sent`. A valid but unavailable feature returns
`CAPABILITY_UNAVAILABLE`; do not substitute another backend or silently enter an
unadvertised method. Capabilities can change when a desktop locks or a backend
becomes unavailable; never cache them as permanent input authority.

## Target data boundary

`targets()` returns a list of unique target IDs. Each target is finite UTF-8 JSON
with nonempty `target_id`, `identity` and `geometry_id` strings (at most 4096
characters), desktop-pixel `bounds: [left, top, right, bottom]` and
`client_origin: [x, y]`. Coordinates must be finite signed-32-bit-range numbers;
negative multi-monitor coordinates and collapsed windows remain valid, inverted
bounds do not. Geometry data does not itself prove that a window is actionable.
Optional title must be text; `is_active`, `minimized` and `launch_candidate` must
be booleans when present. `owner_target_id` is null/omitted or another native
target ID, never itself or the engine's reserved `desktop` session.

The runtime rejects duplicate discovery IDs, malformed geometry and a `bind(id)`
reply naming another ID before inspection/input. It copies bindings so provider
mutation cannot rewrite a session's identity in place. Rebinding must preserve
the original identity; a geometry/origin/DPI change requires a new geometry ID.
Discovery permission filtering uses one validated snapshot, not a new enumeration
per window. Native read errors remain errors, not empty successful discovery.

Focus readback checks the same original identity after dispatch. If it changed,
the result retains `sent` but does not claim a verified effect or replay input.
Close verification accepts only the adapter's explicit `TARGET_NOT_FOUND` for the
original binding; unknown/unavailable bindings are not proof of closure. These
are structural and consistency guards, not proof that a native provider reported
the true process/window or geometry; native revalidation remains mandatory.

## Behavioral obligations

- Bind to process birth plus window lifetime, not title/PID alone. Reject reused
  handles, changed identity and ambiguous launch windows. Geometry includes
  coordinate origin and DPI; revalidate before physical input and during gestures.
- Own one physical-input lease per desktop across host processes. Input dispatch
  must recheck foreground, user interference, cancellation and remaining timeout.
  No focus bypass, implicit shell or automatic forced close/save-dialog dismissal.
- A successful dispatch acknowledges input only. Report `not_sent`, `sent` and
  `unknown` honestly through AxisError and the runner. Never retry a mutation on
  transport timeout. Cleanup releases only AXIS-owned input and preserves failed
  cleanup ownership; restart is not evidence of reconciliation.
- `inspect` returns bounded elements and explicit `complete`/`truncated` coverage.
  Failure is an error, not an empty tree. Scoped queries preserve coverage and
  context identity; duplicate IDs must not resolve to an arbitrary element.
  Windows UIA COM failures return `OBSERVATION_UNAVAILABLE` with the fixed read
  stage and numeric HRESULT, without provider exception strings or partial UI
  contents. A read failure after input does not mean that input was not sent;
  the runner retains dispatch status separately. A COM failure does not trigger
  a read/mutation retry and is not automatically classified as a stale element.
  Separately, an observed filtered-tree sibling/ancestor cycle discards only that
  root's partial snapshot and switches once to a scoped raw walker. Both walks
  share the original time/node limits and authorization. Complete coverage still
  requires actual exhaustion; raw cycles or scope escapes are unavailable, while
  exhausted budgets remain truncated. This recovery never replays physical input.
- Captures return a local PIL frame of the bound window, in the advertised pixel
  geometry, without focus changes. OCR returns text/boxes/language/provenance;
  omit confidence if the backend does not supply it. Missing language/backend is
  unavailable, not an empty successful observation.
- Event gaps are explicit; events prompt verification reads rather than proving
  unchanged state. Temporal readers stay read-only, measure capture intervals,
  bound buffers/deadlines, survive input-worker occupancy, and stop before replay.
  A reader crash or lost samples never authorizes replay of a partial sequence.

## Adding an OS

1. Implement the ports in an OS-specific package and advertise only supported
   native operations/features. Prefer supervised native workers for blocking APIs.
2. Register a host-installed entry point in `axis.platforms`, named by Python's
   platform identifier (for example `linux` or `darwin`), returning the host-facing
   adapter. The Windows built-in remains selected explicitly by its factory.
   Multiple matching entries are refused; the host must choose one installation.
3. Run `python -m pytest tests/v2/test_pal_contract.py tests/v2/test_target_contract.py -q`. These are reusable
   contract rules exercised with deliberately valid/invalid doubles, **not** a
   test that automatically certifies the newly registered native adapter.
4. Apply `validate_adapter` to the real adapter, then adapt the dedicated desktop
   fixture and independent read-only oracle to that OS. Exercise the actual MCP →
   runtime → worker route. Record OS/app versions, DPI/displays and permissions.
5. Run the full native corpus: identity reuse/homonymous windows, Unicode input,
   menus/dialogs, drag interruption, clipboard ownership, held-input crash/restart,
   OCR absence, truncated trees and temporal gaps. Verify persisted app outcomes.
   Include failures, abstentions and unknowns in all 100 attempts per deterministic
   scenario; the release target remains at least 99 verified successes out of 100.
6. Publish latency, model calls/images, handles/resources and model-version/budget
   evidence. Retain `experimental` status until the native and model gates pass.

The current suite validates structure/admission, synthetic behavior and selected
Windows scenarios only. A generic OS-native fixture driver and a complete native
conformance report are still required; do not equate a green unit suite with them.
