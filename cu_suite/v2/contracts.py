"""Canonical JSON contracts shared by every transport. No native dependencies."""
from __future__ import annotations

import math

VERSION = "2.0"
MAX_STEPS = 256
MAX_SECONDS = 60.0
MAX_BYTES = 12 * 1024
KEY_NAMES = (['ctrl', 'shift', 'alt', 'meta', 'enter', 'tab', 'escape', 'space',
              'backspace', 'delete', 'left', 'up', 'right', 'down', 'home', 'end',
              'pageup', 'pagedown'] + [f'f{i}' for i in range(1, 25)]
             + list('abcdefghijklmnopqrstuvwxyz0123456789'))


class AxisError(Exception):
    def __init__(self, code, message, *, dispatch="not_sent"):
        super().__init__(message)
        self.code, self.dispatch = code, dispatch

    def result(self):
        return {"code": self.code, "message": str(self), "dispatch": self.dispatch}


def obj(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


STRING = {"type": "string", "minLength": 1, "maxLength": 4096}
BOOL = {"type": "boolean"}
SECONDS = {"type": "number", "minimum": 0.001, "maximum": MAX_SECONDS}
SELECTOR = {**obj({k: STRING for k in ("name", "role", "automation_id", "native_id")}), "minProperties": 1}
POINT = obj({"space": {"enum": ["frame", "client", "desktop"]},
             "x": {"type": "number"}, "y": {"type": "number"},
             "frame_id": STRING, "geometry_id": STRING}, ("space", "x", "y"))
LOCATOR = {**obj({"ref": STRING, "selector": SELECTOR, "point": POINT}), "minProperties": 1, "maxProperties": 1}
CONDITION = obj({"kind": {"enum": ["exists", "absent", "value", "name", "enabled", "focused", "visible", "selected", "window_closed", "window_state"]},
                 "selector": SELECTOR, "expected": {"type": ["string", "boolean", "number"]}}, ("kind",))
REGION = {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}
PROBE = obj({"name": {"type": "string", "minLength": 1, "maxLength": 64}, "region": REGION}, ("name", "region"))
PROFILE = obj({"probes": {"type": "array", "items": PROBE, "minItems": 1, "maxItems": 16},
               "on_threshold": {"type": "number", "minimum": 1, "maximum": 441},
               "off_threshold": {"type": "number", "minimum": 0, "maximum": 440},
               "interval": {"type": "number", "minimum": .005, "maximum": 1},
               "max_gap": {"type": "number", "minimum": .01, "maximum": 2},
               "min_pulse": {"type": "number", "minimum": .02, "maximum": 10}}, ("probes", "min_pulse"))

# Action arguments are deliberately disjoint from host permissions.
ACTION_ARGS = {
    "open_app": obj({"app": STRING, "args": {"type": "array", "items": STRING, "maxItems": 64}}, ("app",)),
    "focus": obj({"method": {"enum": ["native", "caption_click"]}}), "close_window": obj({}), "terminate_app": obj({}),
    "maximize_window": obj({}), "restore_window": obj({}), "minimize_window": obj({}),
    "click": obj({"at": LOCATOR, "button": {"enum": ["left", "right", "middle"]}, "count": {"enum": [1, 2]}}, ("at",)),
    "type_text": obj({"text": {"type": "string", "maxLength": 65536}, "at": LOCATOR, "replace": BOOL}, ("text",)),
    "paste_text": obj({"text": {"type": "string", "maxLength": 65536}, "at": LOCATOR, "replace": BOOL}, ("text",)),
    "keys": obj({"keys": {"type": "array", "items": {"enum": KEY_NAMES}, "minItems": 1, "maxItems": 8, "uniqueItems": True}, "hold": {"type": "number", "minimum": 0, "maximum": 5}}, ("keys",)),
    "move": obj({"at": LOCATOR}, ("at",)),
    "hover": obj({"at": LOCATOR, "duration": {"type": "number", "minimum": .01, "maximum": 5}}, ("at",)),
    "scroll": obj({"at": LOCATOR, "amount": {"type": "integer", "minimum": -100, "maximum": 100}, "axis": {"enum": ["vertical", "horizontal"]}}, ("at", "amount")),
    "drag": obj({"start": LOCATOR, "end": LOCATOR, "duration": SECONDS, "button": {"enum": ["left", "right"]}}, ("start", "end")),
    "swipe": obj({"start": LOCATOR, "end": LOCATOR, "duration": SECONDS}, ("start", "end")),
    "set_slider": obj({"at": LOCATOR, "value": {"type": "number"}}, ("at", "value")),
    "await": obj({"condition": CONDITION, "timeout": SECONDS, "stable_for": {"type": "number", "minimum": 0, "maximum": 10}}, ("condition",)),
    "await_visual": obj({"baseline_frame_id": STRING, "region": REGION,
        "masks": {"type": "array", "items": REGION, "maxItems": 32}, "timeout": SECONDS,
        "stable_for": {"type": "number", "minimum": .05, "maximum": 10},
        "require_change": {**BOOL, "default": True, "description": "True waits for a NEW change after the baseline, then stability. Set false to wait only for stability after an earlier action."},
        "threshold": {"type": "number", "minimum": 1, "maximum": 255, "default": 8}}, ()),
    "observe": obj({"query": SELECTOR}),
    "calibrate": obj({"profile": PROFILE}, ("profile",)),
    "watch": obj({"profile_id": STRING, "until": CONDITION, "duration": SECONDS, "trigger": {"$ref": "step"}}, ("profile_id", "until")),
    "replay": obj({"watch_step": STRING, "interval": {"type": "number", "minimum": .01, "maximum": 2}}, ("watch_step",)),
    "if": obj({"condition": CONDITION, "then": {"$ref": "steps"}, "else": {"$ref": "steps"}}, ("condition", "then")),
    "repeat": obj({"count": {"type": "integer", "minimum": 1, "maximum": MAX_STEPS}, "steps": {"$ref": "steps"}}, ("count", "steps")),
}
STEP_BASE = obj({"id": STRING, "op": {"enum": list(ACTION_ARGS)}, "target_id": STRING,
            "target_from": STRING, "args": {"type": "object"}, "precondition": CONDITION,
            "postcondition": CONDITION, "timeout": SECONDS,
            "verification": {"enum": ["required", "dispatch_only"]}}, ("id", "op"))
STEP = {"oneOf": [obj({**STEP_BASE["properties"], "op": {"enum": [op]}, "args": schema},
                            ("id", "op", "args") if schema.get("required") else ("id", "op"))
                  for op, schema in ACTION_ARGS.items()]}
STEPS = {"type": "array", "items": {"$ref": "step"}, "minItems": 1, "maxItems": MAX_STEPS}
SCHEMAS = {
    "axis.help": obj({"topic": {"enum": ["start", "run", "actions", "errors"]},
                      "action": {"enum": list(ACTION_ARGS)}}),
    "axis.targets": obj({"cursor": STRING}),
    "axis.observe": obj({"target_id": STRING, "session_id": STRING, "scope": {"enum": ["tree", "capabilities", "ocr", "diff", "visual_diff", "events"]}, "since": STRING, "cursor": STRING, "region": REGION, "query": SELECTOR, "action": {"enum": list(ACTION_ARGS)}}),
    "axis.run": obj({"session_id": STRING, "steps": STEPS, "idempotency_key": STRING, "timeout": SECONDS,
                     "async": BOOL, "recipe": {"enum": ["sequence-memory.play@1"]},
                     "recipe_args": obj({"profile_id": STRING, "trigger": {"$ref": "step"}, "player_turn": CONDITION, "accepted": CONDITION}, ("profile_id", "trigger", "player_turn", "accepted"))}, ("session_id", "idempotency_key")),
    "axis.job": {**obj({"job_id": STRING, "idempotency_key": STRING,
                        "action": {"enum": ["status", "result", "cancel"]}, "cursor": STRING}),
                 "oneOf": [obj({identity: STRING, "action": {"enum": ["status", "result", "cancel"]}, "cursor": STRING}, (identity,))
                           for identity in ("job_id", "idempotency_key")]},
    "axis.capture": obj({"session_id": STRING, "region": REGION, "include_image": BOOL}, ("session_id",)),
}
DESCRIPTIONS = {
    "axis.help": 'New here? Call {}. Short guide + copyable run example. Need one action? {"action":"click"}. Works offline. No input sent.',
    "axis.targets": 'Find allowed windows and apps. Call {}. Pick target_id. Then axis.observe({"target_id":"..."}). No clicks.',
    "axis.observe": 'Read UI as text. Give target_id first; get session_id and elements. Later give session_id. No focus. Need action syntax? Use axis.help.',
    "axis.run": 'Do actions in order. Need session_id, fresh idempotency_key, steps. Each step: id, op, args. Stop on error. First time? axis.help({"topic":"run"}).',
    "axis.job": 'Read or cancel job. Give job_id OR original idempotency_key. action: status, result, cancel. Lost reply? Look here; no new-key retry.',
    "axis.capture": 'Get window image + geometry. Need session_id. Optional region [left,top,right,bottom]. Use only when text not enough.',
}


def validate(value, schema, path="request", depth=0, definitions=None):
    if depth > 24:
        raise AxisError("INVALID_REQUEST", "Maximum nesting exceeded")
    definitions = schema.get("$defs", definitions) or {"step": STEP, "steps": STEPS}
    if "$ref" in schema:
        schema = definitions[schema["$ref"].removeprefix("#/$defs/")]
    for branch in schema.get("allOf", []):
        validate(value, branch, path, depth, definitions)
    if "oneOf" in schema:
        branches = schema["oneOf"]
        if isinstance(value, dict) and "op" in value:
            branches = [b for b in branches if value["op"] in b.get("properties", {}).get("op", {}).get("enum", [])]
            if len(branches) == 1:
                validate(value, branches[0], path, depth+1, definitions)
                return
        matches = 0
        for branch in branches:
            try:
                validate(value, branch, path, depth+1, definitions)
                matches += 1
            except AxisError:
                pass
        if matches != 1:
            raise AxisError("INVALID_REQUEST", f"{path}: must match exactly one operation schema")
        return
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
              "string": lambda: isinstance(value, str), "boolean": lambda: type(value) is bool,
              "integer": lambda: type(value) is int, "number": lambda: type(value) in (int, float) and math.isfinite(value)}
    if types and not any(checks[t]() for t in types):
        raise AxisError("INVALID_REQUEST", f"{path}: expected {types}")
    if "enum" in schema and not any(type(value) is type(choice) and value == choice for choice in schema["enum"]):
        raise AxisError("INVALID_REQUEST", f"{path}: invalid choice")
    if isinstance(value, dict):
        if not schema.get("minProperties", 0) <= len(value) <= schema.get("maxProperties", 100000):
            raise AxisError("INVALID_REQUEST", f"{path}: wrong number of properties")
        missing = [k for k in schema.get("required", []) if k not in value]
        if missing:
            raise AxisError("INVALID_REQUEST", f"{path}: missing required field(s): {', '.join(missing)}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise AxisError("INVALID_REQUEST", f"{path}: unknown fields {sorted(set(value)-set(props))}")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], path+"."+k, depth+1, definitions)
    if isinstance(value, list):
        if schema.get("uniqueItems") and any(v in value[:i] for i, v in enumerate(value)):
            raise AxisError("INVALID_REQUEST", f"{path}: duplicate entries")
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100000):
            raise AxisError("INVALID_REQUEST", f"{path}: invalid array length")
        for v in value:
            validate(v, schema.get("items", {}), path+"[]", depth+1, definitions)
    if isinstance(value, str) and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 100000):
        raise AxisError("INVALID_REQUEST", f"{path}: invalid string length")
    if type(value) in (int, float) and not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
        raise AxisError("INVALID_REQUEST", f"{path}: outside allowed range")


