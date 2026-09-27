"""Local AXIS operations testbench: real HTTP, SQLite persistence, and file storage.

Run: python testbench/server.py --port 8766
Only the loopback interface is exposed. No external services or credentials are used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import mimetypes
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

try:
    from .turnstile_provider import ProviderError, TurnstileProvider
except ImportError:
    from turnstile_provider import ProviderError, TurnstileProvider


ROOT = Path(__file__).resolve().parent
MAX_JSON_BYTES = 64 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PLANS = {"Starter", "Team", "Business"}
CUSTOMER_STATUSES = {"Active", "Paused"}
PRIORITIES = {"Low", "Medium", "High"}
TICKET_STATUSES = {"Backlog", "In progress", "Done"}
ASSIGNEES = {"Unassigned", "Maya Chen", "Alex Morgan"}


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def require(condition: bool, message: str, status: int = 400, code: str = "validation_error"):
    if not condition:
        raise APIError(status, code, message)


def bounded_text(value, field: str, maximum: int = 160, allow_empty: bool = False, trim: bool = True) -> str:
    require(isinstance(value, str), f"{field} must be text.")
    if trim:
        value = value.strip()
    require((allow_empty or bool(value)) and len(value) <= maximum,
            f"{field} must contain {'0' if allow_empty else '1'} to {maximum} characters.")
    require(not any(ord(char) < 32 and char not in "\n\r\t" for char in value),
            f"{field} contains unsupported control characters.")
    return value


def fields(payload: dict, allowed: set[str], required: set[str] | None = None):
    require(isinstance(payload, dict), "The request body must be a JSON object.")
    require(not (set(payload) - allowed), "The request contains unsupported fields.")
    if required:
        require(required <= set(payload), "Required fields are missing: " + ", ".join(sorted(required - set(payload))))


def customer_values(payload: dict, creating: bool = False) -> dict:
    allowed = {"name", "email", "company", "plan", "status"}
    fields(payload, allowed, {"name", "email", "company"} if creating else None)
    require(bool(payload), "Provide at least one customer field.")
    result = dict(payload)
    for key in ("name", "email", "company"):
        if key in result:
            result[key] = bounded_text(result[key], key, 254 if key == "email" else 120)
    if "email" in result:
        require(bool(EMAIL.fullmatch(result["email"])), "Enter a valid email address.")
    if creating:
        result.setdefault("plan", "Starter")
        result.setdefault("status", "Active")
    for key, choices in (("plan", PLANS), ("status", CUSTOMER_STATUSES)):
        if key in result:
            require(isinstance(result[key], str) and result[key] in choices,
                    f"{key} must be one of: {', '.join(sorted(choices))}.")
    return result


class Store:
    def __init__(self, database: str | Path):
        if str(database) != ":memory:":
            Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE, company TEXT NOT NULL,
                plan TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, priority TEXT NOT NULL,
                status TEXT NOT NULL, assignee TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                size INTEGER NOT NULL, sha256 TEXT NOT NULL, content_type TEXT NOT NULL,
                content BLOB NOT NULL, valid_contacts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                action TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        if not self.db.execute("SELECT 1 FROM settings WHERE key='run_id'").fetchone():
            self.reset()

    def close(self):
        with self.lock:
            self.db.close()

    def setting(self, key: str) -> str:
        return self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]

    def set_setting(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))

    def check_run(self, expected_run_id: str | None):
        # Call only while holding the mutation lock and its database transaction.
        # This keeps a delayed browser save from crossing a concurrent reset.
        require(expected_run_id is None or expected_run_id == self.setting("run_id"),
                "This workspace was reset. Refresh before saving your changes.", 409, "stale_run")

    def event(self, action: str, detail: str):
        at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.db.execute("INSERT INTO events(at,action,detail) VALUES (?,?,?)", (at, action, detail))

    def reset(self) -> dict:
        seed = [
            ("Maya Chen", "maya.chen@example.test", "Northstar Labs"),
            ("Alex Morgan", "alex.morgan@example.test", "Cedar Digital"),
            ("Amara Okafor", "amara.okafor@example.test", "Atlas Health"),
            ("Luca Rossi", "luca.rossi@example.test", "Meridian Studio"),
            ("Sofia Garcia", "sofia.garcia@example.test", "Harbor Logistics"),
            ("Noah Williams", "noah.williams@example.test", "Alder Analytics"),
            ("Priya Patel", "priya.patel@example.test", "Juniper Finance"),
            ("Oliver Brown", "oliver.brown@example.test", "Beacon Energy"),
            ("Emma Wilson", "emma.wilson@example.test", "Orbit Retail"),
            ("Jin Park", "jin.park@example.test", "Summit Manufacturing"),
            ("Ines Martin", "ines.martin@example.test", "Willow Education"),
            ("Ethan Davis", "ethan.davis@example.test", "Maple Networks"),
            ("Fatima Hassan", "fatima.hassan@example.test", "Horizon Media"),
            ("Leo Fischer", "leo.fischer@example.test", "Cobalt Systems"),
            ("Ana Silva", "ana.silva@example.test", "Elm Consulting"),
            ("Jack Thompson", "jack.thompson@example.test", "Brookfield Travel"),
            ("Yuki Tanaka", "yuki.tanaka@example.test", "Spruce Robotics"),
            ("Isabella Clark", "isabella.clark@example.test", "Pioneer Foods"),
            ("Omar Khalil", "omar.khalil@example.test", "Stonebridge Data"),
            ("Freya Larsen", "freya.larsen@example.test", "Aspen Mobility"),
            ("Daniel Kim", "daniel.kim@example.test", "Lakefront Security"),
            ("Grace Lee", "grace.lee@example.test", "Evergreen Design"),
            ("Samuel Taylor", "samuel.taylor@example.test", "Brightwater Tech"),
            ("Zara Ahmed", "zara.ahmed@example.test", "Foxglove Research"),
            ("Hugo Dubois", "hugo.dubois@example.test", "Westhaven Services"),
            ("Ava Robinson", "ava.robinson@example.test", "Oakline Partners"),
            ("Mateo Lopez", "mateo.lopez@example.test", "Clearview Commerce"),
            ("Nora Andersen", "nora.andersen@example.test", "Redwood Cloud"),
        ]
        tickets = [
            ("AX-101", "Invite email not received", "High", "In progress", "Alex Morgan"),
            ("AX-102", "Update billing contact", "Low", "Backlog", "Unassigned"),
            ("AX-103", "Timezone missing from activity log", "Medium", "In progress", "Maya Chen"),
            ("AX-104", "Export stalls on large reports", "Medium", "Backlog", "Unassigned"),
            ("AX-105", "Restore archived workspace", "High", "Backlog", "Alex Morgan"),
            ("AX-106", "Mobile navigation overlaps header", "Medium", "Backlog", "Unassigned"),
            ("AX-107", "CSV import skips quoted fields", "High", "In progress", "Maya Chen"),
            ("AX-108", "Add quarterly usage report", "Low", "Done", "Alex Morgan"),
            ("AX-109", "Search results need keyboard focus", "Medium", "Backlog", "Unassigned"),
        ]
        with self.lock, self.db:
            for table in ("customers", "tickets", "documents", "events", "settings"):
                self.db.execute(f"DELETE FROM {table}")
            self.db.execute("DELETE FROM sqlite_sequence WHERE name IN ('customers','documents','events')")
            for index, (name, email, company) in enumerate(seed):
                self.db.execute("INSERT INTO customers(name,email,company,plan,status) VALUES (?,?,?,?,?)",
                                (name, email, company, ("Starter", "Team", "Business")[index % 3],
                                 "Paused" if index % 7 == 6 else "Active"))
            self.db.executemany("INSERT INTO tickets VALUES (?,?,?,?,?)", tickets)
            self.set_setting("run_id", str(uuid.uuid4()))
            self.set_setting("approval_status", "Pending")
            self.set_setting("note", "")
            self.event("run.reset", "A new workspace was seeded.")
            return self.state()

    def results(self) -> list[dict]:
        with self.lock:
            customer = self.db.execute("SELECT email,plan FROM customers WHERE id=1").fetchone()
            ticket = self.db.execute("SELECT status,priority,assignee FROM tickets WHERE id='AX-104'").fetchone()
            uploaded = bool(self.db.execute("SELECT 1 FROM documents WHERE name='contacts.csv' AND valid_contacts=1").fetchone())
            approved = self.setting("approval_status") == "Approved"
            note_saved = "Approved for September rollout" in self.setting("note")
            return [
                {"id": "customer-update", "title": "Update a customer record",
                 "passed": bool(customer and customer["email"] == "maya.chen+ops@example.test" and customer["plan"] == "Team"),
                 "detail": "Maya Chen has email maya.chen+ops@example.test and the Team plan."},
                {"id": "ticket-resolution", "title": "Resolve an escalated support ticket",
                 "passed": bool(ticket and ticket["status"] == "Done" and ticket["priority"] == "High" and ticket["assignee"] == "Maya Chen"),
                 "detail": "AX-104 is Done, High priority, and assigned to Maya Chen."},
                {"id": "document-upload", "title": "Upload a valid contacts file",
                 "passed": uploaded,
                 "detail": "contacts.csv is stored with name,email headers and at least one valid contact row."},
                {"id": "approval-note", "title": "Approve a purchase and save a handover note",
                 "passed": approved and note_saved,
                 "detail": "PO-1042 is approved and the saved note contains: Approved for September rollout."},
            ]

    def state(self) -> dict:
        with self.lock:
            return {
                "run_id": self.setting("run_id"),
                "customers": [dict(row) for row in self.db.execute("SELECT * FROM customers ORDER BY id")],
                "tickets": [dict(row) for row in self.db.execute("SELECT * FROM tickets ORDER BY id")],
                "documents": [dict(row) for row in self.db.execute("SELECT id,name,size,sha256,content_type FROM documents ORDER BY id")],
                "approval": {"reference": "PO-1042", "supplier": "Northstar Supplies", "amount": 1250,
                             "currency": "EUR", "status": self.setting("approval_status")},
                "note": {"text": self.setting("note")},
                "events": [dict(row) for row in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 200")],
                "results": self.results(),
            }

    def save_customer(self, payload: dict, customer_id: int | None = None, expected_run_id: str | None = None) -> dict:
        values = customer_values(payload, creating=customer_id is None)
        with self.lock, self.db:
            self.check_run(expected_run_id)
            if customer_id is not None:
                require(self.db.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone() is not None,
                        "Customer not found.", 404, "not_found")
            try:
                if customer_id is None:
                    cursor = self.db.execute("INSERT INTO customers(name,email,company,plan,status) VALUES (?,?,?,?,?)",
                                             tuple(values[key] for key in ("name", "email", "company", "plan", "status")))
                    customer_id = cursor.lastrowid
                    action = "customer.created"
                else:
                    self.db.execute("UPDATE customers SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                                    (*values.values(), customer_id))
                    action = "customer.updated"
            except sqlite3.IntegrityError:
                raise APIError(409, "duplicate_email", "A customer with this email address already exists.") from None
            customer = dict(self.db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())
            self.event(action, f"Customer {customer_id}: {customer['name']}")
            return customer

    def save_ticket(self, ticket_id: str, payload: dict, expected_run_id: str | None = None) -> dict:
        fields(payload, {"title", "priority", "status", "assignee"})
        require(bool(payload), "Provide at least one ticket field.")
        values = dict(payload)
        if "title" in values:
            values["title"] = bounded_text(values["title"], "title", 240)
        for key, choices in (("priority", PRIORITIES), ("status", TICKET_STATUSES), ("assignee", ASSIGNEES)):
            if key in values:
                require(isinstance(values[key], str) and values[key] in choices,
                        f"{key} must be one of: {', '.join(sorted(choices))}.")
        with self.lock, self.db:
            self.check_run(expected_run_id)
            require(self.db.execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone() is not None,
                    "Ticket not found.", 404, "not_found")
            self.db.execute("UPDATE tickets SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                            (*values.values(), ticket_id))
            self.event("ticket.updated", f"Updated {ticket_id}: {', '.join(values)}")
            return dict(self.db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())

    def save_document(self, name: str, content: bytes, expected_run_id: str | None = None) -> dict:
        require(0 < len(content) <= MAX_UPLOAD_BYTES, "Files must contain 1 byte to 2 MiB.", 413, "invalid_file_size")
        name = bounded_text(name, "filename", 160)
        require(not any(char in name for char in '/\\\r\n\t\x00') and not name.startswith("."), "Use a plain filename without directories.")
        extension = Path(name).suffix.lower()
        require(extension in {".csv", ".txt", ".pdf"}, "Supported file types are CSV, TXT, and PDF.", 415, "unsupported_file")
        valid_contacts = False
        if extension == ".pdf":
            require(content.startswith(b"%PDF-") and b"%%EOF" in content[-2048:], "The file does not contain a valid PDF envelope.")
            content_type = "application/pdf"
        else:
            try:
                decoded = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise APIError(400, "invalid_file", "CSV and TXT files must use UTF-8 encoding.") from None
            require("\x00" not in decoded and bool(decoded.strip()), "The file must contain readable text.")
            content_type = "text/plain; charset=utf-8"
            if extension == ".csv":
                try:
                    rows = list(csv.reader(io.StringIO(decoded, newline=""), strict=True))
                except csv.Error:
                    raise APIError(400, "invalid_csv", "The CSV file is malformed.") from None
                require(bool(rows) and len(rows[0]) >= 2 and all(cell.strip() for cell in rows[0]), "CSV requires at least two nonempty column headers.")
                header = [cell.strip().lower() for cell in rows[0]]
                require(len(set(header)) == len(header), "CSV column headers must be unique.")
                data = [row for row in rows[1:] if row]
                require(bool(data) and all(len(row) == len(header) for row in data), "CSV requires data rows with the same number of columns as its header.")
                if "email" in header:
                    email_index = header.index("email")
                    require(all(EMAIL.fullmatch(row[email_index].strip()) for row in data), "Every CSV email must be a valid email address.")
                valid_contacts = header == ["name", "email"] and all(row[0].strip() for row in data)
                content_type = "text/csv; charset=utf-8"
        checksum = hashlib.sha256(content).hexdigest()
        with self.lock, self.db:
            self.check_run(expected_run_id)
            cursor = self.db.execute("INSERT INTO documents(name,size,sha256,content_type,content,valid_contacts) VALUES (?,?,?,?,?,?)",
                                     (name, len(content), checksum, content_type, content, int(valid_contacts)))
            self.event("document.uploaded", f"{name} ({len(content)} bytes, SHA-256 {checksum})")
            return dict(self.db.execute("SELECT id,name,size,sha256,content_type FROM documents WHERE id=?", (cursor.lastrowid,)).fetchone())

    def document(self, document_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            require(row is not None, "Document not found.", 404, "not_found")
            return dict(row)

    def approve(self, payload: dict, expected_run_id: str | None = None) -> dict:
        fields(payload, {"reference", "status"}, {"reference", "status"})
        require(payload["reference"] == "PO-1042", "Purchase order not found.", 404, "not_found")
        require(payload["status"] == "Approved", "The supported approval status is Approved.")
        with self.lock, self.db:
            self.check_run(expected_run_id)
            self.set_setting("approval_status", "Approved")
            self.event("purchase.approved", "PO-1042 approved for EUR 1,250.")
            return self.state()["approval"]

    def save_note(self, payload: dict, expected_run_id: str | None = None) -> dict:
        fields(payload, {"text", "html"}, {"text"})
        # The editor can send HTML, but only its plain-text representation is persisted.
        note = bounded_text(payload["text"], "text", 5_000, allow_empty=True, trim=False)
        with self.lock, self.db:
            self.check_run(expected_run_id)
            self.set_setting("note", note)
            self.event("note.saved", f"Saved a handover note ({len(note)} characters).")
            return {"text": note}


class TestbenchServer(ThreadingHTTPServer):
    __test__ = False
    daemon_threads = True
    block_on_close = True

    def __init__(self, address, store: Store, root: Path = ROOT):
        self.store = store
        self.root = root.resolve()
        self.turnstile = TurnstileProvider()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: TestbenchServer
    server_version = "AxisTestbench/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def send_bytes(self, status: int, body: bytes, content_type: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, payload, headers: dict | None = None):
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                        "application/json; charset=utf-8", headers)

    def body(self, maximum: int = MAX_JSON_BYTES) -> bytes:
        require(not self.headers.get("Transfer-Encoding"), "Chunked request bodies are not supported.")
        lengths = self.headers.get_all("Content-Length", [])
        require(len(lengths) <= 1, "Only one Content-Length header is allowed.")
        raw_length = self.headers.get("Content-Length", "0")
        require(raw_length.isdecimal(), "Content-Length must be a nonnegative integer.")
        length = int(raw_length)
        require(length <= maximum, f"Request body exceeds the {maximum}-byte limit.", 413, "body_too_large")
        content = self.rfile.read(length)
        require(len(content) == length, "Incomplete request body.")
        return content

    def json_body(self) -> dict:
        require(self.headers.get_content_type() == "application/json", "Send JSON using Content-Type: application/json.", 415, "unsupported_media_type")
        content = self.body()
        try:
            payload = json.loads(content.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise APIError(400, "invalid_json", "The request body must contain valid JSON.") from None
        require(isinstance(payload, dict), "The request body must be a JSON object.")
        return payload

    def dispatch(self):
        try:
            local_hosts = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
            if self.server.server_port == 80:
                local_hosts.update({"localhost", "127.0.0.1"})
            require(self.headers.get("Host", "").lower() in local_hosts,
                    "Use the localhost or 127.0.0.1 address for this application.", 403, "invalid_host")
            path = unquote(urlsplit(self.path).path)
            if self.command in {"POST", "PUT"}:
                origin = self.headers.get("Origin")
                if origin:
                    origin_parts = urlsplit(origin)
                    require(origin_parts.scheme == "http" and origin_parts.netloc == self.headers.get("Host"),
                            "Requests must come from this application origin.", 403, "origin_mismatch")
            if path.startswith("/api/"):
                self.api(path)
            elif self.command in {"GET", "HEAD"}:
                self.static(path)
            else:
                raise APIError(405, "method_not_allowed", "This HTTP method is not supported here.")
        except APIError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": error.message}})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.log_error("Unexpected request failure")
            self.send_json(500, {"error": {"code": "internal_error", "message": "The request could not be completed."}})

    def api(self, path: str):
        store = self.server.store
        expected_run_id = self.headers.get("X-Run-Id")
        if self.command in {"GET", "HEAD"}:
            if path == "/api/turnstile/config":
                return self.send_json(200, self.server.turnstile.config())
            if path == "/api/state":
                return self.send_json(200, store.state())
            if path == "/api/results":
                state = store.state()
                return self.send_json(200, {"run_id": state["run_id"], "results": state["results"]})
            if path == "/api/export":
                return self.send_json(200, store.state(), {"Content-Disposition": 'attachment; filename="axis-evidence.json"'})
            match = re.fullmatch(r"/api/documents/(\d+)", path)
            if match:
                document = store.document(int(match[1]))
                return self.send_bytes(200, document["content"], document["content_type"], {
                    "Content-Disposition": "attachment; filename*=UTF-8''" + quote(document["name"], safe=""),
                    "X-Content-SHA256": document["sha256"],
                })
        elif self.command == "POST":
            if path == "/api/turnstile/verify":
                payload = self.json_body()
                fields(payload, {"token"}, {"token"})
                token = bounded_text(payload["token"], "token", 2048)
                with store.lock:
                    store.check_run(expected_run_id)
                try:
                    result = self.server.turnstile.verify(token, urlsplit("http://" + self.headers["Host"]).hostname)
                except ProviderError as error:
                    raise APIError(503, "provider_unavailable", str(error)) from None
                # Network verification can finish after a reset; do not count that result.
                with store.lock:
                    store.check_run(expected_run_id)
                return self.send_json(200, result)
            if path == "/api/reset":
                content = self.body()
                require(not content or content.strip() == b"{}", "Reset accepts an empty body or an empty JSON object.")
                return self.send_json(200, store.reset())
            if path == "/api/customers":
                return self.send_json(201, store.save_customer(self.json_body(), expected_run_id=expected_run_id))
            if path == "/api/documents":
                content = self.body(MAX_UPLOAD_BYTES)
                filename = unquote(self.headers.get("X-Filename", ""))
                return self.send_json(201, store.save_document(filename, content, expected_run_id))
            if path == "/api/approval":
                return self.send_json(200, store.approve(self.json_body(), expected_run_id))
        elif self.command == "PUT":
            match = re.fullmatch(r"/api/customers/(\d+)", path)
            if match:
                return self.send_json(200, store.save_customer(self.json_body(), int(match[1]), expected_run_id))
            match = re.fullmatch(r"/api/tickets/(AX-\d+)", path)
            if match:
                return self.send_json(200, store.save_ticket(match[1], self.json_body(), expected_run_id))
            if path == "/api/note":
                return self.send_json(200, store.save_note(self.json_body(), expected_run_id))
        known = path in {"/api/state", "/api/results", "/api/export", "/api/reset", "/api/customers", "/api/documents", "/api/approval", "/api/note"} or bool(re.fullmatch(r"/api/(?:customers/\d+|tickets/AX-\d+|documents/\d+)", path))
        raise APIError(405 if known else 404, "method_not_allowed" if known else "not_found",
                       "This method is not supported for this endpoint." if known else "API endpoint not found.")

    def static(self, path: str):
        relative = "index.html" if path == "/" else path.lstrip("/")
        parts = relative.split("/")
        require(not any(part.startswith(".") or "\\" in part or "\x00" in part for part in parts), "Asset not found.", 404, "not_found")
        extension = Path(relative).suffix.lower()
        allowed = relative in {"index.html", "approval.html", "assets/training-popup.html"} or (len(parts) > 1 and parts[0] in {"css", "js", "assets", "vendor"} and extension in {".js", ".mjs", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".woff", ".woff2", ".csv", ".txt"})
        target = (self.server.root / relative).resolve()
        require(allowed and target.is_relative_to(self.server.root) and target.is_file(), "Asset not found.", 404, "not_found")
        mime = "text/javascript" if extension in {".js", ".mjs"} else mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_bytes(200, target.read_bytes(), mime)

    do_GET = dispatch
    do_HEAD = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch
    do_PATCH = dispatch
    do_OPTIONS = dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--db", default=":memory:", help="Optional SQLite file; defaults to a disposable in-memory run")
    args = parser.parse_args()
    require(0 <= args.port <= 65535, "Port must be between 0 and 65535.")
    store = Store(args.db)
    server = TestbenchServer(("127.0.0.1", args.port), store)
    print(f"AXIS Operations Testbench: http://localhost:{server.server_port}/", flush=True)
    print("Disposable run (memory only)" if args.db == ":memory:" else f"Database: {Path(args.db).resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
