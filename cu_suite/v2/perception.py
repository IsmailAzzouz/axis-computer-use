"""Local, bounded perception. No model/video dependency or hidden app state."""
from __future__ import annotations

import math
import time
from PIL import ImageChops, ImageStat

from .contracts import AxisError


def checked_region(region, size):
    l, t, r, b = region or (0, 0, size[0], size[1])
    if not 0 <= l < r <= size[0] or not 0 <= t < b <= size[1]:
        raise AxisError("INVALID_REGION", "Region outside captured surface")
    return (l, t, r, b)


def visual_diff(before, after, *, region=None, masks=(), threshold=8):
    if before.size != after.size:
        raise AxisError("STALE_FRAME", "Cannot compare different geometries")
    box = checked_region(region, before.size)
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    for mask in masks:
        diff.paste((0, 0, 0), checked_region(mask, before.size))
    values = ImageStat.Stat(diff.crop(box)).mean
    delta = sum(values)/3
    return {"changed": delta >= threshold, "mean_absolute_delta": delta,
            "region": box, "provenance": "local_pixels", "verification": "unobservable"}


def tree_diff(before, after):
    if before.get("query") != after.get("query"):
        raise AxisError("INVALID_SCOPE", "Semantic diff requires the same query coverage")
    if before["target_id"] != after["target_id"] or before["identity"] != after["identity"]:
        raise AxisError("STALE_OBSERVATION", "Observations have different target identities")
    if before.get("epoch") != after.get("epoch"):
        return {"reset": True, "reason": "context_changed"}
    a = {e["native_id"]: e for e in before["elements"]}
    b = {e["native_id"]: e for e in after["elements"]}
    fields = ("name", "value", "enabled", "visible", "focused", "selected", "bounds")
    return {"appeared": sorted(b.keys()-a.keys()) if before["coverage"] == "complete" else None,
            "disappeared": sorted(a.keys()-b.keys()) if after["coverage"] == "complete" else None,
            "changed": [{"native_id": k, "fields": [f for f in fields if a[k].get(f) != b[k].get(f)]}
                        for k in sorted(a.keys() & b.keys()) if any(a[k].get(f) != b[k].get(f) for f in fields)],
            "coverage": "complete" if before["coverage"] == after["coverage"] == "complete" else "truncated"}


def await_visual(runtime, job, session_id, target, args, deadline):
    """Observe change then pixel stability, without calling either task success."""
    stop = min(deadline, time.monotonic()+args.get("timeout", 10))
    runtime._check(job, stop)
    baseline = runtime._pal.capture(target)
    runtime._check(job, stop)
    if args.get("baseline_frame_id"):
        frame = runtime._frames.get(args["baseline_frame_id"])
        if not frame or frame["session_id"] != session_id or frame["geometry_id"] != target["geometry_id"] or frame["expires"] < time.monotonic():
            raise AxisError("STALE_FRAME", "Visual wait baseline expired or belongs to another context")
        baseline = frame["image"]
    region = checked_region(args.get("region"), baseline.size)
    masks, threshold = args.get("masks", []), args.get("threshold", 8)
    previous, changed, stable_since = baseline, False, None
    samples = 0
    while True:
        runtime._check(job, stop)
        fresh = runtime._bind(target["target_id"], target)
        runtime._check(job, stop)
        if fresh["geometry_id"] != target["geometry_id"]:
            raise AxisError("STALE_FRAME", "Geometry changed during visual wait")
        current = runtime._pal.capture(fresh)
        changed |= visual_diff(baseline, current, region=region, masks=masks, threshold=threshold)["changed"]
        delta = visual_diff(previous, current, region=region, masks=masks, threshold=threshold)
        now = time.monotonic()
        runtime._check(job, stop)
        if delta["changed"]:
            stable_since = None
        else:
            stable_since = stable_since or now
        previous = current
        samples += 1
        if (changed or not args.get("require_change", True)) and stable_since and now-stable_since >= args.get("stable_for", .25):
            return {"verification": "met", "output": {"changed": changed, "stable_for": now-stable_since,
                    "samples": samples, "provenance": "local_pixels", "task_effect_verified": False}}
        job.cancel.wait(min(.03, max(0, stop-time.monotonic())))


