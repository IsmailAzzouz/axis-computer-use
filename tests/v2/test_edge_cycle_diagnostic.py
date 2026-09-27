from copy import deepcopy
import json

import pytest

from . import native_uia_search_probe as probe
from .native_edge_smoke import PLAN, diagnose_cycle, diagnose_plan_state
from types import SimpleNamespace as NS


def report():
    return {"passed": False, "stages": {
        "launch": {"native_jobs": [{"steps": [{"output": {"process_id": 123}}]}]},
        "save_customer": {"native_jobs": [{"error": {"code": "OBSERVATION_UNAVAILABLE", "message": "Native accessibility traversal cycle"},
            "steps": [{"id": "open_plan", "op": "click", "dispatch": "sent"}],
            "cleanup": {"state": "confirmed", "owned_input_count": 0, "clipboard_pending": False}}]}}}


def test_read_only_probe_keeps_original_failed_result(tmp_path, monkeypatch):
    value = report()
    original = deepcopy(value["stages"])
    def supervise(pid, query, cached, callback, *, same_client):
        assert (pid, query, cached, same_client) == (123, "list_items", False, True)
        callback({"input_sent": False, "progress": {"calls": 1}})
        assert json.loads((tmp_path/"report.json").read_text())["uia_cycle_diagnostic"]["progress"]["calls"] == 1
        return {"input_sent": False, "result": {"complete": True}}
    monkeypatch.setattr(probe, "supervise", supervise)
    diagnose_cycle(value, tmp_path)
    assert value["stages"] == original and value["passed"] is False
    assert value["uia_cycle_diagnostic"]["input_sent"] is False


@pytest.mark.parametrize("change", [
    lambda job: job.update(error={"code": "FOCUS_DENIED"}),
    lambda job: job["steps"][-1].update(dispatch="unknown"),
    lambda job: job["steps"][-1].update(id="another_click"),
    lambda job: job["cleanup"].update(state="failed"),
    lambda job: job["cleanup"].update(owned_input_count=1),
    lambda job: job["cleanup"].update(clipboard_pending=True),
])
def test_no_probe_on_unrelated_failure_or_unconfirmed_cleanup(tmp_path, monkeypatch, change):
    value = report()
    change(value["stages"]["save_customer"]["native_jobs"][0])
    monkeypatch.setattr(probe, "supervise", lambda *a, **k: pytest.fail("Diagnostic must not start"))
    diagnose_cycle(value, tmp_path)
    assert "uia_cycle_diagnostic" not in value


@pytest.mark.parametrize("pid", [True, "123", 0, -1])
def test_bad_pid_cannot_select_another_process(tmp_path, monkeypatch, pid):
    value = report()
    value["stages"]["launch"]["native_jobs"][0]["steps"][0]["output"]["process_id"] = pid
    monkeypatch.setattr(probe, "supervise", lambda *a, **k: pytest.fail("Diagnostic must not start"))
    with pytest.raises(ValueError, match="process identity"):
        diagnose_cycle(value, tmp_path)


def test_plan_reconciliation_reads_only_original_session_and_keeps_failure(tmp_path):
    value = report()
    value["stages"]["save_customer"]["native_jobs"][0]["steps"][-1]["id"] = "choose_team"
    original = deepcopy(value["stages"])
    calls = []
    host = NS(call=lambda tool, args: calls.append((tool, args)) or {"coverage": "truncated"})
    diagnose_plan_state(host, "original-session", value, tmp_path)
    assert calls == [("axis.observe", {"session_id": "original-session", "query": query})
                     for query in ({"role": "ListItem"}, PLAN)]
    assert value["passed"] is False and value["stages"] == original
    assert all(item["result"]["coverage"] == "truncated" for item in value["plan_failure_observations"])


def test_plan_reconciliation_does_not_inspect_while_inputs_remain_held(tmp_path):
    value = report()
    job = value["stages"]["save_customer"]["native_jobs"][0]
    job["steps"][-1]["id"] = "choose_team"
    job["cleanup"]["owned_input_count"] = 1
    host = NS(call=lambda *_: pytest.fail("No diagnostic yet"))
    diagnose_plan_state(host, "original-session", value, tmp_path)
    assert "plan_failure_observations" not in value
