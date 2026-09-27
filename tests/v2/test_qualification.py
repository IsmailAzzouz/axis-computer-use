"""Qualification accounting tests, not evidence of native reliability."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from benchmarks.qualification import classify, latency_summary, summarize


def scenario(*, oracle=True, status="completed", verified=True, dispatch="sent", code=None):
    return {"oracle_met": oracle, "result": {"version": "2.0", "status": status,
        "effects_verified": verified, "steps": [{"dispatch": dispatch}],
        "error": {"code": code, "dispatch": dispatch} if code else None}}


@pytest.mark.parametrize("data,outcome,false_success", [
    (scenario(), "verified", False),
    (scenario(verified=False), "failed", False),
    (scenario(oracle=False), "failed", True),
    (scenario(oracle=None), "unknown", False),
    (scenario(oracle=1), "unknown", False),
    (scenario(status="unknown", dispatch="unknown"), "unknown", False),
    (scenario(status="completed", dispatch="unknown"), "unknown", False),
    (scenario(status="running"), "unknown", False),
    (scenario(status="failed", verified=False, dispatch="not_sent", code="FOCUS_DENIED"), "abstained", False),
    (scenario(status="failed", verified=False, dispatch="not_sent", code="CLIPBOARD_UNSUPPORTED"), "abstained", False),
    (scenario(status="partial", verified=False, code="FOCUS_DENIED"), "failed", False),
    (scenario(status="failed", verified=False, dispatch="not_sent", code="INVALID_REQUEST"), "failed", False),
    (None, "not_run", False), ({}, "unknown", False),
])
def test_result_classes_keep_sent_distinct_from_verified(data, outcome, false_success):
    assert classify(data, "action") == {"outcome": outcome, "false_success": false_success}


def test_read_only_observation_uses_its_independent_oracle():
    assert classify({"result": {"version": "2.0", "events": []}, "oracle_met": True}, "read")["outcome"] == "verified"
    assert classify({"result": {"version": "2.0"}, "oracle_met": False}, "read") == {"outcome": "failed", "false_success": False}
    assert classify({"result": {}, "oracle_met": True}, "read")["outcome"] == "unknown"


def test_unknown_cleanup_overrides_verified_effect():
    data = scenario()
    data["result"]["cleanup"] = {"state": "unknown"}
    assert classify(data, "action")["outcome"] == "unknown"


def test_no_scenario_or_failed_trial_is_dropped_from_denominator():
    reports = [{"trial": 0, "scenarios": {"text": scenario()}}]
    summary = summarize(reports, {"text": "action", "drag": "action"}, 100, finished=True)
    assert summary["scenarios"]["text"]["verified_rate"] == .01
    assert summary["scenarios"]["text"]["not_run"] == 99
    assert summary["scenarios"]["drag"]["not_run"] == 100
    assert not summary["meets_scenario_reliability_gate"] and not summary["release_certified"]


def test_threshold_is_per_scenario_not_intersection_of_successful_trials():
    reports = [{"trial": i, "scenarios": {"text": scenario(), "drag": scenario()}} for i in range(100)]
    reports[0]["scenarios"]["text"] = scenario(verified=False, status="failed")
    reports[1]["scenarios"]["drag"] = scenario(verified=False, status="failed")
    summary = summarize(reports, {"text": "action", "drag": "action"}, 100, finished=True)
    assert summary["verified_trials"] == 98
    assert summary["meets_scenario_reliability_gate"] and not summary["release_certified"]
    assert not summarize(reports, {"text": "action", "drag": "action"}, 100)["meets_scenario_reliability_gate"]


def test_one_false_success_rejects_gate_despite_99_verified_successes():
    reports = [{"trial": i, "scenarios": {"text": scenario(oracle=i != 0)}} for i in range(100)]
    summary = summarize(reports, {"text": "action"}, 100, finished=True)
    assert summary["scenarios"]["text"]["verified"] == 99
    assert summary["false_successes"] == 1 and not summary["meets_scenario_reliability_gate"]


@pytest.mark.parametrize("reports", [
    [{"trial": 0, "scenarios": {}}]*2, [{"trial": -1, "scenarios": {}}],
    [{"trial": True, "scenarios": {}}], [{"trial": 1, "scenarios": {}}],
])
def test_invalid_trial_ids_cannot_inflate_success_count(reports):
    with pytest.raises(ValueError):
        summarize(reports, {"text": "action"}, 1)


@pytest.mark.parametrize("count", [0, -1, True, 10001])
def test_invalid_trial_counts_rejected(count):
    with pytest.raises(ValueError):
        summarize([], {"text": "action"}, count)


def test_summary_does_not_rewrite_source_evidence():
    reports = [{"trial": 0, "scenarios": {"text": scenario()}}]
    before = copy.deepcopy(reports)
    summarize(reports, {"text": "action"}, 1, finished=True)
    assert reports == before


def test_tool_latency_is_measured_and_missing_samples_stay_missing():
    assert latency_summary([]) == {"count": 0, "total_seconds": 0, "p50_seconds": None, "p95_seconds": None}
    assert latency_summary([.3, .1, .2]) == {"count": 3, "total_seconds": pytest.approx(.6), "p50_seconds": .2, "p95_seconds": .3}


@pytest.mark.parametrize("count", ["0", "-1", "10001"])
def test_cli_invalid_count_never_enters_native_setup(tmp_path, monkeypatch, count):
    from . import native_acceptance as harness
    monkeypatch.setattr(sys, "argv", ["native_acceptance", "--output", str(tmp_path/"run"), "--trials", count])
    monkeypatch.setattr(harness, "create_platform", lambda: pytest.fail("Must reject before creating native adapter"))
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2 and not (tmp_path/"run").exists()


def test_existing_evidence_directory_is_never_overwritten(tmp_path, monkeypatch):
    from . import native_acceptance as harness
    original = tmp_path/"report.json"
    original.write_text("preserve previous failed trial", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["native_acceptance", "--output", str(tmp_path)])
    monkeypatch.setattr(harness, "create_platform", lambda: pytest.fail("No native setup"))
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2 and original.read_text(encoding="utf-8") == "preserve previous failed trial"


def test_unavailable_desktop_retains_all_scheduled_scenarios(tmp_path, monkeypatch):
    from . import native_acceptance as harness
    closed = []
    pal = SimpleNamespace(capabilities=lambda: {"interactive": False}, close=lambda: closed.append(True))
    monkeypatch.setattr(harness, "create_platform", lambda: pal)
    output = tmp_path/"run"
    monkeypatch.setattr(sys, "argv", ["native_acceptance", "--output", str(output), "--trials", "100", "--temporal", "--ocr", "--paste"])
    with pytest.raises(RuntimeError, match="Interactive desktop unavailable"):
        harness.main()
    summary = json.loads((output/"summary.json").read_text())
    assert summary["planned_trials"] == 100 and summary["recorded_trials"] == 0
    assert all(s["not_run"] == 100 and s["verified"] == 0 for s in summary["scenarios"].values())
    assert {"launch", "focus", "close", "ocr", "paste", "simon"} <= summary["scenarios"].keys()
    assert summary["metrics"]["model_calls"] == summary["metrics"]["tool_calls"] == 0
    assert not summary["finished"] and not summary["meets_scenario_reliability_gate"]
    assert closed == [True]


@pytest.mark.parametrize("lost_reply", [False, True])
def test_post_dispatch_interruption_retains_unknown_attempt_and_original_key(tmp_path, monkeypatch, lost_reply):
    # Actual MCP handler/TCP/runtime route, synthetic PAL. No native application
    # is launched, no oracle is written and Windows foreground methods must not run.
    from . import native_acceptance as harness
    from .fake_platform import FakePlatform
    pal = FakePlatform()
    capabilities = pal.capabilities()
    pal.capabilities = lambda: {**capabilities, "interactive": True}
    monkeypatch.setattr(harness, "create_platform", lambda: pal)
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace())
    if lost_reply:
        actual_server = harness.MCPServer
        class LoseLaunchReply(actual_server):
            def handle_request(self, request):
                reply = super().handle_request(request)
                if request.get("params", {}).get("name") == "axis.run":
                    raise ConnectionError("Lost after dispatch")
                return reply
        monkeypatch.setattr(harness, "MCPServer", LoseLaunchReply)
    output = tmp_path/"run"
    monkeypatch.setattr(sys, "argv", ["native_acceptance", "--output", str(output)])
    assert harness.main() == 1
    summary = json.loads((output/"summary.json").read_text())
    assert summary["scenarios"]["launch"]["unknown"] == 1
    assert summary["scenarios"]["focus"]["not_run"] == 1
    assert summary["metrics"]["model_calls"] == 0 and summary["metrics"]["tool_calls"] == 2
    assert summary["metrics"]["tool_latency"]["count"] == 2
    assert len(pal.calls) == 1 and pal.calls[0][0] == "open_app"
    events = [json.loads(line) for line in (output/"trace.jsonl").read_text().splitlines()]
    requests = [e["request"] for e in events if e["phase"] == "request"]
    assert len(requests) == 2 and requests[-1]["params"]["arguments"]["idempotency_key"]
    assert "token" not in json.dumps(requests).lower()
    if lost_reply:
        assert events[-1]["phase"] == "interrupted" and events[-1]["request_id"] == requests[-1]["id"]
