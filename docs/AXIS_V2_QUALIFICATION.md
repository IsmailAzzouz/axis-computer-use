# AXIS v2 qualification: evidence and remaining gates

Status: **not certified**. The fixture harness exercises a declared native corpus;
it is not an independent model evaluation, an Excel/Edge certification, or proof
that every safety invariant was independently observed.

## Run the declared fixture corpus

From an explicitly authorized interactive Windows session, using a **new** output
directory for each run:

```powershell
python -m tests.v2.native_acceptance --output output/axis-v2-native/fixture-run-001 --trials 100 --temporal --ocr --paste
```

The harness launches only its isolated native fixture. It does not operate user
documents. Its application policy allows the fixture's Python executable and
does not grant force-termination authority. A noninteractive desktop produces an
unfinished report, zero executed trials and no input; it is never worked around.
`--focus-method caption_click` is an explicit alternate configuration, not a
silent retry. Record it separately; do not merge configurations into a score.

The actual route is **in-process MCP handler → authenticated TCP → runtime → native
worker**. Separate subprocess tests exercise the public stdio entrypoints; this
fixture command alone does not prove the stdio host integration end to end.

Before native setup, the harness records the intended trial count and scenario
set. Existing output directories are refused, preserving old failures and avoiding
stale oracle reuse. `summary.json` and `report.json` are replaced atomically after
each trial. `trace.jsonl` is flushed before each request and after its response;
lost responses retain the original job idempotency key. Never rerun that mutation
with a new key to recover it. Inspect the original job and fixture first.

## What gets counted

The required set always contains launch, focus, Unicode input plus submit, native
events, right-click/menu, slider value, drag and normal close. The switches add
OCR, controlled paste and calibrated Simon. An early failure does not shrink that
set or remove later scenarios from the planned denominator.

| Outcome | Meaning |
| --- | --- |
| `verified` | Action completed with `effects_verified: true` and independent oracle true; reads require a valid successful response and their expected fact. |
| `failed` | Error, partial/cancelled action, failed expected fact or completed-but-unverified input. |
| `abstained` | Recognized safety/capability refusal before any input was sent. Still in the denominator. |
| `unknown` | Lost/incomplete result, uncertain cleanup, or claimed effect without available oracle evidence. |
| `not_run` | No attempt recorded for this scheduled scenario. Still in the denominator. |

A runtime **verified-effect claim** contradicted by the independent oracle counts
as a false success. A completed dispatch-only action is not such a claim and
cannot pass. A successful read alone does not assert the harness's expected
business fact: a missing expected event/text fails that scenario, without being
mislabeled as a false business-success claim. Purpose-built `verification_scope`
groups can prove a demonstration/accepted replay while individual clicks remain
unobservable; the runtime checks their exact membership before setting the global
verified flag. Unrelated or uncertain input is not covered by those groups.
`CLIPBOARD_UNSUPPORTED/not_sent` is a safety abstention: unsupported clipboard
formats are preserved, never cleared to make the benchmark pass.

The fixture checks launch PID against its independent file, focus against the
foreground process, and close against persisted fixture state. Unicode, submit,
context-menu acceptance, slider, drag and Simon use fixture state unavailable to
AXIS. Event and OCR checks use declared expected fixture content, not secret game
sequences. Simon gets a public zone calibration; AXIS derives pulses from local
captures. These observations are limited to the fixture, not other apps.

`meets_scenario_reliability_gate` requires a finished run, all planned trial
records, at least 100 scheduled trials, **at least 99% verified per required
scenario**, and zero measured false successes. The intersection of fully passing
trials is reported separately. Different scenarios may fail on different trials;
none of those failures is discarded. An unfinished run never passes the gate.

`release_certified` remains false: this narrow gate does not establish the whole
approved release corpus, absence of wrong-target input/unauthorized retries across
all scenarios, resource endurance, other applications or model usability.

## Metrics and reproducibility

`tool_calls` measures attempted MCP calls, including those whose reply is lost.
`model_calls` is zero: the driver is scripted. Model/version/settings/budget fields
remain null, not fictional model results. Image responses are counted; no token
savings or model-token consumption is inferred from bytes or preset constants.

Tool latency reports measured count, total, p50 and p95 (nearest rank). It includes
harness response logging overhead. OS/Python, focus method, capability profile,
scenario set and a hash of v2 Python/PowerShell, fixture, harness and accounting
sources are retained. Target/DPI geometry and exact requests/results are in the
trace. Collect actual model usage and native resource/handle samples separately;
this change does not claim those measurements are implemented.

## Coverage still required for delivery

