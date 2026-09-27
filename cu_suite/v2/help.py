"""Small offline guide. Examples are data, never an alternate action runner."""
import copy

from .contracts import ACTION_ARGS, SCHEMAS, VERSION, tool_definitions, validate


def run_example():
    return {"session_id": "SESSION", "idempotency_key": "edit-001", "steps": [
        {"id": "focus", "op": "focus"},
        {"id": "write", "op": "type_text",
         "args": {"at": {"selector": {"name": "Input"}}, "text": "Hello", "replace": True},
         "postcondition": {"kind": "value", "selector": {"name": "Input"}, "expected": "Hello"}},
        {"id": "read", "op": "observe"}]}


def action_example(action):
    """Small, complete plans for common actions; placeholders never imply authority."""
    field = {"selector": {"name": "Input"}}
    value = {"kind": "value", "selector": {"name": "Input"}, "expected": "Hello"}
    steps = {
        "focus": {"id": "focus", "op": "focus"},
        "click": {"id": "click", "op": "click", "args": {"at": field},
                  "postcondition": {"kind": "focused", "selector": {"name": "Input"}, "expected": True}},
        "type_text": {"id": "write", "op": "type_text",
                      "args": {"at": field, "text": "Hello", "replace": True}, "postcondition": value},
        "paste_text": {"id": "paste", "op": "paste_text",
                       "args": {"at": field, "text": "Hello", "replace": True}, "postcondition": value},
        "keys": {"id": "select", "op": "keys", "args": {"keys": ["ctrl", "a"]},
                 "verification": "dispatch_only"},
        "scroll": {"id": "scroll", "op": "scroll",
                   "args": {"at": {"selector": {"name": "List"}}, "amount": -3},
                   "verification": "dispatch_only"},
        "close_window": {"id": "close", "op": "close_window"},
    }
    if action == "open_app":
        plan = [{"id": "open", "op": "open_app", "args": {"app": "ALLOWED_APP", "args": []}},
                {"id": "focus", "op": "focus", "target_from": "open"},
                {"id": "read", "op": "observe", "target_from": "open"}]
    elif action in steps:
        plan = ([] if action in ("focus", "close_window") else [{"id": "focus", "op": "focus"}]) + [steps[action]]
        if action != "close_window":
            plan.append({"id": "read", "op": "observe"})
    else:
        return None
    return {"tool": "axis.run", "arguments": {
        "session_id": "SESSION", "idempotency_key": "example-001", "steps": plan}}


def guide(arguments=None):
    arguments = {} if arguments is None else arguments
    validate(arguments, SCHEMAS["axis.help"])
    topic = arguments.get("topic", "start")
    result = {"version": VERSION, "topic": topic}
    if "action" in arguments:
        action = arguments["action"]
        result.update(topic="action", action=action,
                      guide="Step = id + op + args. Put step inside run.steps. Syntax only; axis.targets shows host capabilities.",
                      args_schema=copy.deepcopy(ACTION_ARGS[action]))
        example = action_example(action)
        if example:
            result["example"] = example
            result["guide"] = (
                'Copy example.arguments into axis.run. SESSION = observe result. '
                'Input/List = exact observed name. ALLOWED_APP = targets app. Fresh key per NEW plan. '
                'Change postcondition to wanted UI fact. Example click checks field focus only. '
                'keys/scroll example: sent only, NOT verified. Observe does not certify earlier steps.')
            if action == "open_app":
                result["guide"] += ' First observe({}) for desktop SESSION. target_from uses opened window.'
        # Recursive actions need their definitions too. Keep ordinary actions tiny.
        if action in ("watch", "if", "repeat"):
            schema = next(t["inputSchema"] for t in tool_definitions() if t["name"] == "axis.run")
            def refs(node):
                if isinstance(node, dict):
                    return {k: "#/$defs/"+v if k == "$ref" else refs(v) for k, v in node.items()}
                if isinstance(node, list):
                    return [refs(v) for v in node]
                return node
            result["args_schema"] = {**refs(result["args_schema"]), "$defs": schema["$defs"]}
        result["rules"] = (
            "paste_text/replay: postcondition required. Other input: prefer postcondition; "
            "dispatch_only means unverified. at = {selector:{name:...}} OR {ref:...} OR {point:...}. "
            "Use observed IDs/names. Frame point needs frame_id; client/desktop point needs geometry_id.")
        return result
    if topic in ("start", "run"):
        result["guide"] = (
            '1. targets({}) -> choose target_id.\n'
            '2. observe({"target_id":"..."}) -> keep session_id + names.\n'
            '3. Copy example.arguments into run. SESSION = session_id. Input = observed field name.\n'
            'Many steps. One call. Fresh key per NEW plan. args = action inputs. postcondition = wanted UI fact.\n'
            'Sent != verified. Check steps + effects_verified. dispatch_only = unverified, NOT success.\n'
            'Running? job({"job_id":"...","action":"result"}). '
            'Lost reply/unknown? job({"idempotency_key":"ORIGINAL-KEY","action":"result"}). No new-key retry.\n'
            'Text first. capture only if needed.')
        result["example"] = {"tool": "axis.run", "arguments": run_example()}
        result["more"] = 'help({"action":"click"}) = exact args. help({"topic":"actions"}) = list. help({"topic":"errors"}) = recovery.'
        if topic == "run":
            result["extra"] = (
                'Open app: observe({}) -> desktop session; run open_app args:{app:"allowed-app",args:[]}. '
                'Next step target_from:"open-step-id" uses new window. Otherwise steps use session target. '
                'IDs unique. Selectors exact, unique. Add await for delayed UI. Max 256 steps/60s. '
                'Long plan: async:true; read axis.job. next_cursor: fetch next page, same tool/session/job.')
    elif topic == "actions":
        result["actions"] = list(ACTION_ARGS)
        result["guide"] = ('All actions go in run.steps. help({"action":"NAME"}) gives exact args. '
                           'Syntax != availability: targets gives host capabilities/apps. '
                           'click button:right = right click; count:2 = double click. keys:["ctrl","a"] = chord. '
                           'type_text = Unicode input. paste_text = clipboard. close_window != terminate_app. '
                           'Simon: calibrate, watch, replay; known zones + player-turn/acceptance cues required. No model video.')
    else:
        result["guide"] = (
            'INVALID_REQUEST/INVALID_PLAN + not_sent: fix JSON; help(action) gives args. '
            'HOST_NOT_CONFIGURED/BROKER_UNAVAILABLE: ask operator start authorized host. Help works offline; not proof desktop ready. '
            'CAPABILITY_UNAVAILABLE: do not invent backend. '
            'ADAPTER_CONTRACT_ERROR: host adapter invalid; ask operator. '
            'CLIPBOARD_UNSUPPORTED: clipboard kept safe; ask operator or use type_text in a new plan after not_sent. '
            'FOCUS_DENIED: stop; ask operator activate target. Never type elsewhere. '
            'Stale/ambiguous target: observe again; choose exact target. '
            'Partial/unknown/lost reply: job with original key; inspect effects before new plan. '
            'INPUT_UNRECONCILED/CLEANUP_FAILED: operator reconcile held input; restart is not proof of cleanup. '
            'Incomplete/failed observation: missing element not proof absent. Save dialog: no forced close without permission. '
            'cancel stops future work, not undo. Follow next_cursor for remaining result pages.')
    return result
