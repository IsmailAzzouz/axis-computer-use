"""Oracle tests use synthetic HTTP evidence, never claim native Edge execution."""
import copy
import hashlib
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.v2 import verify_edge_workflow as oracle


FIXTURE = Path(__file__).resolve().parents[2]/"testbench/assets/contacts.csv"


class EdgeOracleTests(unittest.TestCase):
    def setUp(self):
        self.content = FIXTURE.read_bytes()
        self.state = {"run_id": "current-trial", "customers": [{
            "name": "Maya Chen", "email": "maya.chen+ops@example.test",
            "company": "AXIS élève 中文 😀", "plan": "Team"}], "documents": [{
            "id": 1, "name": FIXTURE.name, "sha256": hashlib.sha256(self.content).hexdigest(),
            "size": len(self.content)}]}

    def check(self, state=None, final=None, content=None, expected="current-trial"):
        state = self.state if state is None else state
        final = state if final is None else final
        bodies = [json.dumps(state).encode()]
        documents = state["documents"]
        if (state["run_id"] == expected and len(documents) == 1
                and type(documents[0]["id"]) is int and documents[0]["id"] > 0):
            bodies.append(self.content if content is None else content)
        bodies.append(json.dumps(final).encode())
        opener = Mock()
        opener.open.side_effect = [io.BytesIO(body) for body in bodies]
        with patch.object(oracle, "build_opener", return_value=opener):
            report = oracle.verify("http://127.0.0.1:8766", FIXTURE, expected_run_id=expected)
        return report, opener

    def test_exact_current_evidence_passes_and_only_gets_expected_paths(self):
        report, opener = self.check()
        self.assertTrue(report["passed"])
        self.assertEqual([call.args[0] for call in opener.open.call_args_list], [
            "http://127.0.0.1:8766/api/state", "http://127.0.0.1:8766/api/documents/1",
            "http://127.0.0.1:8766/api/state"])

    def test_prior_trial_with_all_correct_values_fails_without_downloading(self):
        report, opener = self.check(expected="different-trial")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["expected_run"])
        self.assertEqual(opener.open.call_count, 2)

    def test_reset_during_download_fails_even_if_new_data_identical(self):
        final = copy.deepcopy(self.state)
        final["run_id"] = "reset-trial"
        report, _ = self.check(final=final)
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["stable_evidence"])

    def test_customer_changes_during_read_fail(self):
        final = copy.deepcopy(self.state)
        final["customers"][0]["company"] = "another writer"
        self.assertFalse(self.check(final=final)[0]["passed"])

    def test_document_changes_during_read_fail(self):
        final = copy.deepcopy(self.state)
        final["documents"][0]["id"] = 2
        self.assertFalse(self.check(final=final)[0]["passed"])

    def test_corrupt_bytes_fail_despite_correct_metadata(self):
        self.assertFalse(self.check(content=b"corrupt")[0]["checks"]["upload_bytes"])

    def test_wrong_metadata_hash_or_size_fail(self):
        for key, value in [("sha256", "incorrect"), ("size", len(self.content)+1)]:
            with self.subTest(key=key):
                state = copy.deepcopy(self.state)
                state["documents"][0][key] = value
                self.assertFalse(self.check(state=state)[0]["passed"])

    def test_duplicate_customer_or_document_fail(self):
        for key in ("customers", "documents"):
            with self.subTest(key=key):
                state = copy.deepcopy(self.state)
                state[key].append(copy.deepcopy(state[key][0]))
                self.assertFalse(self.check(state=state)[0]["passed"])

    def test_invalid_document_ids_do_not_download(self):
        for document_id in (True, 1.5, "1", -1, 0):
            with self.subTest(document_id=document_id):
                state = copy.deepcopy(self.state)
                state["documents"][0]["id"] = document_id
                report, opener = self.check(state=state)
                self.assertFalse(report["passed"])
                self.assertEqual(opener.open.call_count, 2)

    def test_requires_pre_input_identity(self):
        for expected in (None, "", " ", 3):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                oracle.verify("http://127.0.0.1:8766", FIXTURE, expected_run_id=expected)

    def test_rejects_nonlocal_or_decorated_urls_before_network(self):
        for url in ("https://localhost", "http://example.test", "http://127.0.0.1/path",
                    "http://user:secret@localhost", "http://localhost?x=1",
                    "http://localhost#x", "http://localhost:bad", "http://localhost:0"):
            with self.subTest(url=url), patch.object(oracle, "build_opener") as opener:
                with self.assertRaises(ValueError):
                    oracle.verify(url, FIXTURE, expected_run_id="current-trial")
                opener.assert_not_called()

    def test_oversized_response_fails(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b" "*(oracle.MAX_BYTES+1))
        with patch.object(oracle, "build_opener", return_value=opener), self.assertRaises(ValueError):
            oracle.verify("http://localhost", FIXTURE, expected_run_id="current-trial")

    def test_real_http_ignores_proxy_and_refuses_redirects(self):
        requested = []
        state, content = self.state, self.content
        class Handler(BaseHTTPRequestHandler):
            redirect = False
            def log_message(self, *args):
                pass
            def do_GET(self):
                requested.append(self.path)
                if self.redirect:
                    self.send_response(302)
                    self.send_header("Location", "/must-not-follow")
                    self.end_headers()
                    return
                body = json.dumps(state).encode() if self.path == "/api/state" else content
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                with patch.dict("os.environ", {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
                    self.assertTrue(oracle.verify(url, FIXTURE, expected_run_id="current-trial")["passed"])
                Handler.redirect = True
                with self.assertRaisesRegex(ValueError, "redirects"):
                    oracle.verify(url, FIXTURE, expected_run_id="current-trial")
                self.assertNotIn("/must-not-follow", requested)
            finally:
                server.shutdown()
                thread.join(2)

    def test_real_testbench_persistence_is_read_only_and_reset_invalidates_evidence(self):
        from testbench.server import Store, TestbenchServer
        store = Store(":memory:")
        server = TestbenchServer(("127.0.0.1", 0), store)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            # Synthetic fixture setup for oracle validation, not a native trial.
            run_id = store.state()["run_id"]
            store.save_customer({"email": "maya.chen+ops@example.test", "company": "AXIS élève 中文 😀",
                                 "plan": "Team"}, 1, run_id)
            store.save_document(FIXTURE.name, self.content, run_id)
            before = store.state()
            url = f"http://127.0.0.1:{server.server_port}"
            self.assertTrue(oracle.verify(url, FIXTURE, expected_run_id=run_id)["passed"])
            self.assertEqual(store.state(), before)
            store.reset()
            report = oracle.verify(url, FIXTURE, expected_run_id=run_id)
            self.assertFalse(report["passed"])
            self.assertFalse(report["checks"]["expected_run"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            store.close()