| Requirement | Current evidence route | Remaining work |
| --- | --- | --- |
| Basic fixture, gestures, OCR, calibrated Simon | `native_acceptance` | Run current build's full 100-trial configurations; temporal fault/variation corpus remains broader than this scenario. |
| Homonymous windows, cancellation, save dialog | `native_lifecycle` | Integrate repeated per-scenario accounting and current-build qualification. |
| Focus across controlled windows | `native_focus_acceptance` | Repeated current-build evidence and independent safety accounting. |
| Excel ranges, formulas, save/reopen | `native_excel_smoke` passed once with edit/commit predicates and independent saved OOXML oracle | Range-selection coverage, locale/configuration matrix and 100-trial gate; Excel required. |
| Edge forms, tabs, scrolling and file dialogs | `native_edge_smoke` drives customer editing, address-bar navigation and native upload; `verify_edge_workflow` independently reads persistence | Qualify the driver natively and add the full tabs/scrolling/context-menu corpus plus repeated trials. Browser-plugin QA is not native AXIS evidence. |
| Native crash cleanup and resource endurance | Worker/unit tests, synthetic sampler endurance | Real held-key/button/clipboard crash/restart and resource measurements. |
| Tiny text-only and multimodal model usability | Executable help examples and schema/transport tests | Actual model runs with declared versions, settings, budgets, calls/images/tokens. |

The removed V1 `benchmarks.runner` was a synthetic reference/trajectory benchmark,
not this qualification harness. Its historical preset token estimates are not measured
efficiency evidence and must not be used for a v2 release claim.

## Independent Edge persistence oracle

`python -m tests.v2.verify_edge_workflow --url http://127.0.0.1:PORT --expected-run-id PRE_INPUT_RUN_ID --report REPORT.json`
checks the customer fields, uploaded fixture size/hash and independently downloaded
bytes. Record the disposable testbench run ID **before** native actions. A run ID
discovered only after execution cannot bind evidence to the attempted trial.

The oracle makes only local HTTP GET requests, ignores proxy environment variables
and refuses redirects. A second state read brackets the download: a reset or a
change in the relevant customer/document evidence prevents a passing report.
This is a final persistence check, not proof of how the workflow was performed,
per-action native correctness, or protection from changes after the final read.
Its synthetic/unit HTTP tests do not count as native Edge qualification.

## Native Edge customer/upload smoke

`python -m tests.v2.native_edge_smoke --output output/axis-v2-native/NEW-DIRECTORY`
requires an authorized interactive Windows session, Edge and the explicit
French-Edge/English-testbench UI profile. It creates a disposable local server
on an ephemeral port, records its run ID before input, and opens a new isolated
guest profile through AXIS. The driver edits Maya Chen's email, Unicode company
and plan, reopens and rereads the form, navigates using the native address bar,
uploads the known contacts CSV through the owned file dialog and checks persisted
fields and bytes before closing its own window normally.

Actions traverse MCP, TCP, the runner and the native worker. The file-dialog
trigger is explicitly dispatch-only; its original `effects_verified: false`
result is preserved alongside a separate owned-dialog observation. It is not
silently promoted to verified input. All other action plans require verification.
An unknown reply, ambiguous target, failed predicate or oracle stops the trial;
no mutation is retried and no surviving window is force-closed on failure.

The output directory must be new. `report.json` checkpoints jobs, observations,
oracle binding and failure/cleanup information; `trace.jsonl` flushes each request
before dispatch. `testbench.sqlite3` retains only this isolated trial's data for
post-run diagnostics, including after failure. The report includes hashes of runner, harness and testbench
sources. This is a scripted single-workflow smoke (`model_calls: 0`), not an
independent model-usage benchmark, complete Edge corpus or 100-trial certification.
The report always sets `release_certified: false`.

## Native Excel text/formula smoke

`python -m tests.v2.native_excel_smoke --output output/axis-v2-native/NEW-DIRECTORY`
requires an explicitly authorized interactive Windows session and French Excel.
It opens a new `/x` instance only, validates profile selectors, writes four cells
with edit-buffer and committed-value predicates, saves a fresh workbook, checks
raw persisted OOXML, closes, reopens, rereads and closes the test window. The eight
write/commit steps use one `axis.run`; no Excel object-model authoring or images.

The output directory must not exist. Original MCP requests/keys are flushed to
`trace.jsonl` before dispatch; `report.json` checkpoints each stage. Any ambiguous,
unknown, paginated or unverified action stops the smoke without retry. Failure
does not force-close or discard a surviving workbook. Inspect the trace first.

This is a scripted smoke, not range-selection coverage, independent-model
evaluation, resource endurance, or the 100-trial qualification gate. The report
always sets `release_certified: false`. Only the saved-file oracle is independent
of AXIS UI observations; no per-action independent oracle is claimed.
