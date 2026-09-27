# Running the v2 client examples

`run_simon.py` and `play_sequence.py` no longer operate a native facade or spawn
one process per click. Each submits **one** `axis.run` request to the existing,
authorized resident broker. Neither starts a host, changes permissions, chooses
a window by title or installs a desktop bridge.

Use the configured AXIS Python environment and the same broker token environment
as your host. See [host setup](AXIS_V2_API.md). Requests are UTF-8 JSON files
(256 KiB maximum), or stdin with `--request -`. The request supplies its own
session and idempotency key. Preserve that original file/key for reconciliation.

```powershell
.venv-axis/Scripts/python.exe play_sequence.py --request sequence.json --dry-run
.venv-axis/Scripts/python.exe play_sequence.py --request sequence.json
.venv-axis/Scripts/python.exe run_simon.py --request round.json --dry-run
.venv-axis/Scripts/python.exe run_simon.py --request round.json
```

`--dry-run` checks shared schemas, plan semantics and static budgets only. It does
not prove host connectivity, permissions, current target geometry or calibration.
`--port` and `--token-env` select the broker connection without putting a token
in request JSON. Dynamic replay steps remain subject to the runner's 256-step cap.

## Explicit sequence

`play_sequence.py` requires canonical `steps`, not a recipe. Discover selectors or
fresh coordinates first; replace the example session/selector with actual values.
Repeated actions are separate steps, not deduplicated commands. There are no
hardcoded color coordinates, implicit delays, automatic submit clicks or retries.
Use observed `await` conditions where the target requires readiness between inputs.

```json
{
  "session_id": "returned-window-session",
  "idempotency_key": "unique-sequence-request",
  "steps": [
    {"id": "focus", "op": "focus"},
    {
      "id": "write",
      "op": "type_text",
      "args": {"at": {"selector": {"role": "Edit", "name": "Input"}}, "text": "élève 中文 😀", "replace": true},
      "postcondition": {"kind": "value", "selector": {"role": "Edit", "name": "Input"}, "expected": "élève 中文 😀"}
    },
    {"id": "read", "op": "observe", "args": {"query": {"role": "Edit"}}}
  ]
}
```

## One calibrated Simon round

Before running `run_simon.py`, bind the intended game window and calibrate it
through `axis.run` using the discovered `calibrate` operation schema. Define
probe regions against the current window image while all zones are idle. A
profile is tied to its session, target identity and geometry; a resize or restart
requires new calibration. Do not reuse coordinates from the archived v1 scripts.

The client requires `sequence-memory.play@1` and a profile ID already returned by
that host. It does not secretly submit calibration or focus requests. Focus the
authorized window beforehand if necessary. Choose actual player-turn and round-
acceptance predicates; merely finding the game container is not acceptance.

```json
{
  "session_id": "returned-game-session",
  "idempotency_key": "unique-round-request",
  "recipe": "sequence-memory.play@1",
  "recipe_args": {
    "profile_id": "returned-calibration-id",
    "trigger": {
      "id": "start",
      "op": "click",
      "args": {"at": {"selector": {"name": "Start", "role": "Button"}}},
      "verification": "dispatch_only"
    },
    "player_turn": {"kind": "value", "selector": {"name": "Status"}, "expected": "your turn"},
    "accepted": {"kind": "value", "selector": {"name": "Status"}, "expected": "accepted"}
  }
}
```

The runtime arms local detectors, triggers the demonstration, preserves repeated
colors, waits for the player cue, then replays and checks acceptance. It sends no
video to the model. Unknown games still require appropriate calibration/detectors.
This is one round, not a continuously armed multi-round implementation.

Sample timestamps use the monotonic high-resolution performance counter. Some
Python/Windows combinations expose a roughly 15.6 ms `monotonic()` deadline clock;
equal coarse-clock ticks must not be mistaken for lost captures. Actual excessive
sample gaps, missing probe data or incomplete sequences still abort without replay.
The trigger currently runs synchronously inside the watcher, so a sufficiently
slow trigger can still cause a genuine gap; fast native-game qualification remains
open. Changing the clock does not solve that architectural limitation.

## Read results accurately

Exit 0 means the request returned without an explicit failure, not that a long
job has finished or every individual effect was verified. Inspect `status`, each
step's `verification`, `effects_verified`, and any pagination cursors. The current
Simon recipe can verify the demonstration and accepted round as explicit
`verification_scope` groups. Individual trigger/replay clicks remain unobservable;
`effects_verified` can be true when their verified parents cover exactly those
acknowledged inputs. Unknown/failed clicks or unrelated dispatch-only steps still
prevent a fully verified result. This is group proof, not per-click observation.
Do not relabel those individual effects as verified.

For an accepted/running job, use `axis.job`. For lost acknowledgements, use the
original idempotency key; the examples never resend automatically. Large/non-ASCII
keys are not echoed in error output; recover them from the original request.
Closing a client does not undo or automatically cancel a submitted plan.

Older script bodies remain archived as non-executable text in `docs/legacy/`.
The examples' simulator tests are transport/logic evidence, not native desktop
or model-usability certification.
