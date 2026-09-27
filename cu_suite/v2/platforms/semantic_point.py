"""Readback guard for a semantic point resolved earlier by the runner."""
from ..contracts import AxisError


def verify_semantic_point(point, observation):
    if observation.get("coverage") != "complete":
        raise AxisError("OBSERVATION_INCOMPLETE", "Cannot revalidate semantic point coverage")
    matches = [e for e in observation["elements"] if e["native_id"] == point["native_id"]]
    if len(matches) != 1:
        raise AxisError("STALE_REFERENCE", "Resolved native element disappeared or became ambiguous")
    element = matches[0]
    if not element.get("enabled", False) or not element.get("visible", False):
        raise AxisError("ELEMENT_NOT_ACTIONABLE", "Resolved element is no longer actionable")
    if list(element["bounds"]) != point["resolved_bounds"]:
        raise AxisError("STALE_ELEMENT_GEOMETRY", "Element moved inside the window; resolve a fresh point before acting")
    l, t, r, b = element["bounds"]
    if not l <= point["x"] < r or not t <= point["y"] < b:
        raise AxisError("INVALID_POINT", "Resolved point is outside its element")
