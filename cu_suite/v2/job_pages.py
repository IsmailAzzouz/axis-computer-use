"""Bounded job pages. Oversized individual values use explicit JSON fragments."""
import copy
import hashlib
import json
from urllib.parse import quote, unquote
from .contracts import AxisError, MAX_BYTES


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def size(value):
    return len(encode(value).encode("utf-8"))


def bounded_metadata(metadata):
    job_id = metadata["job_id"]
    result = copy.deepcopy(metadata)
    if size(result) > 2048:
        error = result.get("error") or {}
        result["error"] = {"code": str(error.get("code", "RESULT_METADATA"))[:128],
                           "message": str(error.get("message", ""))[:256],
                           "dispatch": error.get("dispatch", "unknown"), "truncated": True}
        result["result_data"] = {"encoding": "json", "cursor": f"json:{job_id}:all:0"}
    return result


def page_result(metadata, steps, cursor=None):
    job_id = metadata["job_id"]
    full = {**metadata, "steps": steps}
    result = bounded_metadata(metadata)

    def descriptor(value, prefix):
        text = encode(value).encode("utf-8")
        return {"encoding": "json", "utf8_bytes": len(text), "sha256": hashlib.sha256(text).hexdigest(), "cursor": prefix+":0"}

    def step_summary(step, index):
        name = str(step.get("id", ""))
        return {"id": name[:128], "id_truncated": len(name) > 128, "op": str(step.get("op", "unknown"))[:64],
                "dispatch": step["dispatch"], "verification": step["verification"],
                "step_data": descriptor(step, f"json:{job_id}:{index}")}

    def integer(value, length, *, end=False):
        index = int(value)
        if index < 0 or index > length or (not end and index == length): raise ValueError()
        return index

    def fragment_step(index):
        step = steps[index]
        if step.get("op") == "observe" and step.get("output", {}).get("data_state") == "unavailable":
            raise AxisError("OBSERVATION_EXPIRED", "Ephemeral readback expired; cannot continue fragments of the previous snapshot")
        return step

    try:
        parts = cursor.split(":") if cursor else ["steps", job_id, "0"]
        mode, bound = parts[:2]
        if bound != job_id: raise ValueError()
        if mode == "steps" and len(parts) == 3:
            index = integer(parts[2], len(steps), end=True)
            page = []
            while index < len(steps):
                item = copy.deepcopy(steps[index])
                if size(item) > MAX_BYTES-3072:
                    for name, value in item.get("output", {}).items():
                        if isinstance(value, list) and len(name) <= 64:
                            item["output"][name] = {"count": len(value), "cursor": f"items:{job_id}:{index}:{quote(name, safe='')}:0"}
                    if size(item) > MAX_BYTES-3072:
                        item = step_summary(steps[index], index)
                if size({**result, "steps": page+[item]}) > MAX_BYTES-2048:
                    if page: break
                    item = step_summary(steps[index], index)
                page.append(item)
                index += 1
            return {**result, "steps": page, "next_cursor": f"steps:{job_id}:{index}" if index < len(steps) else None}
        if mode == "items" and len(parts) == 5:
            index = integer(parts[2], len(steps))
            name = unquote(parts[3])
            values = fragment_step(index)["output"][name]
            if not isinstance(values, list): raise ValueError()
            start = integer(parts[4], len(values), end=True)
            page = []
            while start < len(values):
                item = values[start]
                if size({**result, "output": page+[item]}) > MAX_BYTES-2048:
                    if page: break
                    prefix = f"itemjson:{job_id}:{index}:{quote(name, safe='')}:{start}"
                    item = {"item_data": descriptor(item, prefix)}
                page.append(copy.deepcopy(item))
                start += 1
            return {**result, "output": page, "next_cursor": f"items:{job_id}:{index}:{parts[3]}:{start}" if start < len(values) else None}
        if mode == "json" and len(parts) == 4:
            if parts[2] == "all" and metadata["status"] in ("accepted", "running"):
                raise AxisError("RESULT_PENDING", "Wait for terminal status before collecting full-result fragments")
            if parts[2] == "all":
                for index in range(len(steps)):
                    fragment_step(index)
                value = full
            else:
                value = fragment_step(integer(parts[2], len(steps)))
        elif mode == "itemjson" and len(parts) == 6:
            values = fragment_step(integer(parts[2], len(steps)))["output"][unquote(parts[3])]
            if not isinstance(values, list): raise ValueError()
            value = values[integer(parts[4], len(values))]
        else:
            raise ValueError()
        text = encode(value)
        start = integer(parts[-1], len(text), end=True)
        prefix = ":".join(parts[:-1])
        low, high = start, len(text)
        while low < high:
            end = (low+high+1)//2
            if size({**result, "encoding": "json", "data": text[start:end], "next_cursor": f"{prefix}:{end}"}) <= MAX_BYTES-128: low = end
            else: high = end-1
        if low == start and start < len(text):
            raise AxisError("OUTPUT_TOO_LARGE", "Job metadata leaves no fragment budget")
        return {**result, "encoding": "json", "data": text[start:low],
                "next_cursor": f"{prefix}:{low}" if low < len(text) else None}
    except (ValueError, KeyError, IndexError, TypeError):
        raise AxisError("INVALID_CURSOR", "Cursor is malformed or belongs to another job/output")