def compile_steps(steps, known=None, depth=0):
    """Validate every branch before effects; count worst-case executed steps."""
    if depth > 8:
        raise AxisError("INVALID_PLAN", "Plan nesting exceeds 8")
    validate(steps, STEPS)
    known = set() if known is None else set(known)
    total = 0
    for step in steps:
        if step["id"] in known:
            raise AxisError("INVALID_PLAN", "Duplicate step id")
        if step.get("target_from") not in known and "target_from" in step:
            raise AxisError("INVALID_PLAN", "target_from must refer to an earlier step")
        if "target_id" in step and "target_from" in step:
            raise AxisError("INVALID_PLAN", "Choose target_id or target_from")
        args = step.get("args", {})
        validate(args, ACTION_ARGS[step["op"]], step["id"]+".args")
        for condition in [step.get("precondition"), step.get("postcondition"), args.get("condition"), args.get("until")]:
            if condition and condition["kind"] not in ("window_closed", "window_state") and not condition.get("selector"):
                raise AxisError("INVALID_PLAN", "Predicate requires a nonempty selector")
            if condition:
                kind = condition["kind"]
                if kind in ("name", "value") and "expected" not in condition:
                    raise AxisError("INVALID_PLAN", "Property predicate requires expected")
                if kind == "name" and not isinstance(condition.get("expected"), str):
                    raise AxisError("INVALID_PLAN", "Name predicate expects text")
                if kind in ("focused", "enabled", "visible", "selected") and type(condition.get("expected", True)) is not bool:
                    raise AxisError("INVALID_PLAN", "State predicate expects a boolean")
                if kind == "window_state" and condition.get("expected") not in ("normal", "minimized", "maximized"):
                    raise AxisError("INVALID_PLAN", "Window state expects normal, minimized or maximized")
                if kind in ("window_state", "window_closed") and condition.get("selector"):
                    raise AxisError("INVALID_PLAN", "Window predicates apply to the bound target, not an element selector")
        if step["op"] in ("paste_text", "replay") and not step.get("postcondition"):
            raise AxisError("INVALID_PLAN", "Paste/replay requires an observed postcondition")
        if step["op"] in {"click", "type_text", "paste_text", "keys", "move", "hover", "scroll", "drag", "swipe", "set_slider", "replay"}:
            if not step.get("postcondition") and step.get("verification", "required") != "dispatch_only":
                raise AxisError("INVALID_PLAN", "Mutation requires a postcondition or explicit dispatch_only")
        for name in ("at", "start", "end"):
            if name in args:
                loc = args[name]
                if len(loc) != 1 or ("selector" in loc and not loc["selector"]):
                    raise AxisError("INVALID_PLAN", "Locator must have one nonempty ref, selector, or point")
                p = loc.get("point", {})
                if p.get("space") == "frame" and "frame_id" not in p:
                    raise AxisError("INVALID_PLAN", "Frame point requires frame_id")
                if p.get("space") in ("client", "desktop") and "geometry_id" not in p:
                    raise AxisError("INVALID_PLAN", "Point requires current geometry_id")
        total += 1
        if step["op"] == "repeat":
            total += args["count"] * compile_steps(args["steps"], known, depth+1)
        if step["op"] == "if":
            total += max(compile_steps(args["then"], known, depth+1), compile_steps(args["else"], known, depth+1) if args.get("else") else 0)
        if step["op"] == "watch" and "trigger" in args:
            if args["trigger"]["op"] not in {"click", "keys"}:
                raise AxisError("INVALID_PLAN", "Watch trigger must be a click or keys")
            total += compile_steps([args["trigger"]], known, depth+1)
        if step["op"] == "replay" and args["watch_step"] not in known:
            raise AxisError("INVALID_PLAN", "replay requires an earlier watch")
        known.add(step["id"])
    if total > MAX_STEPS:
        raise AxisError("BUDGET_EXCEEDED", "Plan exceeds executed step budget")
    return total


