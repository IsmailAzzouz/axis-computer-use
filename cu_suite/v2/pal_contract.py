"""Portable adapter admission. Structural checks are not native certification."""
import json
import math

from .contracts import ACTION_ARGS, AxisError

LOCAL_OPERATIONS = frozenset({"if", "repeat", "await", "await_visual", "observe", "calibrate", "watch", "replay"})
NATIVE_OPERATIONS = frozenset(ACTION_ARGS)-LOCAL_OPERATIONS
FLAGS = ("interactive", "accessibility", "targeted_accessibility", "capture", "ocr", "subscriptions", "temporal_capture")
FEATURE_PORTS = {"accessibility": "inspect", "capture": "capture", "ocr": "ocr",
                 "subscriptions": "events", "temporal_capture": "open_observer"}


def _invalid(message):
    raise AxisError("ADAPTER_CONTRACT_ERROR", message)


def _require_ports(adapter, names):
    for name in names:
        if not callable(getattr(adapter, name, None)):
            _invalid(f"Adapter requires callable port: {name}")


def read_capabilities(adapter):
    _require_ports(adapter, ("capabilities", "targets", "bind", "release", "close"))
    raw = adapter.capabilities()
    if not isinstance(raw, dict):
        _invalid("Adapter capabilities must be an object")
    actions = raw.get("actions")
    if not isinstance(actions, list) or len(actions) > len(NATIVE_OPERATIONS):
        _invalid("Adapter actions must be a bounded list of native operations")
    if any(not isinstance(op, str) or op not in NATIVE_OPERATIONS for op in actions):
        _invalid("Adapter advertised unknown or engine-owned operations")
    if len(set(actions)) != len(actions):
        _invalid("Adapter actions must be unique")
    for flag in FLAGS:
        if flag in raw and type(raw[flag]) is not bool:
            _invalid(f"Adapter capability must be boolean: {flag}")
    if raw.get("targeted_accessibility") and not raw.get("accessibility"):
        _invalid("Targeted accessibility requires accessibility")
    if raw.get("temporal_capture") and not raw.get("capture"):
        _invalid("Continuous observation requires capture")
    if actions:
        _require_ports(adapter, ("dispatch",))
    for feature, port in FEATURE_PORTS.items():
        if raw.get(feature):
            _require_ports(adapter, (port,))
    try:
        # Freeze a JSON snapshot: callers cannot mutate the returned actions while
        # a plan is being admitted. Metadata is bounded and must also be portable.
        wire = json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(wire.encode("utf-8")) > 8192:
            _invalid("Adapter capability metadata exceeds 8 KiB")
        return json.loads(wire)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        _invalid("Adapter capabilities must contain finite JSON data")


def validate_adapter(adapter):
    """Host factory gate. Never dispatches input; returns validated capabilities.

    Physical-input adapters additionally need desktop-wide ownership, cancellation
    and cleanup reporting. In-process test doubles can use read_capabilities alone.
    Native semantics still require the published conformance scenarios.
    """
    capabilities = read_capabilities(adapter)
    if capabilities["actions"]:
        _require_ports(adapter, ("acquire_lease", "release_lease", "cancel", "cleanup_status"))
    return capabilities


def validate_target(raw):
    """Independent JSON snapshot; native identity/geometry truth remains PAL-owned."""
    if not isinstance(raw, dict):
        _invalid("Adapter target must be an object")
    for field in ("target_id", "identity", "geometry_id"):
        value = raw.get(field)
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            _invalid(f"Adapter target requires a bounded nonempty string: {field}")
    if raw["target_id"] == "desktop":
        _invalid("Desktop is an engine session, not a native window target")
    for field, length in (("bounds", 4), ("client_origin", 2)):
        value = raw.get(field)
        if (not isinstance(value, list) or len(value) != length or
                any(type(n) not in (int, float) or not -2**31 <= n <= 2**31-1 or
                    not math.isfinite(n) for n in value)):
            _invalid(f"Adapter target requires finite pixel coordinates: {field}")
    left, top, right, bottom = raw["bounds"]
    # Collapsed/minimized windows remain discoverable; actionability is separate.
    if right < left or bottom < top:
        _invalid("Adapter target bounds are inverted")
    for field in ("is_active", "minimized", "launch_candidate"):
        if field in raw and type(raw[field]) is not bool:
            _invalid(f"Adapter target field must be boolean: {field}")
    if "title" in raw and not isinstance(raw["title"], str):
        _invalid("Adapter target title must be a string")
    owner = raw.get("owner_target_id")
    if owner is not None and (not isinstance(owner, str) or not 1 <= len(owner) <= 4096 or
                              owner in ("desktop", raw["target_id"])):
        _invalid("Adapter target owner must name a different native window")
    try:
        wire = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return json.loads(wire)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        _invalid("Adapter target must contain finite JSON data")


def read_targets(adapter):
    raw = adapter.targets()
    if not isinstance(raw, list):
        _invalid("Adapter targets must be a list")
    targets = {}
    for item in raw:
        target = validate_target(item)
        if target["target_id"] in targets:
            _invalid("Adapter discovery returned duplicate target IDs")
        targets[target["target_id"]] = target
    return targets


def read_target(adapter, target_id, previous=None):
    target = validate_target(adapter.bind(target_id))
    if target["target_id"] != target_id:
        _invalid("Adapter binding returned a different target ID")
    if previous and target["identity"] != previous["identity"]:
        raise AxisError("STALE_TARGET", "Target identity changed")
    if previous and target["geometry_id"] == previous["geometry_id"]:
        if any(target.get(field) != previous.get(field) for field in ("bounds", "client_origin", "dpi")):
            _invalid("Adapter changed window geometry without changing geometry ID")
    return target
