from concurrent.futures import ThreadPoolExecutor
import pytest
from cu_suite.v2.contracts import AxisError, MAX_BYTES
from cu_suite.v2.pages import Pages, size


def test_ocr_word_pages_are_complete_immutable_and_bounded():
    pages = Pages()
    words = [{"text": "élève中文"*10, "line": i//8, "bounds": [0, 0, 10, 10]} for i in range(200)]
    first = pages.create("words", words, {"language": "fr", "session_id": "s"}, "s")
    words.clear()
    result, collected = first, []
    while True:
        assert size(result) < MAX_BYTES
        collected.extend(result["words"])
        assert result["text"] == " ".join(w["text"] for w in result["words"])
        if not result["next_cursor"]:
            break
        result = pages.read(result["next_cursor"], session_id="s")
    assert len(collected) == 200


def test_cursor_scoped_and_nested_metadata_cannot_mutate_snapshot():
    pages = Pages()
    first = pages.create("targets", [{"title": "x"*2000}]*12, {"nested": {"value": "original"}})
    cursor = first["next_cursor"]
    first["nested"]["value"] = "changed"
    assert pages.read(cursor, kind="targets")["nested"]["value"] == "original"
    with pytest.raises(AxisError):
        pages.read(cursor, session_id="foreign")
    with pytest.raises(AxisError):
        pages.read(cursor, kind="words")


def test_concurrent_initial_pages_and_snapshot_budget():
    pages = Pages()
    def create(i):
        return pages.create("targets", [{"id": i}], {})["targets"][0]["id"]
    with ThreadPoolExecutor(max_workers=12) as workers:
        assert list(workers.map(create, range(300))) == list(range(300))
    assert len(pages._snapshots) == 16
    with pytest.raises(AxisError, match="snapshot budget"):
        pages.create("targets", [{"text": "x"*2_100_000}], {})
