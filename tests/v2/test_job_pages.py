import hashlib
import json
import pytest
from cu_suite.v2.contracts import AxisError, MAX_BYTES
from cu_suite.v2.job_pages import encode, page_result


META = {"job_id": "one", "status": "completed", "completed_steps": 1, "executed_steps": 1,
        "error": None, "effects_verified": True}


def step(value):
    return {"id": "a", "op": "watch", "dispatch": "sent", "verification": "met", "output": value}


def collect(steps, cursor, field, metadata=META):
    values, seen = [], set()
    while cursor:
        assert cursor not in seen
        seen.add(cursor)
        result = page_result(metadata, steps, cursor)
        assert len(encode({"version": "2.0", **result}).encode()) <= MAX_BYTES
        assert result[field]
        values.append(result[field])
        cursor = result["next_cursor"]
        assert len(seen) < 100
    return values


def test_large_list_pages_preserve_every_item_and_job_identity():
    values = [{"name": "red", "index": i} for i in range(2000)]
    steps = [step({"events": values})]
    first = page_result(META, steps)
    cursor = first["steps"][0]["output"]["events"]["cursor"]
    pages = collect(steps, cursor, "output")
    assert [item for page in pages for item in page] == values
    with pytest.raises(AxisError, match="another job"):
        page_result({**META, "job_id": "two"}, steps, cursor)


@pytest.mark.parametrize("value", ["中文😀"*10000, {"message": '"\\\n'*12000}], ids=["unicode", "escaped-json"])
def test_oversized_individual_list_item_is_not_an_infinite_empty_page(value):
    steps = [step({"events": [value, "tail"]})]
    cursor = page_result(META, steps)["steps"][0]["output"]["events"]["cursor"]
    pages = collect(steps, cursor, "output")
    items = [item for page in pages for item in page]
    descriptor = items[0]["item_data"]
    text = "".join(collect(steps, descriptor["cursor"], "data"))
    assert json.loads(text) == value
    assert hashlib.sha256(text.encode()).hexdigest() == descriptor["sha256"]
    assert items[1] == "tail"


def test_large_step_metadata_and_large_error_remain_retrievable():
    steps = [{**step({"huge": "x"*30000}), "id": "中文😀"*3000}]
    meta = {**META, "error": {"code": "TEST", "message": "é"*30000, "dispatch": "sent"}}
    first = page_result(meta, steps)
    assert len(encode(first).encode()) < MAX_BYTES
    assert first["job_id"] == "one"
    text = "".join(collect(steps, first["steps"][0]["step_data"]["cursor"], "data", meta))
    assert json.loads(text) == steps[0]
    result = json.loads("".join(collect(steps, first["result_data"]["cursor"], "data", meta)))
    assert result == {**meta, "steps": steps}


@pytest.mark.parametrize("cursor", ["0", "steps:other:0", "steps:one:-1", "steps:one:2", "items:one:0:missing:0", "json:one:0:-1"])
def test_malformed_cursors_cannot_read_other_output(cursor):
    with pytest.raises(AxisError): page_result(META, [step({})], cursor)