class TransitionDetector:
    """Hysteresis state machine: ON, OFF, ON preserves a repeated same color."""
    def __init__(self, baseline, *, on_threshold=30, off_threshold=12, max_gap=.1, max_events=4096):
        if off_threshold >= on_threshold:
            raise AxisError("INVALID_PROFILE", "off_threshold must be below on_threshold")
        self.baseline, self.on, self.off = baseline, on_threshold, off_threshold
        self.max_gap, self.max_events = max_gap, max_events
        self.active = {name: False for name in baseline}
        self.last_time = None
        self.last_start = None
        self.samples, self.max_observed_gap = 0, 0.0
        self.events = []

    def feed(self, timestamp, values, *, started_at=None):
        # A capture is an interval, not an instantaneous read. Pixel acquisition
        # can occur anywhere inside it. Bound the worst gap between possible
        # acquisition times, including slow capture and validation calls.
        started_at = timestamp if started_at is None else started_at
        gap = timestamp-(self.last_start if self.last_start is not None else started_at)
        if (not math.isfinite(timestamp) or not math.isfinite(started_at)
                or started_at > timestamp or gap > self.max_gap
                or (self.last_time is not None and (timestamp <= self.last_time or started_at < self.last_time))):
            raise AxisError("SAMPLING_GAP", "Temporal coverage lost; do not replay incomplete sequence")
        if values.keys() != self.baseline.keys():
            raise AxisError("SAMPLING_GAP", "A probe sample is missing")
        self.last_time = timestamp
        self.last_start = started_at
        self.samples += 1
        self.max_observed_gap = max(self.max_observed_gap, gap)
        for name, rgb in values.items():
            delta = math.sqrt(sum((x-y)**2 for x, y in zip(rgb, self.baseline[name])))
            new = delta > self.off if self.active[name] else delta >= self.on
            if new != self.active[name]:
                if len(self.events) >= self.max_events:
                    raise AxisError("BUDGET_EXCEEDED", "Event buffer full")
                self.events.append({"name": name, "state": "on" if new else "off", "timestamp": timestamp})
                self.active[name] = new

    @property
    def sequence(self):
        return [e["name"] for e in self.events if e["state"] == "on"]


def _sample(image, probes):
    return {p["name"]: ImageStat.Stat(image.crop(checked_region(p["region"], image.size)).convert("RGB")).mean for p in probes}


def _temporal_sample(runtime, job, target, probes, deadline):
    runtime._check(job, deadline)
    fresh = runtime._bind(target["target_id"], target)
    runtime._check(job, deadline)
    if fresh["geometry_id"] != target["geometry_id"]:
        raise AxisError("STALE_PROFILE", "Target moved during observation")
    started = time.perf_counter()
    values = _sample(runtime._pal.capture(fresh), probes)
    runtime._check(job, deadline)
    after = runtime._bind(target["target_id"], target)
    runtime._check(job, deadline)
    if after["geometry_id"] != target["geometry_id"]:
        raise AxisError("STALE_PROFILE", "Target moved during capture")
    return started, time.perf_counter(), values


def sequence_recipe(args):
    return [
        {"id": "demonstration", "op": "watch", "args": {"profile_id": args["profile_id"], "until": args["player_turn"], "trigger": args["trigger"]}},
        {"id": "playback", "op": "replay", "args": {"watch_step": "demonstration"}, "postcondition": args["accepted"]},
    ]


def _watch_result(result, job, args, first_step):
    # The proof is the triggered demonstration as a whole: complete pulse coverage
    # followed by the player cue. Never relabel its physical trigger as individually
    # observed, and never cover a nested plan or an arbitrary text/application edit.
    trigger = args.get("trigger", {})
    if trigger.get("op") in ("click", "keys") and len(job.steps) == first_step+1:
        result["verification_scope"] = {"kind": "triggered_demonstration", "first_step": first_step,
                                        "step_count": 1, "trigger_id": trigger["id"]}
    return result


