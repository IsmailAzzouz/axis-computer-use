"""Evidence accounting for a declared corpus, never a native/model certification.

The independent harness supplies oracle results. Nothing here supplies hidden
state to the engine or turns successful input dispatch into business success.
"""
from collections import Counter
import math


OUTCOMES = ("verified", "failed", "abstained", "unknown", "not_run")
ABSTENTIONS = frozenset({"CAPABILITY_UNAVAILABLE", "POLICY_DENIED", "FOCUS_DENIED",
    "ACTIVATION_UNAVAILABLE", "DESKTOP_BUSY", "HOST_NOT_CONFIGURED", "TARGET_OCCLUDED",
    "INPUT_UNRECONCILED", "STALE_TARGET", "STALE_ELEMENT", "STALE_ELEMENT_GEOMETRY",
    "CLIPBOARD_UNSUPPORTED"})


def classify(scenario, kind):
    """Return outcome + false-success flag; missing evidence never passes."""
    if scenario is None:
        return {"outcome": "not_run", "false_success": False}
    if not isinstance(scenario, dict) or not isinstance(scenario.get("result"), dict):
        return {"outcome": "unknown", "false_success": False}
    result = scenario["result"]
    oracle = scenario.get("oracle_met")
    status = result.get("status")
    error = result.get("error") or {}
    if not isinstance(error, dict):
        return {"outcome": "unknown", "false_success": False}
    steps = result.get("steps", [])
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return {"outcome": "unknown", "false_success": False}
    claims_success = result.get("version") == "2.0" and not error and (
        (kind == "action" and status == "completed" and result.get("effects_verified") is True) or
        (kind == "read" and status is None))
    # A successful read does not assert the harness's expected business fact.
    false_success = kind == "action" and claims_success and oracle is False
    dispatches = [error.get("dispatch")] + [step.get("dispatch") for step in steps]
    cleanup = result.get("cleanup") or {}
    uncertain = (status in ("unknown", "accepted", "running") or "unknown" in dispatches or
                 not isinstance(cleanup, dict) or cleanup.get("state") in ("unknown", "failed"))
    if uncertain:
        outcome = "unknown"
    elif claims_success and oracle is True:
        outcome = "verified"
    elif claims_success and oracle is not False:
        outcome = "unknown"  # Verification claim without independent readback.
    elif (status == "failed" and error.get("code") in ABSTENTIONS and
          error.get("dispatch") == "not_sent" and
          all(step.get("dispatch") == "not_sent" for step in steps)):
        outcome = "abstained"
    elif status in ("completed", "partial", "failed", "cancelled") or oracle is False or error:
        outcome = "failed"
    else:
        outcome = "unknown"
    return {"outcome": outcome, "false_success": false_success}


def summarize(reports, required, planned_trials, *, finished=False):
    """Every scheduled trial stays in each scenario's denominator, even if absent.

    `required` is a predeclared {scenario: action|read} mapping, not inferred from
    the subset of results that happened to arrive. IDs must be unique and in range.
    """
    if type(planned_trials) is not int or not 1 <= planned_trials <= 10000:
        raise ValueError("planned_trials must be between 1 and 10000")
    if (not isinstance(required, dict) or not required or
            any(not isinstance(name, str) or not name or kind not in ("action", "read")
                for name, kind in required.items())):
        raise ValueError("Declare nonempty action/read scenarios before running")
    indexed = {}
    for report in reports:
        if not isinstance(report, dict):
            raise ValueError("Invalid trial report")
        trial = report.get("trial")
        if type(trial) is not int or not 0 <= trial < planned_trials or trial in indexed:
            raise ValueError("Trial IDs must be unique and within the planned corpus")
        if not isinstance(report.get("scenarios"), dict):
            raise ValueError("Trial scenarios must be an object")
        indexed[trial] = report
    counts = {name: Counter({outcome: 0 for outcome in OUTCOMES}) for name in required}
    false_successes = Counter({name: 0 for name in required})
    trials = []
    for trial in range(planned_trials):
        record = indexed.get(trial, {})
        decisions = {}
        for name, kind in required.items():
            decision = classify(record.get("scenarios", {}).get(name), kind)
            decisions[name] = decision
            counts[name][decision["outcome"]] += 1
            false_successes[name] += decision["false_success"]
        trials.append({"trial": trial, "recorded": trial in indexed, "scenarios": decisions,
            "verified": not record.get("error") and all(d["outcome"] == "verified" for d in decisions.values())})
    scenarios = {name: {"kind": required[name], "planned": planned_trials, **dict(count),
        "verified_rate": count["verified"]/planned_trials, "false_successes": false_successes[name],
        "meets_reliability_threshold": planned_trials >= 100 and count["verified"]*100 >= 99*planned_trials
                                      and false_successes[name] == 0}
        for name, count in counts.items()}
    complete = finished and len(indexed) == planned_trials
    return {"planned_trials": planned_trials, "recorded_trials": len(indexed),
        "verified_trials": sum(t["verified"] for t in trials), "finished": finished,
        "false_successes": sum(false_successes.values()), "scenarios": scenarios, "trials": trials,
        "meets_scenario_reliability_gate": complete and all(s["meets_reliability_threshold"] for s in scenarios.values()),
        "release_certified": False,
        "scope": "Declared scenarios only. No proof of complete safety corpus, Excel/Edge coverage or model usability."}


def latency_summary(seconds):
    """Measured nearest-rank percentiles; no invented samples when unavailable."""
    samples = sorted(seconds)
    if any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 for n in samples):
        raise ValueError("Latencies must be finite nonnegative seconds")
    return {"count": len(samples), "total_seconds": sum(samples),
        "p50_seconds": samples[math.ceil(.50*len(samples))-1] if samples else None,
        "p95_seconds": samples[math.ceil(.95*len(samples))-1] if samples else None}
