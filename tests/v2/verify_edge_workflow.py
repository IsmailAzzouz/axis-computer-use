"""Read-only acceptance oracle for the local testbench; never supplies AXIS input."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Oracle does not follow redirects")


def verify(base_url, fixture, *, expected_run_id):
    """Bind evidence to the run created before input, never a run discovered after it."""
    if not isinstance(expected_run_id, str) or not expected_run_id.strip():
        raise ValueError("An independently recorded pre-input run ID is required")
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.path not in {"", "/"} or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("Only the local disposable testbench is supported")
    # Reject malformed ports before opening anything; never send local evidence
    # via proxy environment settings or a server-controlled redirect.
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid testbench port")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    def read(path):
        with opener.open(base_url.rstrip("/")+path, timeout=5) as response:
            data = response.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError("Oracle response too large")
        return data
    fixture = Path(fixture)
    with fixture.open("rb") as stream:
        content = stream.read(MAX_BYTES+1)
    if len(content) > MAX_BYTES:
        raise ValueError("Oracle fixture too large")
    state = json.loads(read("/api/state"))
    customers = [c for c in state["customers"] if c["name"] == "Maya Chen"]
    documents = [d for d in state["documents"] if d["name"] == fixture.name]
    digest = hashlib.sha256(content).hexdigest()
    run_matches = state["run_id"] == expected_run_id
    document = documents[0] if len(documents) == 1 else {}
    document_id = document.get("id")
    valid_document_id = type(document_id) is int and document_id > 0
    checks = {"expected_run": run_matches,
        "customer_persisted": len(customers) == 1 and all(customers[0].get(k) == v for k, v in {
        "email": "maya.chen+ops@example.test", "company": "AXIS élève 中文 😀", "plan": "Team"}.items()),
        "upload_metadata": valid_document_id and document.get("sha256") == digest and document.get("size") == len(content),
        "upload_bytes": run_matches and valid_document_id and hashlib.sha256(read(f"/api/documents/{document_id}")).hexdigest() == digest}
    # A reset can reuse numeric document IDs. Bracket the download with a fresh
    # state read so a reset or changed evidence cannot produce a passing report.
    final_state = json.loads(read("/api/state"))
    checks["stable_evidence"] = (final_state["run_id"] == expected_run_id
        and [c for c in final_state["customers"] if c["name"] == "Maya Chen"] == customers
        and [d for d in final_state["documents"] if d["name"] == fixture.name] == documents)
    return {"source": "Independent read-only local HTTP and fixture hash", "run_id": state["run_id"],
            "expected_run_id": expected_run_id, "final_run_id": final_state["run_id"],
            "checks": checks, "passed": all(checks.values()), "fixture_sha256": digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--expected-run-id", required=True, help="Run ID recorded before native actions")
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[2]/"testbench/assets/contacts.csv"
    report = verify(args.url, fixture, expected_run_id=args.expected_run_id)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
