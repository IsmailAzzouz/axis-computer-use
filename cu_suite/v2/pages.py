"""Bounded immutable pages for non-tree observations and target discovery."""
import copy
import json
import threading
import uuid
from .contracts import AxisError, MAX_BYTES


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


class Pages:
    def __init__(self):
        self._snapshots = {}
        self._lock = threading.RLock()

    def create(self, kind, items, metadata, session_id=None):
        snapshot = {"kind": kind, "items": items, "metadata": metadata, "session_id": session_id}
        if size(snapshot) > 2*1024*1024:
            raise AxisError("OUTPUT_TOO_LARGE", "Observation exceeds snapshot budget; narrow the region or scope")
        key = uuid.uuid4().hex
        with self._lock:
            self._snapshots[key] = copy.deepcopy(snapshot)
            while len(self._snapshots) > 16:
                self._snapshots.pop(next(iter(self._snapshots)))
            return self.read(f"page:{key}:0", kind=kind, session_id=session_id)

    def read(self, cursor, *, kind=None, session_id=None):
        try:
            prefix, key, index = cursor.split(":")
            index = int(index)
            with self._lock:
                snapshot = self._snapshots[key]
            if prefix != "page" or index < 0 or index > len(snapshot["items"]): raise ValueError()
        except (ValueError, KeyError):
            raise AxisError("INVALID_CURSOR", "Invalid or expired snapshot cursor")
        if (kind and kind != snapshot["kind"]) or session_id != snapshot["session_id"]:
            raise AxisError("INVALID_CURSOR", "Cursor belongs to another tool/session")
        field = snapshot["kind"]
        result = {**copy.deepcopy(snapshot["metadata"]), field: []}
        # OCR returns both word boxes and a compact text view; reserve half the
        # budget for that view and transport envelope.
        limit = MAX_BYTES//2 if field == "words" else MAX_BYTES-512
        while index < len(snapshot["items"]):
            item = snapshot["items"][index]
            if size({**result, field: result[field]+[item]}) > limit:
                if not result[field]:
                    raise AxisError("OUTPUT_TOO_LARGE", "One item exceeds the output budget")
                break
            result[field].append(copy.deepcopy(item))
            index += 1
        result["next_cursor"] = f"page:{key}:{index}" if index < len(snapshot["items"]) else None
        if field == "words":
            result["text"] = " ".join(word["text"] for word in result[field])
        return result
