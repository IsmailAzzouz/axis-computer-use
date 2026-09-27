"""Resident, platform-independent execution engine for the AXIS tools."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field

from .contracts import (ACTION_ARGS, AxisError, MAX_BYTES, MAX_SECONDS, MAX_STEPS,
                        SCHEMAS, VERSION, compile_steps, validate)
from .pal_contract import read_target, read_targets


def uid():
    return uuid.uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Policy:
    """Created by the host, never deserialized from model arguments."""
    target_ids: frozenset[str] = frozenset()
    apps: frozenset[str] = frozenset()
    allow_terminate: bool = False
    read_all: bool = False
    allow_all: bool = False
    max_seconds: float = MAX_SECONDS


@dataclass
class Job:
    job_id: str
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    status: str = "accepted"
    steps: list = field(default_factory=list)
    error: dict | None = None
    started: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock)
    entered_steps: int = 0
    cleanup: dict | None = None
    observation_sessions: dict = field(default_factory=dict)


class Runtime:
    def __init__(self, platform, *, policy=None, journal_path="axis-v2.sqlite3", lease=None):
        self._pal = platform
        self.policy = policy or Policy()
        self._created = set()
        self._sessions, self._observations, self._frames, self._jobs = {}, {}, {}, {}
        self._profiles = {}
        from .pages import Pages
        self._pages = Pages()
        self._lock = threading.RLock()
        self._input = lease or threading.Lock()
        self._db = sqlite3.connect(journal_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, digest TEXT NOT NULL, job TEXT NOT NULL, result TEXT)")
        self._db.execute("CREATE INDEX IF NOT EXISTS requests_by_job ON requests(job)")
        self._db.execute("CREATE TABLE IF NOT EXISTS effects (job TEXT, ordinal INTEGER, step TEXT, phase TEXT, PRIMARY KEY(job, ordinal))")
        self._db.commit()
        self._closed = False
        self._active_job = None
        self._control_lock = threading.Lock()
        self._journal_failed = False
        self._input_uncertain = False

    def call(self, tool, arguments=None):
        result, effect_path = None, False
        try:
            if self._closed:
                raise AxisError("RUNTIME_CLOSED", "Runtime has stopped")
            if not isinstance(tool, str) or tool not in SCHEMAS:
                raise AxisError("UNKNOWN_TOOL", "Unknown tool; use axis.help")
            arguments = {} if arguments is None else arguments
            validate(arguments, SCHEMAS[tool])
            effect_path = tool == "axis.run" or (tool == "axis.job" and arguments.get("action") == "cancel")
            result = getattr(self, "_" + tool.split(".")[1])(**arguments)
            response = {"version": VERSION, **result}
            if "image_base64" not in response and len(encoded(response).encode()) > MAX_BYTES:
                raise AxisError("OUTPUT_TOO_LARGE", "Response exceeds text budget; recover submitted jobs using the original idempotency key, or narrow read-only observations",
                                dispatch="unknown" if effect_path else "not_sent")
            return response
        except AxisError as exc:
            error = exc.result()
        except Exception as exc:
            # Never serialize arbitrary native exception messages (may contain secrets).
            error = {"code": "INTERNAL_ERROR", "message": type(exc).__name__, "dispatch": "unknown" if effect_path else "not_sent"}
        # Error paths must obey the text budget too; never echo an unbounded list
        # of invalid model-supplied field names outside the normal output guard.
        if len(error["code"]) > 128 or len(error["message"]) > 1024:
            error = {**error, "code": error["code"][:128], "message": error["message"][:1024], "truncated": True}
        failure = {"version": VERSION, "status": "unknown" if error["dispatch"] == "unknown" else "failed", "error": error}
        job_id = result.get("job_id") if isinstance(result, dict) else None
        if isinstance(job_id, str) and job_id.isascii() and len(job_id) <= 128:
            failure["job_id"] = job_id
        return failure

    @staticmethod
    def _help(**arguments):
        from .help import guide
        return guide(arguments)

    def _capabilities(self):
        from .pal_contract import read_capabilities
        return read_capabilities(self._pal)

    def _allowed(self, target_id, mutate=False, *, windows=None):
        # O(1) when allow_all/target authorized, bounded O(1) ancestor chain (max 8)
        if self.policy.allow_all or "*" in self.policy.target_ids:
            return
        if target_id in self.policy.target_ids or target_id in self._created:
            return
        if not mutate and self.policy.read_all:
            return
        # Native-owned dialogs/menus inherit only their bound owner's authority,
        # never authority merely because another window shares the process.
        if windows is None:
            windows = read_targets(self._pal)
        owner = windows.get(target_id, {}).get("owner_target_id")
        for _ in range(8):
            if not owner:
                break
            if owner in self.policy.target_ids or owner in self._created:
                return
            owner = windows.get(owner, {}).get("owner_target_id")
        raise AxisError("POLICY_DENIED", "Target is not authorized by the host")

    def _targets(self, cursor=None):
        if cursor:
            return self._pages.read(cursor, kind="targets")
        capabilities = self._capabilities()
        windows = read_targets(self._pal)
        targets = []
        for target in windows.values():
            try:
                self._allowed(target["target_id"], windows=windows)
                if len(target.get("title", "")) > 2048:
                    target = {**target, "title": target["title"][:2048], "title_truncated": True}
                targets.append(target)
            except AxisError as exc:
                if exc.code != "POLICY_DENIED":
                    raise
        apps_list = ["*"] if (self.policy.allow_all or "*" in self.policy.apps) else sorted(self.policy.apps)
        return self._pages.create("targets", targets, {"capabilities": capabilities, "apps": apps_list})

    def _session(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
        if not session or time.monotonic() > session["expires"]:
            raise AxisError("SESSION_EXPIRED", "Observe the target to create a new session")
        return session

    def _bind(self, target_id, previous=None):
        self._allowed(target_id)
        return read_target(self._pal, target_id, previous)

    @staticmethod
    def _bounded_store(store, key, value, limit):
        store[key] = value
        while len(store) > limit:
            store.pop(next(iter(store)))

    def _inspect(self, target, query=None):
        capabilities = self._capabilities()
        if not capabilities.get("accessibility", False):
            raise AxisError("CAPABILITY_UNAVAILABLE", "Accessibility unavailable")
        if query and capabilities.get("targeted_accessibility"):
            return self._pal.inspect(target, query)
        raw = self._pal.inspect(target)
        if query:
            raw = {**raw, "elements": self._matches(raw["elements"], query)}
        return raw

    def _observe(self, target_id=None, session_id=None, scope="tree", since=None, cursor=None, region=None, action=None, query=None):
        if query and scope not in ("tree", "diff"):
            raise AxisError("INVALID_REQUEST", "query is valid only for tree/diff scope")
        if scope == "capabilities":
            result = {"capabilities": self._capabilities(), "actions": list(ACTION_ARGS),
                      "recipes": {"sequence-memory.play@1": SCHEMAS["axis.run"]["properties"]["recipe_args"]}}
            if action:
                result["action"] = {"name": action, "arguments": ACTION_ARGS[action], "nested_step_schema": "axis.run inputSchema.$defs.step"}
            return result
        if action:
            raise AxisError("INVALID_REQUEST", "action is valid only in capabilities scope")
        if cursor:
            if cursor.startswith("page:"):
                return self._pages.read(cursor, session_id=session_id)
            return self._observation_page(cursor, session_id)
        if session_id and target_id:
            raise AxisError("INVALID_REQUEST", "Use target_id or session_id")
        if not session_id:
            target_id = target_id or "desktop"
            target = {"target_id": "desktop", "identity": "desktop"} if target_id == "desktop" else self._bind(target_id)
            session_id = uid()
            with self._lock:
                self._bounded_store(self._sessions, session_id, {"target": target, "expires": time.monotonic()+1800}, 256)
        session = self._session(session_id)
        if session["target"]["target_id"] == "desktop":
            return {"session_id": session_id, **self._targets()}
        target = self._bind(session["target"]["target_id"], session["target"])
        if scope == "events":
            if not self._capabilities().get("subscriptions"):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Native subscriptions unavailable")
            try:
                event_cursor = int(since or 0)
            except ValueError:
                raise AxisError("INVALID_CURSOR", "Event cursor must be an integer string")
            return {"session_id": session_id, **self._pal.events(target, event_cursor)}
        if scope == "ocr":
            if not self._capabilities().get("ocr"):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Local OCR unavailable")
            ocr = self._pal.ocr(target, region)
            words = []
            for index, line in enumerate(ocr.get("lines", [])):
                for word in line["words"]:
                    words.append({**word, "line": index})
            return self._pages.create("words", words, {"session_id": session_id,
                **{k: v for k, v in ocr.items() if k not in ("lines", "text")}}, session_id)
        if scope == "visual_diff":
            from .perception import visual_diff
            old = self._frames.get(since)
            if not old or old["session_id"] != session_id:
                raise AxisError("STALE_FRAME", "A frame from this session is required")
            if old["geometry_id"] != target["geometry_id"]:
                raise AxisError("STALE_FRAME", "Frame geometry changed")
            if not self._capabilities().get("capture", False):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Local capture unavailable")
            current = self._pal.capture(target)
            return {"session_id": session_id, **visual_diff(old["image"], current, region=region)}
        raw = self._inspect(target, query)
        if raw.get("coverage") not in ("complete", "truncated"):
            raise AxisError("OBSERVATION_UNAVAILABLE", "Accessibility coverage unavailable")
        observation_id = uid()
        elements = []
        for index, e in enumerate(raw["elements"]):
            e = copy.deepcopy(e)
            e["ref"] = f"{observation_id}:{index}"
            if e.get("sensitive"):
                e["name"], e["value"] = "[redacted]", "[redacted]"
            for key in ("name", "value", "automation_id"):
                if isinstance(e.get(key), str) and len(e[key]) > 1024:
                    e[key] = e[key][:1024]
                    e.setdefault("truncated_fields", []).append(key)
            elements.append(e)
        observation = {"observation_id": observation_id, "session_id": session_id, "target_id": target["target_id"],
                       "identity": target["identity"], "geometry_id": target["geometry_id"], "epoch": raw.get("epoch"),
                       "observed_at": time.time(), "expires_at": time.time()+30, "coverage": raw["coverage"],
                       "provenance": "native_accessibility", "elements": elements, "query": query}
        if scope == "diff":
            from .perception import tree_diff
            old = self._observations.get(since)
            if not old or old["session_id"] != session_id:
                raise AxisError("STALE_OBSERVATION", "Diff requires an observation from this session")
            observation["changes"] = tree_diff(old, observation)
        with self._lock:
            self._bounded_store(self._observations, observation_id, observation, 64)
        return self._observation_page(observation_id+":0", session_id)

    def _observation_page(self, cursor, session_id):
        try:
            oid, offset = cursor.rsplit(":", 1)
            offset = int(offset)
            obs = self._observations[oid]
        except (KeyError, ValueError):
            raise AxisError("INVALID_CURSOR", "Unknown observation cursor")
        if obs["session_id"] != session_id or offset < 0 or offset > len(obs["elements"]):
            raise AxisError("INVALID_CURSOR", "Cursor does not belong to session")
        result = {k: v for k, v in obs.items() if k not in ("elements", "identity", "changes")}
        result["elements"] = []
        while offset < len(obs["elements"]):
            candidate = obs["elements"][offset]
            if len(encoded({**result, "elements": result["elements"]+[candidate]}).encode()) > MAX_BYTES-512:
                if not result["elements"]:
                    raise AxisError("OUTPUT_TOO_LARGE", "One element exceeds page budget; narrow observation")
                break
            result["elements"].append(candidate)
            offset += 1
        result["next_cursor"] = f"{oid}:{offset}" if offset < len(obs["elements"]) else None
        if "changes" in obs:
            result["changes"] = obs["changes"]
            if len(encoded(result).encode()) > MAX_BYTES:
                result.pop("changes")
                result["changes_unavailable"] = "OUTPUT_TOO_LARGE"
        return result

    def _plan_observe(self, job, session_id, target, query=None):
        """Bind readback to this job's verified identity, with bounded session reuse."""
        if target["target_id"] == "desktop":
            raise AxisError("INVALID_TARGET", "A plan tree observation needs a window target; use target_from after open_app")
        source = self._session(session_id)["target"]
        if source["target_id"] == target["target_id"]:
            observation_session = session_id
        else:
            observation_session = job.observation_sessions.get(target["target_id"])
            if observation_session is None:
                observation_session = uid()
                with self._lock:
                    self._bounded_store(self._sessions, observation_session,
                        {"target": copy.deepcopy(target), "expires": time.monotonic()+1800}, 256)
                job.observation_sessions[target["target_id"]] = observation_session
        bound = self._session(observation_session)["target"]
        if bound["identity"] != target["identity"]:
            raise AxisError("STALE_TARGET", "Observed target identity changed during this plan")
        observed = self._observe(session_id=observation_session, query=query)
        # Only references are durable. Hydrate the immutable, redacted snapshot
        # when returning a job result; never persist native text/values here.
        return {"session_id": observation_session, "observation_id": observed["observation_id"],
                "target_id": target["target_id"], "cursor": observed["observation_id"]+":0"}

    def _readback_steps(self, steps):
        """Attach live-cache readbacks without altering durable step records."""
        result = []
        for step in steps:
            output = step.get("output", {})
            if step.get("op") == "observe" and "observation_id" in output:
                try:
                    page = self._observation_page(output.get("cursor", output["observation_id"]+":0"), output["session_id"])
                except AxisError as exc:
                    if exc.code != "INVALID_CURSOR":
                        raise
                    output = {**output, "data_state": "unavailable", "data_reason": "OBSERVATION_EXPIRED"}
                else:
                    output = {**output, **page, "data_state": "available"}
                step = {**step, "output": output}
            result.append(step)
        return result

    def _capture(self, session_id, region=None, include_image=True):
        from .perception import checked_region
        session = self._session(session_id)
        if not self._capabilities().get("capture", False):
            raise AxisError("CAPABILITY_UNAVAILABLE", "Local capture unavailable")
        target = self._bind(session["target"]["target_id"], session["target"])
        l, t, r, b = target["bounds"]
        if (r-l)*(b-t) > 16_000_000:
            raise AxisError("CAPTURE_TOO_LARGE", "Window exceeds the 16-megapixel capture budget")
        image = self._pal.capture(target)
        box = checked_region(region, image.size)
        crop = image.crop(box)
        frame_id = uid()
        with self._lock:
            self._bounded_store(self._frames, frame_id, {"image": image, "session_id": session_id,
                "geometry_id": target["geometry_id"], "box": box, "expires": time.monotonic()+30}, 16)
            while sum(f["image"].width*f["image"].height*4 for f in self._frames.values()) > 64*1024*1024:
                del self._frames[next(iter(self._frames))]
        result = {"frame_id": frame_id, "session_id": session_id, "geometry_id": target["geometry_id"],
                "width": crop.width, "height": crop.height, "source_region": box,
                "desktop_origin": [target["bounds"][0]+box[0], target["bounds"][1]+box[1]],
                "mime_type": "image/png"}
        if include_image:
            out = io.BytesIO()
            crop.save(out, format="PNG")
            result["image_base64"] = base64.b64encode(out.getvalue()).decode()
        return result

    def _resolve(self, locator, session_id, target):
        if "point" in locator:
            p = locator["point"]
            x, y = p["x"], p["y"]
            if p["space"] == "frame":
                f = self._frames.get(p["frame_id"])
                if not f or f["session_id"] != session_id or f["expires"] < time.monotonic() or f["geometry_id"] != target["geometry_id"]:
                    raise AxisError("STALE_FRAME", "Capture again before using this point")
                l, t, r, b = f["box"]
                if not (0 <= x < r-l and 0 <= y < b-t):
                    raise AxisError("INVALID_POINT", "Point outside frame")
                x, y = x+l+target["bounds"][0], y+t+target["bounds"][1]
            else:
                if p["geometry_id"] != target["geometry_id"]:
                    raise AxisError("STALE_FRAME", "Geometry changed")
                if p["space"] == "client":
                    x, y = x+target["client_origin"][0], y+target["client_origin"][1]
            l, t, r, b = target["bounds"]
            if not l <= x < r or not t <= y < b:
                raise AxisError("INVALID_POINT", "Point is outside authorized window")
            return {"x": round(x), "y": round(y)}
        if "ref" in locator:
            try:
                oid, index = locator["ref"].rsplit(":", 1)
                old = self._observations[oid]
                raw = self._inspect(target, old.get("query"))
                if int(index) < 0 or old["session_id"] != session_id or old["identity"] != target["identity"] or time.time() > old["expires_at"] or old["epoch"] != raw.get("epoch"):
                    raise ValueError()
                wanted = old["elements"][int(index)]
                candidates = [e for e in raw["elements"] if e["native_id"] == wanted["native_id"]]
            except (KeyError, IndexError, ValueError):
                raise AxisError("STALE_REFERENCE", "Observe and resolve a new reference")
        else:
            raw = self._inspect(target, locator["selector"])
            if raw["coverage"] != "complete":
                raise AxisError("OBSERVATION_INCOMPLETE", "Selector uniqueness requires complete scoped coverage; use a contextual ref or narrow the observation")
            candidates = self._matches(raw["elements"], locator["selector"])
        if raw.get("coverage") not in ("complete", "truncated"):
            raise AxisError("OBSERVATION_UNAVAILABLE", "Cannot resolve element")
        if len(candidates) != 1:
            raise AxisError("AMBIGUOUS_TARGET" if candidates else "ELEMENT_NOT_FOUND", "Expected exactly one matching element")
        e = candidates[0]
        if not e.get("enabled", True) or not e.get("visible", True):
            raise AxisError("ELEMENT_NOT_ACTIONABLE", "Element disabled or not visible")
        l, t, r, b = e["bounds"]
        if r <= l or b <= t:
            raise AxisError("ELEMENT_NOT_ACTIONABLE", "Element has no usable bounds")
        query = locator.get("selector") or {k: e[k] for k in ("role", "automation_id", "name") if e.get(k)}
        return {"x": (l+r)//2, "y": (t+b)//2, "native_id": e["native_id"],
                "resolved_bounds": list(e["bounds"]), "query": copy.deepcopy(query)}

    @staticmethod
    def _matches(elements, selector):
        return [e for e in elements if all(e.get(k) == v for k, v in selector.items())]

    def _predicate(self, target, condition):
        if condition["kind"] == "window_state":
            observed = self._bind(target["target_id"], target).get("window_state")
            if observed not in ("normal", "minimized", "maximized"):
                raise AxisError("VERIFICATION_UNAVAILABLE", "Native window state is unavailable")
            return observed == condition["expected"]
        if condition["kind"] == "window_closed":
            try:
                # The window may already have left discovery/owner policy. Read
                # its original binding without requiring it to still be listed.
                read_target(self._pal, target["target_id"], target)
                return False
            except AxisError as exc:
                if exc.code == "TARGET_NOT_FOUND":
                    return True
                raise
        raw = self._inspect(self._bind(target["target_id"], target), condition.get("selector"))
        if raw.get("coverage") not in ("complete", "truncated"):
            raise AxisError("OBSERVATION_UNAVAILABLE", "Predicate cannot be observed")
        selector = condition.get("selector")
        if not selector:
            raise AxisError("INVALID_PREDICATE", "A nonempty selector is required")
        matches = self._matches(raw["elements"], selector)
        kind = condition["kind"]
        if kind == "absent":
            if not matches and raw["coverage"] != "complete":
                raise AxisError("OBSERVATION_INCOMPLETE", "Absence cannot be proven on truncated tree")
            return not matches
        if kind == "exists":
            return bool(matches)
        if len(matches) > 1:
            raise AxisError("AMBIGUOUS_TARGET", "Predicate matches multiple elements")
        if raw["coverage"] != "complete":
            raise AxisError("OBSERVATION_INCOMPLETE", "Property verification requires a unique element in complete scoped coverage")
        if not matches:
            return False
        if matches[0].get("sensitive"):
            raise AxisError("UNOBSERVABLE", "Sensitive values cannot be compared through model predicates")
        if kind == "selected" and type(matches[0].get("selected")) is not bool:
            raise AxisError("UNOBSERVABLE", "Selection state is not exposed by this element")
        return matches[0].get(kind) == condition.get("expected", True)

    def _check(self, job, deadline):
        if job.cancel.is_set():
            raise AxisError("CANCELLED", "Plan cancelled")
        if time.monotonic() >= deadline:
            raise AxisError("DEADLINE_EXCEEDED", "Plan deadline exceeded")
        if job.entered_steps > MAX_STEPS:
            raise AxisError("BUDGET_EXCEEDED", "Executed step limit reached")

    def _await(self, target, condition, job, deadline, stable_for=0):
        stable_since = None
        self._check(job, deadline)
        subscribed = self._capabilities().get("subscriptions", False) and condition["kind"] not in ("window_closed", "window_state")
        event_cursor = self._pal.events(target)["cursor"] if subscribed else 0
        while True:
            self._check(job, deadline)
            met = self._predicate(target, condition)
            self._check(job, deadline)
            if met:
                stable_since = stable_since or time.monotonic()
                if time.monotonic()-stable_since >= stable_for:
                    return
            else:
                stable_since = None
            job.cancel.wait(min(.05, max(0, deadline-time.monotonic())))
            self._check(job, deadline)
            if subscribed:
                # Drain bounded native events but always re-read state, even on
                # silence or dropped coverage. Polling remains the portable fallback.
                event_cursor = self._pal.events(target, event_cursor)["cursor"]

    def _write_journal(self, statement, parameters):
        with self._lock:
            if self._journal_failed:
                raise AxisError("JOURNAL_UNAVAILABLE", "Journal write failure requires host recovery before new input")
            try:
                self._db.execute(statement, parameters)
                self._db.commit()
            except BaseException:
                # Keep rollback under the same lock: another job must never commit
                # an earlier failed transaction, or have its own write rolled back.
                self._journal_failed = True
                try:
                    self._db.rollback()
                except Exception:
                    pass  # Writes remain disabled even if rollback itself failed.
                raise

    def _journal(self, job, ordinal, step_id, phase):
        try:
            self._write_journal("INSERT OR REPLACE INTO effects VALUES (?, ?, ?, ?)", (job.job_id, ordinal, step_id, phase))
        except Exception:
            raise AxisError("JOURNAL_FAILED", "Durable journal unavailable", dispatch="unknown" if phase == "sent" else "not_sent")

    def _admit(self, steps, default_target, capabilities):
        """Reject all statically knowable authority/capability errors before effects.

        Dynamic identities returned by earlier launches are checked on execution;
        selectors are deliberately resolved only at their actual time of use.
        """
        from .pal_contract import LOCAL_OPERATIONS
        local_ops = LOCAL_OPERATIONS
        for step in steps:
            op, args = step["op"], step.get("args", {})
            target_id = None if "target_from" in step else step.get("target_id", default_target)
            if op == "open_app":
                if not (self.policy.allow_all or "*" in self.policy.apps) and args["app"] not in self.policy.apps:
                    raise AxisError("POLICY_DENIED", "Application is not in host allowlist")
            elif target_id is not None:
                if target_id == "desktop":
                    raise AxisError("INVALID_TARGET", "Bind a window or use target_from before this operation")
                self._allowed(target_id, mutate=op not in local_ops or op == "replay")
            if op not in local_ops and op not in capabilities.get("actions", []):
                raise AxisError("CAPABILITY_UNAVAILABLE", f"Action unavailable: {op}")
            conditions = [step.get("precondition"), step.get("postcondition"), args.get("condition"), args.get("until")]
            needs_accessibility = (op == "observe" or
                any(c and c["kind"] not in ("window_closed", "window_state") for c in conditions) or
                any("selector" in args.get(k, {}) or "ref" in args.get(k, {}) for k in ("at", "start", "end")))
            if needs_accessibility and not capabilities.get("accessibility", False):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Accessibility is required by this plan")
            if op in ("await_visual", "calibrate", "watch") and not capabilities.get("capture", False):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Local capture is required by this plan")
            if op == "replay" and "click" not in capabilities.get("actions", []):
                raise AxisError("CAPABILITY_UNAVAILABLE", "Replay requires native click capability")
            if op == "terminate_app" and not (self.policy.allow_terminate or self.policy.allow_all):
                raise AxisError("POLICY_DENIED", "Forced termination requires host authority")
            if op == "repeat":
                self._admit(args["steps"], target_id, capabilities)
            elif op == "if":
                self._admit(args["then"], target_id, capabilities)
                self._admit(args.get("else", []), target_id, capabilities)
            elif op == "watch" and "trigger" in args:
                trigger = args["trigger"]
                if "target_from" in trigger or trigger.get("target_id", target_id) != target_id:
                    raise AxisError("INVALID_PLAN", "Watch trigger must act on its observed target")
                self._admit([trigger], target_id, capabilities)

    def _run(self, session_id, idempotency_key, steps=None, timeout=MAX_SECONDS, recipe=None, recipe_args=None, **options):
        session = self._session(session_id)
        if bool(steps) == bool(recipe):
            raise AxisError("INVALID_PLAN", "Provide steps or a recipe, not both")
        if recipe:
            from .perception import sequence_recipe
            if not recipe_args:
                raise AxisError("INVALID_PLAN", "recipe_args required")
            steps = sequence_recipe(recipe_args)
        compile_steps(steps)
        digest = hashlib.sha256(encoded({"target_identity": session["target"]["identity"], "steps": steps, "timeout": timeout}).encode()).hexdigest()
        with self._lock:
            if self._closed:
                raise AxisError("RUNTIME_CLOSED", "Runtime has stopped")
            prior = self._db.execute("SELECT digest,job,result FROM requests WHERE key=?", (idempotency_key,)).fetchone()
            if prior:
                if prior[0] != digest:
                    raise AxisError("IDEMPOTENCY_CONFLICT", "Key used for a different request")
                return self._run_result(prior[1])
            if self._journal_failed:
                raise AxisError("JOURNAL_UNAVAILABLE", "Repair journal storage and restart the host before submitting new input; existing jobs remain queryable")
            if self._input_uncertain:
                raise AxisError("INPUT_UNRECONCILED", "Prior input cleanup is unresolved; host reconciliation required before new execution")
            self._admit(steps, session["target"]["target_id"], self._capabilities())
            if len(self._jobs) >= 256:
                completed = next((key for key, old in self._jobs.items() if old.done.is_set()), None)
                if completed is None:
                    raise AxisError("RESOURCE_LIMIT", "Too many active jobs")
                del self._jobs[completed]  # Durable results remain paginatable.
            job = Job(uid())
            try:
                self._write_journal("INSERT INTO requests VALUES (?,?,?,NULL)", (idempotency_key, digest, job.job_id))
            except Exception:
                raise AxisError("JOURNAL_FAILED", "Request could not be durably admitted; no execution thread was started")
            self._jobs[job.job_id] = job
        launch_decided, launch_allowed = threading.Event(), False
        def execute_after_start():
            launch_decided.wait()
            if launch_allowed:
                self._execute(job, session_id, steps, min(timeout, self.policy.max_seconds))
        try:
            # No effect can begin before start() has returned successfully. This
            # also handles a launcher that starts a thread and then raises.
            thread = threading.Thread(target=execute_after_start, daemon=True)
            thread.start()
        except BaseException as exc:
            launch_decided.set()
            job.status = "failed"
            job.error = {"code": "EXECUTOR_UNAVAILABLE", "message": "Execution thread could not start", "dispatch": "not_sent"}
            job.cleanup = {"state": "not_required"}
            self._publish(job)
            if not isinstance(exc, Exception):
                raise
            return self._run_result(job.job_id)
        launch_allowed = True
        launch_decided.set()
        if options.get("async"):
            return {"job_id": job.job_id, "status": "accepted"}
        job.done.wait(min(timeout+1, 10))
        return self._run_result(job.job_id)

    def _run_result(self, job_id):
        """Retrieval failure after admission is not an unsubmitted operation."""
        try:
            return self._job(job_id, "result")
        except Exception:
            return {"job_id": job_id, "status": "unknown", "effects_verified": False,
                    "error": {"code": "RESULT_UNAVAILABLE", "message": "Submitted job result unavailable; recover with axis.job using the original idempotency key", "dispatch": "unknown"}}

    def _publish(self, job):
        try:
            result = {"job_id": job.job_id, "status": job.status, "error": job.error, "steps": job.steps, "cleanup": job.cleanup}
            self._write_journal("UPDATE requests SET result=? WHERE job=?", (encoded(result), job.job_id))
        except Exception:
            job.status, job.error = "unknown", {"code": "JOURNAL_FAILED", "message": "Do not retry without reconciliation", "dispatch": "unknown"}
        finally:
            job.done.set()

    def _cleanup_snapshot(self):
        raw = self._pal.cleanup_status()
        if not isinstance(raw, dict) or raw.get("state") not in ("confirmed", "not_required", "pending", "failed", "unknown"):
            raise ValueError("Invalid cleanup state")
        # Never persist arbitrary adapter details (notably clipboard contents).
        snapshot = {"state": raw["state"]}
        if "owned_input_count" in raw:
            count = raw["owned_input_count"]
            if type(count) is not int or not 0 <= count <= 256:
                raise ValueError("Invalid owned input count")
            snapshot["owned_input_count"] = count
        if "clipboard_pending" in raw:
            if type(raw["clipboard_pending"]) is not bool:
                raise ValueError("Invalid clipboard state")
            snapshot["clipboard_pending"] = raw["clipboard_pending"]
        if (snapshot["state"] in ("confirmed", "not_required") and
                (snapshot.get("owned_input_count", 0) or snapshot.get("clipboard_pending", False))):
            snapshot["state"] = "unknown"
        return snapshot

    def _execute(self, job, session_id, steps, timeout):
        deadline = time.monotonic()+timeout
        acquired = False
        native_acquired = False
        try:
            acquired = self._input.acquire(blocking=False)
            if not acquired:
                raise AxisError("DESKTOP_BUSY", "Another plan owns desktop input")
            if self._input_uncertain:
                raise AxisError("INPUT_UNRECONCILED", "Prior input cleanup is unresolved; no new native input was admitted")
            if hasattr(self._pal, "acquire_lease"):
                self._pal.acquire_lease()
            native_acquired = True
            with self._control_lock:
                self._active_job = job.job_id
            job.status = "running"
            outputs = {}
            self._steps(job, session_id, steps, outputs, deadline)
            job.status = "completed"
        except AxisError as exc:
            progressed = any(step["dispatch"] != "not_sent" or step["verification"] == "met" for step in job.steps)
            job.status = "cancelled" if exc.code == "CANCELLED" else "unknown" if exc.dispatch == "unknown" else "partial" if progressed else "failed"
            job.error = exc.result()
        except Exception as exc:
            job.status, job.error = "unknown", {"code": "INTERNAL_ERROR", "message": type(exc).__name__, "dispatch": "unknown"}
        finally:
            if acquired:
                if native_acquired:
                    cleanups = [self._pal.release]
                    if hasattr(self._pal, "release_lease"):
                        cleanups.append(self._pal.release_lease)
                    for cleanup in cleanups:
                        try:
                            cleanup()
                        except Exception:
                            self._input_uncertain = True
                            job.status, job.error = "unknown", {"code": "CLEANUP_FAILED", "message": "Input ownership could not be reconciled", "dispatch": "unknown"}
                    if hasattr(self._pal, "cleanup_status"):
                        try:
                            job.cleanup = self._cleanup_snapshot()
                            if job.cleanup.get("state") not in ("confirmed", "not_required"):
                                raise ValueError("Cleanup unconfirmed")
                        except Exception:
                            self._input_uncertain = True
                            if job.cleanup is None:
                                job.cleanup = {"state": "unknown"}
                            job.status, job.error = "unknown", {"code": "CLEANUP_FAILED", "message": "Cleanup status unconfirmed", "dispatch": "unknown"}
                else:
                    job.cleanup = {"state": "not_required"}
                # Complete this owner's bookkeeping before another job can take
                # the lease and install its own out-of-band cancellation route.
                with self._control_lock:
                    self._active_job = None
                try:
                    self._input.release()
                except Exception:
                    self._input_uncertain = True
                    job.status, job.error = "unknown", {"code": "CLEANUP_FAILED", "message": "Local input lease could not be released", "dispatch": "unknown"}
            else:
                job.cleanup = {"state": "not_required"}
            self._publish(job)

    def _steps(self, job, session_id, steps, outputs, deadline, default_target=None):
        for step in steps:
            job.entered_steps += 1
            self._check(job, deadline)
            # Target binding, resolution and preconditions consume this step's
            # budget too; a slow read must never authorize a late mutation.
            local_deadline = min(deadline, time.monotonic()+step.get("timeout", 10))
            op, args = step["op"], copy.deepcopy(step.get("args", {}))
            session = self._session(session_id)
            base_target = default_target or session["target"]
            target_id = step.get("target_id", base_target["target_id"])
            if "target_from" in step:
                target_id = outputs.get(step["target_from"], {}).get("target_id")
                if not target_id:
                    raise AxisError("INVALID_DATAFLOW", "Earlier step did not produce a target")
            previous = base_target if target_id == base_target["target_id"] else None
            target = {"target_id": "desktop", "identity": "desktop"} if target_id == "desktop" else self._bind(target_id, previous)
            self._check(job, local_deadline)
            if step.get("precondition") and not self._predicate(target, step["precondition"]):
                raise AxisError("PRECONDITION_UNMET", "Precondition is false")
            self._check(job, local_deadline)
            result = {"id": step["id"], "op": op, "dispatch": "not_sent", "verification": "unobservable"}
            if op == "if":
                branch = args["then"] if self._predicate(target, args["condition"]) else args.get("else", [])
                self._steps(job, session_id, branch, dict(outputs), local_deadline, target)
                result["verification"] = "met"
            elif op == "repeat":
                for _ in range(args["count"]):
                    self._steps(job, session_id, args["steps"], dict(outputs), local_deadline, target)
                result["verification"] = "met"
            elif op == "await":
                self._await(target, args["condition"], job, min(local_deadline, time.monotonic()+args.get("timeout", 10)), args.get("stable_for", 0))
                result["verification"] = "met"
            elif op == "await_visual":
                from .perception import await_visual
                result.update(await_visual(self, job, session_id, target, args, local_deadline))
            elif op == "observe":
                result["output"] = self._plan_observe(job, session_id, target, args.get("query"))
                result["verification"] = "met"
            elif op in ("calibrate", "watch", "replay"):
                from .perception import execute_temporal
                result.update(execute_temporal(self, job, session_id, target, step, args, outputs, local_deadline))
            else:
                if op == "open_app":
                    if not (self.policy.allow_all or "*" in self.policy.apps) and args["app"] not in self.policy.apps:
                        raise AxisError("POLICY_DENIED", "Application is not in host allowlist")
                else:
                    self._allowed(target_id, mutate=True)
                if op == "terminate_app" and not (self.policy.allow_terminate or self.policy.allow_all):
                    raise AxisError("POLICY_DENIED", "Forced termination requires host authority")
                if op not in self._capabilities().get("actions", []):
                    raise AxisError("CAPABILITY_UNAVAILABLE", f"Action unavailable: {op}")
                for key in ("at", "start", "end"):
                    if key in args:
                        args[key] = self._resolve(args[key], session_id, target)
                        self._check(job, local_deadline)
                ordinal = len(job.steps)
                self._journal(job, ordinal, step["id"], "intention")
                self._check(job, local_deadline)
                try:
                    output = self._pal.dispatch(target, op, args, max(.001, local_deadline-time.monotonic()))
                    result["dispatch"] = "sent"
                except AxisError as exc:
                    result["dispatch"], result["error"] = exc.dispatch, exc.result()
                    job.steps.append(result)
                    raise
                except Exception:
                    result["dispatch"] = "unknown"
                    job.steps.append(result)
                    raise AxisError("EFFECT_UNKNOWN", "Native dispatch interrupted", dispatch="unknown")
                try:
                    self._journal(job, ordinal, step["id"], "sent")
                except Exception:
                    # The native ACK is already known. Failure to persist it
                    # prevents verified completion, not knowledge of its dispatch.
                    error = AxisError("JOURNAL_FAILED", "Input acknowledged but its journal update failed; do not replay", dispatch="unknown")
                    result["error"] = error.result()
                    job.steps.append(result)
                    raise error
                try:
                    if op == "open_app":
                        # Keep an acknowledged launch addressable even when its
                        # reply arrived too late. This is reconciliation data,
                        # not proof that a usable window was verified in time.
                        result["output"] = {k: output[k] for k in ("target_id", "process_id") if k in output}
                        self._created.add(output["target_id"])
                    self._check(job, local_deadline)
                    if op == "open_app":
                        target = self._bind(output["target_id"])
                        result["verification"] = "met"
                    elif op == "focus":
                        if not self._bind(target_id, target).get("is_active"):
                            raise AxisError("FOCUS_LOST", "Foreground verification failed")
                        result["output"] = {k: output[k] for k in ("activation_method",) if k in output}
                        result["verification"] = "met"
                    elif op in ("maximize_window", "restore_window", "minimize_window"):
                        expected = {"maximize_window": "maximized", "restore_window": "normal",
                                    "minimize_window": "minimized"}[op]
                        while True:
                            self._check(job, local_deadline)
                            observed = self._bind(target_id, target).get("window_state")
                            if observed is None:
                                raise AxisError("VERIFICATION_UNAVAILABLE", "Adapter did not expose window state")
                            if observed == expected:
                                break
                            job.cancel.wait(min(.025, max(0, local_deadline-time.monotonic())))
                        result["output"] = {"window_state": observed}
                        result["evidence"] = {"observed_at": time.time(), "predicate": "window_state"}
                        result["verification"] = "met"
                    elif op in ("close_window", "terminate_app"):
                        self._await(target, {"kind": "window_closed"}, job, local_deadline)
                        result["verification"] = "met"
                    if step.get("postcondition"):
                        result["verification"] = "unobservable"
                        self._await(target, step["postcondition"], job, local_deadline)
                        result["verification"] = "met"
                        result["evidence"] = {"observed_at": time.time(), "predicate": step["postcondition"]["kind"]}
                    self._check(job, local_deadline)
                except AxisError as exc:
                    result["verification"] = "unmet" if exc.code == "DEADLINE_EXCEEDED" else "unobservable"
                    error = AxisError(exc.code, str(exc), dispatch="sent")
                    result["error"] = error.result()
                    job.steps.append(result)
                    raise error from exc
                except Exception as exc:
                    # The dispatch acknowledgement is known, even if verification crashed.
                    error = AxisError("VERIFICATION_UNAVAILABLE", "Verification failed: "+type(exc).__name__, dispatch="sent")
                    result["verification"], result["error"] = "unobservable", error.result()
                    job.steps.append(result)
                    raise error from exc
                if result["verification"] == "unobservable" and step.get("verification", "required") != "dispatch_only":
                    job.steps.append(result)
                    raise AxisError("UNVERIFIED_EFFECT", "Supply a postcondition or explicitly request dispatch_only", dispatch="sent")
            # Native dispatch and replay verify within their effect-handling
            # paths. Pure/local control steps must not silently ignore the same
            # postcondition field exposed by the shared step contract.
            if op in {"observe", "if", "repeat", "await", "await_visual", "calibrate", "watch"}:
                try:
                    self._check(job, local_deadline)
                    if step.get("postcondition"):
                        result["verification"] = "unobservable"
                        self._await(target, step["postcondition"], job, local_deadline)
                except AxisError as exc:
                    result["verification"] = "unmet" if exc.code == "DEADLINE_EXCEEDED" else "unobservable"
                    result["error"] = exc.result()
                    with job.lock:
                        job.steps.append(result)
                    raise
                except Exception as exc:
                    error = AxisError("VERIFICATION_UNAVAILABLE", "Verification failed: "+type(exc).__name__)
                    result["error"] = error.result()
                    with job.lock:
                        job.steps.append(result)
                    raise error from exc
                if step.get("postcondition"):
                    result["verification"] = "met"
                    result["evidence"] = {"observed_at": time.time(), "predicate": step["postcondition"]["kind"]}
            outputs[step["id"]] = result.get("output", {})
            with job.lock:
                job.steps.append(result)

    def _job(self, job_id=None, action="status", cursor=None, idempotency_key=None):
        if (job_id is None) == (idempotency_key is None):
            raise AxisError("INVALID_REQUEST", "Use exactly one job_id or idempotency_key")
        if idempotency_key is not None:
            with self._lock:
                found = self._db.execute("SELECT job FROM requests WHERE key=?", (idempotency_key,)).fetchone()
            if not found:
                raise AxisError("JOB_NOT_FOUND", "No durable request has this idempotency key")
            job_id = found[0]
        job = self._jobs.get(job_id)
        if not job:
            with self._lock:
                row = self._db.execute("SELECT result FROM requests WHERE job=?", (job_id,)).fetchone()
            if row and row[0]:
                stored = json.loads(row[0])
                job = Job(job_id, status=stored["status"], steps=stored["steps"], error=stored["error"], cleanup=stored.get("cleanup"))
                job.done.set()
            elif row:
                # The process did not commit a terminal result. An intention does
                # not tell us whether input was sent; never resume these steps.
                with self._lock:
                    effects = self._db.execute("SELECT ordinal,step,phase FROM effects WHERE job=? ORDER BY ordinal", (job_id,)).fetchall()
                steps = [{"ordinal": ordinal, "id": step, "dispatch": "sent" if phase == "sent" else "unknown",
                          "verification": "unobservable", "provenance": "durable_effect_journal"}
                         for ordinal, step, phase in effects]
                job = Job(job_id, status="unknown", steps=steps,
                          error={"code": "EFFECT_UNKNOWN", "message": "Interrupted runtime; reconcile external effects before any new request", "dispatch": "unknown"})
                job.done.set()
            else:
                raise AxisError("JOB_NOT_FOUND", "Job not found in this runtime")
        if action == "cancel":
            job.cancel.set()
            self._cancel_native(job_id)
        with job.lock:
            visible_status = job.status if job.done.is_set() or job.status in ("accepted", "running") else "running"
            result = {"job_id": job_id, "status": visible_status, "completed_steps": sum(x["verification"] == "met" for x in job.steps),
                      "executed_steps": len(job.steps), "error": job.error}
            if job.cleanup is not None:
                result["cleanup"] = job.cleanup
            if action == "result":
                from .verification import effects_verified
                result["effects_verified"] = job.done.is_set() and job.status == "completed" and effects_verified(job.steps)
                from .job_pages import page_result
                return page_result(result, self._readback_steps(job.steps), cursor)
            from .job_pages import bounded_metadata
            return bounded_metadata(result)

    def _cancel_native(self, job_id):
        # The identity check and signal must be atomic relative to owner handoff.
        with self._control_lock:
            if job_id is not None and self._active_job == job_id and hasattr(self._pal, "cancel"):
                self._pal.cancel()

    def close(self):
        with self._lock:
            self._closed = True
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel.set()
        self._cancel_native(self._active_job)
        deadline = time.monotonic()+15
        for job in jobs:
            if not job.done.wait(max(0, deadline-time.monotonic())):
                raise AxisError("RUNTIME_BUSY", "Worker still stopping; do not dispose active resources")
        try:
            self._pal.close()
        finally:
            self._db.close()