def _continuous_watch(runtime, job, session_id, target, args, outputs, profile, stop):
    observer = runtime._pal.open_observer(target, profile["settings"], profile["baseline"], stop, cancel=job.cancel)
    try:
        def check_target():
            runtime._check(job, stop)
            current = runtime._bind(target["target_id"], target)
            runtime._check(job, stop)
            if current["geometry_id"] != profile["geometry_id"]:
                raise AxisError("STALE_PROFILE", "Target changed while continuous capture was active")
        # Essential cross-worker handshake: the original window generation must
        # still exist after the reader attached and armed its lifetime tracking.
        check_target()
        if "trigger" in args:
            armed = observer.snapshot()
            runtime._check(job, stop)
            if armed["sequence"] or armed["active"]:
                raise AxisError("CALIBRATION_UNSTABLE", "Demonstration started before its trigger")
            trigger = {**args["trigger"], "verification": "dispatch_only"}
            runtime._steps(job, session_id, [trigger], outputs, stop, target)
        while True:
            check_target()
            cue_started = time.perf_counter()
            met = runtime._predicate(target, args["until"])
            runtime._check(job, stop)
            # Response always includes a NEW capture after this request, so the
            # entire predicate read remains inside the measured coverage window.
            observed = observer.snapshot()
            check_target()
            if met:
                if not observed["sequence"] or observed["active"]:
                    raise AxisError("INCOMPLETE_SEQUENCE", "Player cue did not follow a complete idle-ended sequence")
                if observed["last_transition_at"] < cue_started:
                    return {"verification": "met", "output": {
                        **{k: v for k, v in observed.items() if k not in ("active", "last_transition_at")},
                        "profile_id": args["profile_id"]}}
                # A slow semantic read overlapped a fully captured transition.
                # Re-read the cue AFTER it, without repeating any input action.
            job.cancel.wait(min(profile["settings"]["interval"], max(0, stop-time.monotonic())))
    finally:
        # Reader must be stopped before this step completes and replay begins;
        # our own button flashes must never enter the demonstration sequence.
        observer.close()


