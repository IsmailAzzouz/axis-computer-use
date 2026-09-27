"""Resolve native ownership by contextual target identity, never by shared PID."""
from ..contracts import AxisError


def owned_handles(target, windows):
    root = next((w for w in windows if w["target_id"] == target["target_id"]), None)
    if root is None or root["identity"] != target["identity"]:
        raise AxisError("STALE_TARGET", "Owner window identity is no longer present")
    owned = {root["target_id"]: root["handle"]}
    for _ in range(8):
        added = {w["target_id"]: w["handle"] for w in windows if w.get("owner_target_id") in owned}
        if added.keys() <= owned.keys():
            break
        owned.update(added)
    return set(owned.values())
