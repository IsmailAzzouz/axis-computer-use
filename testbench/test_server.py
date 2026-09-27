"""HTTP integration tests. Run: python -m unittest discover -s testbench -p test_server.py -v"""

import concurrent.futures
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from server import MAX_JSON_BYTES, MAX_UPLOAD_BYTES, Store, TestbenchServer


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "state.sqlite3"
        self.root = Path(self.temp.name) / "public"
        (self.root / "js").mkdir(parents=True)
        (self.root / "index.html").write_text("<!doctype html><title>Operations</title>", encoding="utf-8")
        (self.root / "js" / "app.js").write_text("const ready = true;", encoding="utf-8")
        (self.root / "server.py").write_text("private", encoding="utf-8")
        (self.root / ".data").mkdir()
        (self.root / ".data" / "secret.txt").write_text("private", encoding="utf-8")
        self.start()

    def start(self):
        self.store = Store(self.database)
        self.server = TestbenchServer(("127.0.0.1", 0), self.store, self.root)
        self.server.RequestHandlerClass.log_message = lambda *args: None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def request(self, method, path, payload=None, raw=None, headers=None):
        request_headers = dict(headers or {})
        body = raw
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
            parsed = json.loads(content) if content and "application/json" in response_headers.get("Content-Type", "") else content
            return response.status, parsed, response_headers
        finally:
            conn.close()

    def state(self):
        status, result, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        return result

    def upload(self, name="contacts.csv", content=b"name,email\r\nAmina Yusuf,amina@example.test\r\n"):
        return self.request("POST", "/api/documents", raw=content, headers={"X-Filename": name, "Content-Type": "text/csv"})

    def test_seed_is_realistic_and_results_initially_incomplete(self):
        state = self.state()
        self.assertGreaterEqual(len(state["customers"]), 25)
        self.assertGreaterEqual(len(state["tickets"]), 8)
        self.assertEqual(state["customers"][0]["email"], "maya.chen@example.test")
        self.assertEqual(state["note"], {"text": ""})
        self.assertFalse(any(item["passed"] for item in state["results"]))
        self.assertEqual(len(state["results"]), 4)

    def test_end_to_end_tasks_file_roundtrip_and_restart_persistence(self):
        initial_id = self.state()["run_id"]
        self.assertEqual(self.request("PUT", "/api/customers/1", {"email": "maya.chen+ops@example.test", "plan": "Team"})[0], 200)
        self.assertEqual(self.request("PUT", "/api/tickets/AX-104", {"status": "Done", "priority": "High", "assignee": "Maya Chen"})[0], 200)
        content = b'name,email\r\n"Yusuf, Amina",amina@example.test\r\n'
        status, document, _ = self.upload(content=content)
        self.assertEqual(status, 201)
        self.assertEqual(document["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(document["size"], len(content))
        status, downloaded, headers = self.request("GET", f"/api/documents/{document['id']}")
        self.assertEqual((status, downloaded), (200, content))
        self.assertEqual(headers["X-Content-SHA256"], document["sha256"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.request("POST", "/api/approval", {"reference": "PO-1042", "status": "Approved"})[0], 200)
        self.assertFalse(self.state()["results"][-1]["passed"])
        self.assertEqual(self.request("PUT", "/api/note", {"text": "Approved for September rollout", "html": "<script>alert(1)</script>"})[0], 200)
        before = self.state()
        self.assertTrue(all(item["passed"] for item in before["results"]))
        self.assertNotIn("html", before["note"])
        self.assertEqual(len(before["events"]), 6)
        self.stop()
        self.start()
        after = self.state()
        self.assertEqual(after, before)
        self.assertEqual(after["run_id"], initial_id)
        self.assertEqual(self.request("GET", f"/api/documents/{document['id']}")[1], content)
        status, evidence, headers = self.request("GET", "/api/export")
        self.assertEqual((status, evidence), (200, after))
        self.assertIn("axis-evidence.json", headers["Content-Disposition"])
        status, results, _ = self.request("GET", "/api/results")
        self.assertEqual(results, {"run_id": initial_id, "results": after["results"]})

    def test_invalid_customer_and_duplicate_email_do_not_mutate(self):
        initial = self.state()
        for payload, status in [({"email": "invalid"}, 400), ({"plan": "Enterprise"}, 400),
                                ({"id": 7}, 400), ({"status": []}, 400), ({}, 400),
                                ({"name": "Changed", "email": "ALEX.MORGAN@example.test"}, 409)]:
            with self.subTest(payload=payload):
                actual, error, _ = self.request("PUT", "/api/customers/1", payload)
                self.assertEqual(actual, status)
                self.assertIn("message", error["error"])
                self.assertEqual(self.state(), initial)
        self.assertEqual(self.request("PUT", "/api/customers/999", {"name": "Someone"})[0], 404)
        self.assertEqual(self.request("POST", "/api/customers", {"name": "New", "email": "new@example.test"})[0], 400)
        self.assertEqual(self.state(), initial)

    def test_parallel_customer_creation_has_unique_ids_and_duplicate_is_serialized(self):
        def create(index):
            return self.request("POST", "/api/customers", {"name": f"Partner {index}", "company": "Example Partners", "email": f"partner{index}@example.test"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(create, range(8)))
        self.assertTrue(all(status == 201 for status, _, _ in replies))
        self.assertEqual(len({row["id"] for _, row, _ in replies}), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(create, [99] * 4))
        self.assertEqual(sorted(status for status, _, _ in replies), [201, 409, 409, 409])
        self.assertEqual(len(self.state()["customers"]), 37)

    def test_invalid_ticket_approval_and_note_do_not_mutate(self):
        initial = self.state()
        cases = [
            ("PUT", "/api/tickets/AX-104", {"status": "Closed"}, 400),
            ("PUT", "/api/tickets/AX-104", {"assignee": "Unknown"}, 400),
            ("PUT", "/api/tickets/AX-999", {"status": "Done"}, 404),
            ("POST", "/api/approval", {"reference": "PO-9999", "status": "Approved"}, 404),
            ("POST", "/api/approval", {"reference": "PO-1042", "status": "Rejected"}, 400),
            ("PUT", "/api/note", {"html": "<p>Only HTML</p>"}, 400),
            ("PUT", "/api/note", {"text": "a" * 5001}, 400),
        ]
        for method, path, payload, expected in cases:
            with self.subTest(path=path, payload=str(payload)[:80]):
                self.assertEqual(self.request(method, path, payload)[0], expected)
                self.assertEqual(self.state(), initial)

    def test_note_preserves_whitespace_and_enforces_actual_character_limit(self):
        note = "  Approved for September rollout\n\n  Follow up with Maya.\n"
        status, saved, _ = self.request("PUT", "/api/note", {"text": note})
        self.assertEqual((status, saved), (200, {"text": note}))
        self.assertEqual(self.state()["note"]["text"], note)
        self.assertEqual(self.request("PUT", "/api/note", {"text": "x" * 5000})[0], 200)
        before = self.state()
        self.assertEqual(self.request("PUT", "/api/note", {"text": "x" * 5001})[0], 400)
        self.assertEqual(self.state(), before)

    def test_invalid_uploads_do_not_create_files_or_pass_results(self):
        initial = self.state()
        for name, content, expected in [
            ("contacts.csv", b"name,email\nAmina,broken\n", 400),
            ("contacts.csv", b"name,email\n", 400),
            ("contacts.csv", b"name,email\nAmina,amina@example.test,extra", 400),
            ("contacts.csv", b'name,email\n"unclosed,amina@example.test', 400),
            ("contacts.csv", b"\xff\xfe", 400),
            ("../contacts.csv", b"name,email\nAmina,amina@example.test", 400),
            ("contacts.csv", b"", 413),
            ("contacts.exe", b"executable", 415),
            ("contacts.pdf", b"actually plain text", 400),
        ]:
            with self.subTest(name=name, content=content):
                self.assertEqual(self.upload(name, content)[0], expected)
                self.assertEqual(self.state(), initial)
        self.assertEqual(self.upload("other.csv")[0], 201)
        self.assertFalse(self.state()["results"][2]["passed"])
        self.assertEqual(self.upload("contacts.txt", b"name,email\nAmina,amina@example.test")[0], 201)
        self.assertFalse(self.state()["results"][2]["passed"])

    def test_reset_replaces_run_and_clears_persisted_work(self):
        before = self.state()
        self.request("PUT", "/api/customers/1", {"plan": "Team"})
        _, document, _ = self.upload()
        self.request("PUT", "/api/note", {"text": "Draft"})
        status, after, _ = self.request("POST", "/api/reset", {})
        self.assertEqual(status, 200)
        self.assertNotEqual(after["run_id"], before["run_id"])
        for field in ("customers", "tickets", "documents", "approval", "note", "results"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(len(after["events"]), 1)
        self.assertEqual(self.request("GET", f"/api/documents/{document['id']}")[0], 404)
        self.stop()
        self.start()
        self.assertEqual(self.state(), after)

    def test_http_errors_body_limits_and_origin_do_not_mutate(self):
        initial = self.state()
        self.assertEqual(self.request("PUT", "/api/customers/1", raw=b"not JSON", headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("PUT", "/api/customers/1", raw=b'{"name":NaN}', headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("PUT", "/api/customers/1", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("PUT", "/api/customers/1", raw=b"[]", headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("PUT", "/api/customers/1", raw=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(MAX_JSON_BYTES + 1)})[0], 413)
        self.assertEqual(self.request("POST", "/api/documents", raw=b"", headers={"Content-Length": str(MAX_UPLOAD_BYTES + 1)})[0], 413)
        self.assertEqual(self.request("POST", "/api/reset", {}, headers={"Origin": "https://unrelated.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/reset", {}, headers={"Host": "unrelated.example", "Origin": "http://unrelated.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "unrelated.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/reset", {"unexpected": True})[0], 400)
        self.assertEqual(self.request("DELETE", "/api/customers/1")[0], 405)
        self.assertEqual(self.request("GET", "/api/missing")[0], 404)
        self.assertEqual(self.state(), initial)

    def test_reset_rejects_stale_run_writes_across_all_mutation_routes(self):
        old_run = self.state()["run_id"]
        self.assertEqual(self.request("PUT", "/api/note", {"text": "Before reset"}, headers={"X-Run-Id": old_run})[0], 200)
        # Reset itself deliberately accepts the previous run identifier.
        self.assertEqual(self.request("POST", "/api/reset", {}, headers={"X-Run-Id": old_run})[0], 200)
        after_reset = self.state()
        self.assertNotEqual(after_reset["run_id"], old_run)
        cases = [
            ("POST", "/api/customers", {"name": "Late customer", "email": "late@example.test", "company": "Example"}),
            ("PUT", "/api/customers/1", {"email": "maya.chen+ops@example.test", "plan": "Team"}),
            ("PUT", "/api/tickets/AX-104", {"status": "Done", "priority": "High", "assignee": "Maya Chen"}),
            ("POST", "/api/approval", {"reference": "PO-1042", "status": "Approved"}),
            ("PUT", "/api/note", {"text": "Approved for September rollout"}),
        ]
        for method, path, payload in cases:
            with self.subTest(path=path):
                status, error, _ = self.request(method, path, payload, headers={"X-Run-Id": old_run})
                self.assertEqual((status, error["error"]["code"]), (409, "stale_run"))
                self.assertEqual(self.state(), after_reset)
        status, error, _ = self.request("POST", "/api/documents", raw=b"name,email\nAmina,amina@example.test\n",
                                        headers={"X-Run-Id": old_run, "X-Filename": "contacts.csv", "Content-Type": "text/csv"})
        self.assertEqual((status, error["error"]["code"]), (409, "stale_run"))
        self.assertEqual(self.state(), after_reset)
        self.assertEqual(self.request("PUT", "/api/note", {"text": "Current run draft"},
                                      headers={"X-Run-Id": after_reset["run_id"]})[0], 200)
        self.assertEqual(self.state()["note"]["text"], "Current run draft")

    def test_static_server_only_exposes_public_assets(self):
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/js/app.js")[0], 200)
        for path in ("/server.py", "/.data/secret.txt", "/js/../server.py", "/js/%2e%2e/server.py", "/js/%5c../server.py", "/test_server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        status, body, headers = self.request("HEAD", "/")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)


if __name__ == "__main__":
    unittest.main()