def tool_definitions():
    # Resolve internal refs to standard, self-contained JSON Schema $defs.
    import copy
    definitions = []
    for name, schema in SCHEMAS.items():
        schema = copy.deepcopy(schema)
        if name == "axis.run":
            # Same strict contract, without repeating every shared field for
            # every operation. Per-op args remain closed and fully validated.
            branches = []
            for op, args in ACTION_ARGS.items():
                branch = obj({"op": {"enum": [op]}, "args": copy.deepcopy(args)},
                             ("args",) if args.get("required") else ())
                del branch["additionalProperties"]
                branches.append(branch)
            shared = copy.deepcopy(STEP_BASE)
            shared["properties"] = {k: copy.deepcopy(v) for k, v in STEP_BASE["properties"].items()}
            shared["properties"]["id"]["description"] = "Unique step name, e.g. write."
            shared["properties"]["args"]["description"] = "Action parameters. See axis.help(action=op)."
            shared["properties"]["postcondition"]["description"] = "UI fact that must become true."
            shared["properties"]["verification"]["description"] = "dispatch_only = unverified input, NOT task success. Prefer postcondition."
            schema["$defs"] = {"step": {"allOf": [shared, {"oneOf": branches}]}, "steps": copy.deepcopy(STEPS)}
            # Common locators/conditions also occur in nested actions.
            common = {"locator": LOCATOR, "condition": CONDITION, "selector": SELECTOR,
                      "text": STRING, "seconds": SECONDS, "region": REGION}
            def compact(node):
                if isinstance(node, dict):
                    for key, value in common.items():
                        if node == value:
                            return {"$ref": key}
                    return {key: compact(value) for key, value in node.items()}
                if isinstance(node, list):
                    return [compact(value) for value in node]
                return node
            schema = compact(schema)
            schema["$defs"].update(copy.deepcopy(common))
        def rewrite(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    node["$ref"] = "#/$defs/" + node["$ref"]
                for value in node.values():
                    rewrite(value)
            elif isinstance(node, list):
                for value in node:
                    rewrite(value)
        rewrite(schema)
        definitions.append({"name": name, "description": DESCRIPTIONS[name], "inputSchema": schema})
    return definitions
