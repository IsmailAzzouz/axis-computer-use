"""Durable native-input quarantine, independent of run journals and sessions."""
import sqlite3
import time
import uuid
from pathlib import Path

from .contracts import AxisError


class SafetyLatch:
    def __init__(self, path, scope):
        self.path, self.scope = str(path), scope
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS latch (scope TEXT PRIMARY KEY, owner TEXT NOT NULL, pid INTEGER NOT NULL, armed INTEGER NOT NULL, updated REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS reconciliations (scope TEXT, owner TEXT, reason TEXT, at REAL)")

    def _connect(self):
        # Callers explicitly close connections as well as committing transactions.
        return _Database(self.path)

    def status(self):
        with self._connect() as db:
            row = db.execute("SELECT owner,pid,armed,updated FROM latch WHERE scope=?", (self.scope,)).fetchone()
        return {"scope": self.scope, "state": "quarantined" if row and row[2] else "clear",
                "owner": row[0] if row and row[2] else None,
                "pid": row[1] if row and row[2] else None}

    def arm(self, pid, *, abandoned=False):
        owner = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner,armed FROM latch WHERE scope=?", (self.scope,)).fetchone()
            if row and row[1]:
                if abandoned:
                    return row[0]
                raise AxisError("INPUT_UNRECONCILED", "Prior native input owner remains quarantined; operator reconciliation required")
            db.execute("INSERT OR REPLACE INTO latch VALUES (?,?,?,?,?)", (self.scope, owner, pid, 1, time.time()))
        return owner

    def clear(self, owner, *, reason):
        if reason not in ("normal_cleanup", "operator_acknowledged"):
            raise ValueError("Invalid reconciliation reason")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE latch SET armed=0,updated=? WHERE scope=? AND owner=? AND armed=1",
                                 (time.time(), self.scope, owner)).rowcount
            if changed != 1:
                raise AxisError("RECONCILIATION_CONFLICT", "Input owner changed or was already reconciled; inspect status again")
            db.execute("INSERT INTO reconciliations VALUES (?,?,?,?)", (self.scope, owner, reason, time.time()))


class _Database:
    def __init__(self, path):
        self.db = None
        try:
            self.db = sqlite3.connect(path, timeout=1)
            self.db.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error as exc:
            if self.db is not None: self.db.close()
            raise AxisError("SAFETY_STORE_UNAVAILABLE", "Persistent input safety store unavailable; input disabled") from exc

    def __enter__(self): return self.db

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None: self.db.commit()
            else: self.db.rollback()
        except sqlite3.Error as exc:
            raise AxisError("SAFETY_STORE_UNAVAILABLE", "Persistent input safety update failed; input disabled") from exc
        finally:
            self.db.close()
        if kind is not None and issubclass(kind, sqlite3.Error):
            raise AxisError("SAFETY_STORE_UNAVAILABLE", "Persistent input safety operation failed; input disabled") from value