def execute_temporal(runtime, job, session_id, target, step, args, outputs, deadline):
    runtime._check(job, deadline)
    op = step["op"]
    if op == "calibrate":
        from .runtime import uid
        settings = args["profile"]
        probes = settings["probes"]
        if len({p["name"] for p in probes}) != len(probes):
            raise AxisError("INVALID_PROFILE", "Probe names must be unique")
        interval = settings.get("interval", .02)
        gap = settings.get("max_gap", interval*3)
        if gap >= settings["min_pulse"]/2 or interval >= gap:
            raise AxisError("INVALID_PROFILE", "Require interval < max_gap < minimum pulse/2")
        started, completed, baseline = _temporal_sample(runtime, job, target, probes, deadline)
        detector = TransitionDetector(baseline, on_threshold=settings.get("on_threshold", 30),
                                      off_threshold=settings.get("off_threshold", 12), max_gap=gap)
        detector.feed(completed, baseline, started_at=started)
        # A calibration requires an idle, stable surface, not one arbitrary frame.
        for _ in range(3):
            runtime._check(job, deadline)
            job.cancel.wait(min(interval, max(0, deadline-time.monotonic())))
            runtime._check(job, deadline)
            started, completed, values = _temporal_sample(runtime, job, target, probes, deadline)
            detector.feed(completed, values, started_at=started)
            if detector.events:
                raise AxisError("CALIBRATION_UNSTABLE", "Calibrate while all probes are idle")
        profile_id = uid()
        runtime._bounded_store(runtime._profiles, profile_id, {"session_id": session_id, "target_id": target["target_id"],
            "identity": target["identity"], "geometry_id": target["geometry_id"], "baseline": baseline,
            "settings": {**settings, "interval": interval, "max_gap": gap}}, 32)
        return {"verification": "met", "output": {"profile_id": profile_id}}
    if op == "watch":
        profile = runtime._profiles.get(args["profile_id"])
        if not profile or profile["session_id"] != session_id or profile["target_id"] != target["target_id"] or profile["identity"] != target["identity"] or profile["geometry_id"] != target["geometry_id"]:
            raise AxisError("STALE_PROFILE", "Calibrate this target/session again")
        settings = profile["settings"]
        first_step = len(job.steps) if "trigger" in args else None
        stop = min(deadline, time.monotonic()+args.get("duration", 10))
        from .pal_contract import read_capabilities
        if hasattr(runtime._pal, "capabilities") and read_capabilities(runtime._pal).get("temporal_capture", False):
            if not hasattr(runtime._pal, "open_observer"):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Advertised continuous observation port unavailable")
            result = _continuous_watch(runtime, job, session_id, target, args, outputs, profile, stop)
            return _watch_result(result, job, args, first_step)
        detector = TransitionDetector(profile["baseline"], on_threshold=settings.get("on_threshold", 30),
                                      off_threshold=settings.get("off_threshold", 12), max_gap=settings["max_gap"])
        # Arm before trigger. The first sample must still be idle.
        # On Python 3.12/Windows monotonic() can be GetTickCount64 with a
        # 15.6 ms tick. Separate valid captures then get equal timestamps and
        # look like lost/reordered frames. Keep deadlines on the runtime clock,
        # but stamp samples with the monotonic high-resolution counter.
        def sample():
            started, completed, values = _temporal_sample(runtime, job, target, settings["probes"], stop)
            detector.feed(completed, values, started_at=started)
        sample()
        if any(detector.active.values()):
            raise AxisError("CALIBRATION_UNSTABLE", "Demonstration already started")
        if "trigger" in args:
            trigger = {**args["trigger"], "verification": "dispatch_only"}
            runtime._steps(job, session_id, [trigger], outputs, stop, target)
        while True:
            runtime._check(job, stop)
            sample()
            met = runtime._predicate(target, args["until"])
            runtime._check(job, stop)
            if met:
                if not detector.sequence or any(detector.active.values()):
                    raise AxisError("INCOMPLETE_SEQUENCE", "Player cue arrived without a complete idle-ended sequence")
                # Cover the semantic read too. A slow successful predicate may
                # have hidden another flash or a lost sample at the very end.
                events_before_cue_tail = len(detector.events)
                sample()
                if len(detector.events) != events_before_cue_tail:
                    raise AxisError("INCOMPLETE_SEQUENCE", "Demonstration changed while reading the player cue")
                break
            job.cancel.wait(min(settings["interval"], max(0, stop-time.monotonic())))
        return _watch_result({"verification": "met", "output": {"sequence": detector.sequence, "profile_id": args["profile_id"],
                "sampled_until": detector.last_time, "sample_clock": "performance_counter",
                "samples": detector.samples, "max_observed_gap": detector.max_observed_gap,
                "observation_mode": "polling"}}, job, args, first_step)
    recorded = outputs.get(args["watch_step"], {})
    profile = runtime._profiles.get(recorded.get("profile_id"))
    if not profile or not recorded.get("sequence"):
        raise AxisError("INVALID_DATAFLOW", "Replay requires a completed watch")
    if (profile["session_id"] != session_id or profile["target_id"] != target["target_id"]
            or profile["identity"] != target["identity"]
            or profile["geometry_id"] != runtime._bind(target["target_id"], target)["geometry_id"]):
        raise AxisError("STALE_PROFILE", "Replay target geometry changed")
    first_step = len(job.steps)
    for i, name in enumerate(recorded["sequence"]):
        probe = next(p for p in profile["settings"]["probes"] if p["name"] == name)
        l, t, r, b = probe["region"]
        click = {"id": step["id"]+"-"+str(i), "op": "click", "target_id": target["target_id"], "verification": "dispatch_only",
                 "args": {"at": {"point": {"space": "desktop", "geometry_id": profile["geometry_id"],
                    "x": target["bounds"][0]+(l+r)//2, "y": target["bounds"][1]+(t+b)//2}}}}
        runtime._steps(job, session_id, [click], outputs, deadline)
        job.cancel.wait(min(args.get("interval", .15), max(0, deadline-time.monotonic())))
    if not step.get("postcondition"):
        raise AxisError("UNVERIFIED_EFFECT", "Replay requires round acceptance postcondition", dispatch="sent")
    try:
        runtime._await(target, step["postcondition"], job, deadline)
    except AxisError as exc:
        # These clicks were acknowledged already. Failed acceptance is not proof
        # that no input was sent, and must never authorize replaying the sequence.
        raise AxisError(exc.code, str(exc), dispatch="unknown" if exc.dispatch == "unknown" else "sent") from exc
    return {"dispatch": "sent", "verification": "met", "output": {"replayed": len(recorded["sequence"])},
            "evidence": {"observed_at": time.time(), "predicate": step["postcondition"]["kind"]},
            "verification_scope": {"kind": "sequence_acceptance", "first_step": first_step,
                                   "step_count": len(recorded["sequence"])}}
