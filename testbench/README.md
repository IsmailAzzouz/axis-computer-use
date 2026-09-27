# AXIS Training Ground

A local operations app for exercising browser automation against realistic workflows.
It uses native browser controls and APIs: HTML forms and validation, modal `dialog`,
HTML Drag and Drop / DataTransfer, file inputs and downloads, an iframe, and a Web
Component with an open Shadow DOM and a plaintext contenteditable editor. Requests
use a local HTTP API. Local exercises need no CDN, external account, API key, or
npm install. The optional, explicitly loaded Turnstile widget connects to Cloudflare.

Start from the repository root:

```powershell
python testbench/server.py
```

Open **http://127.0.0.1:8766/**. Runs are disposable and use memory by default;
restarting the server seeds a fresh run. `Reset run` also resets the exercises.
For an optional longer-lived run, use `--db testbench/.data/run.sqlite3`.
The old `python -m http.server` on port 8765 only serves files; use the new server.

## Exercises

| Workflow | What AXIS must handle | Completion target |
| --- | --- | --- |
| Customer account | Search, sorting, pagination, native modal focus, text/email fields, select, validation, asynchronous save | Maya's email becomes `maya.chen+ops@example.test`, plan `Team` |
| Support triage | Find ticket, edit dialog, priority/assignee controls, native drag/drop or keyboard-accessible edit | AX-104: High, Maya Chen, Done |
| Documents | Download fixture, OS file picker or file drop, upload, browser download | Valid `contacts.csv` upload; compare downloaded bytes for round-trip verification |
| Purchase approval | Enter an iframe, required checkbox, submit, discover/edit a Shadow DOM textbox | PO-1042 approved; note contains `Approved for September rollout` |

`assets/contacts.csv` is a small UTF-8 fixture. Invalid inputs and duplicate emails
produce real validation errors. Uploads are limited to 2 MiB and CSV/TXT/PDF.
The UI never labels a user or agent "human" based on pointer motion. CAPTCHA
practice and browser/desktop drills remain available alongside these workflows.

## Test AXIS

Run AXIS in the same interactive desktop session as the browser, then navigate to
the lab. Perform the assignments through AXIS controls; do not use the HTTP mutation
API to solve them. The result view and `/api/results` can verify final outcomes,
but cannot identify which automation engine performed the actions.

```python
import os
from cu_suite import AxisClient

print(AxisClient.help())  # Offline guide; not proof that the desktop host is ready.
client = AxisClient(token=os.environ["AXIS_TOKEN"])
print(client.call("axis.targets", {}))
# Choose an authorized window by its returned identity, not only its title.
print(client.call("axis.observe", {"target_id": "TARGET_FROM_TARGETS"}))
# Keep the returned session_id; submit ordered actions through axis.run.
```

For native file dialogs, discover the owned dialog and observe its explicit target.
Use `axis.help`, `axis.targets`, `axis.observe`, `axis.run`, `axis.job` and
`axis.capture`; see [the v2 API](../docs/AXIS_V2_API.md). Keep AXIS action traces
with the exported evidence. `dispatch: sent` alone does not prove effect
verification. Browser reload preserves the current run
while the server stays up; restarting the default server clears it.

Customer/ticket forms stay busy until acknowledged save and readback settle.
If readback fails after acknowledgement, the dialog closes with a distinct warning,
and the acknowledged record remains available locally. The UI does not submit the
write again automatically. A rejected write leaves the form open for correction.

## Application verification

```powershell
python testbench/live_verification.py
# Or independently:
python -m unittest discover -s testbench -p test_server.py -v
node --test testbench/form_save.test.mjs
node testbench/browser_verification.mjs
```

The browser checks require Node.js 22+ and Chrome, Brave, or Edge. They start their
own server, temporary database, and isolated headless Chromium profile. Reports
and screenshots go to `.browser-test/`; the browser profile is removed afterward.
Use `--browser PATH` or `--python PATH` to override runtime discovery.

These checks test the application through Chromium CDP. They are **not evidence
that AXIS's desktop accessibility adapter has passed**. File selection uses CDP's
file-input facility; it does not exercise an OS file picker. The runner labels its
synthetic drag fixture separately from pointer-driven drag coverage.
The seven save-flow tests use deferred reads to reproduce the reopen race and
distinguish rejected writes from failed readback. `test_form_save.py` includes
them in the pytest suite when Node.js is installed; otherwise it explicitly skips.

Reference semantics: [native dialogs](https://developer.mozilla.org/en-US/docs/Web/API/HTMLDialogElement/showModal),
[HTML Drag and Drop](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API),
[Shadow DOM](https://developer.mozilla.org/en-US/docs/Web/API/Web_components/Using_shadow_DOM).
