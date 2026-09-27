"""Native filtered UIA walking: no unbounded GetChildren/FindAll materialization.

The walker condition is evaluated by UI Automation; output completeness means
all matches in the authorized window/owned roots, not an exhaustive desktop tree.
Provider calls remain bounded by the supervising process timeout.
"""
import time
from array import array
from contextlib import contextmanager
from ..contracts import AxisError


MAX_EDIT_TEXT_UNITS = 4096


@contextmanager
def provider_read(error_types, stage):
    """Keep native error codes, never provider strings that may contain UI text."""
    diagnostic = {"stage": stage}
    try:
        yield diagnostic
    except error_types as exc:
        hresult = getattr(exc, "hresult", None)
        code = f"0x{hresult & 0xffffffff:08X}" if type(hresult) is int else "unavailable"
        raise AxisError("OBSERVATION_UNAVAILABLE",
                        f"Native accessibility {diagnostic['stage']} failed (HRESULT {code})") from None


def edit_text(auto, node):
    """Read a text-only edit provider without pretending a clipped prefix is its value."""
    pattern = node.GetPattern(auto.PatternId.TextPattern)
    if not pattern:
        return None
    text = pattern.DocumentRange.GetText(MAX_EDIT_TEXT_UNITS + 1)
    if not isinstance(text, str):
        raise AxisError("OBSERVATION_UNAVAILABLE", "Native edit text is not available")
    # UIA limits UTF-16 units, while Python len counts Unicode code points.
    if len(text.encode("utf-16-le", errors="surrogatepass")) // 2 > MAX_EDIT_TEXT_UNITS:
        raise AxisError("OBSERVATION_INCOMPLETE", "Native edit text exceeds the bounded read; value is not complete")
    return text


def read_controls(auto, uia, roots, query=None, *, limit=512, seconds=8, cancel=None, provider_errors=()):
    with provider_read(provider_errors, "filter") as diagnostic:
        return _read_controls(auto, uia, roots, query, limit=limit, seconds=seconds,
                              cancel=cancel, diagnostic=diagnostic)


def _read_controls(auto, uia, roots, query, *, limit, seconds, cancel, diagnostic):
    query = query or {}
    condition = uia.CreateTrueCondition()
    for key, value in query.items():
        if key == "native_id":
            continue  # Runtime IDs are compared locally; never parse model code.
        properties = {"name": auto.PropertyId.NameProperty,
                      "role": auto.PropertyId.ControlTypeProperty,
                      "automation_id": auto.PropertyId.AutomationIdProperty}
        if key == "role":
            value = getattr(auto.ControlType, value+"Control", None)
            if value is None:
                raise AxisError("INVALID_SELECTOR", "Unknown native accessibility role")
        condition = uia.CreateAndCondition(condition, uia.CreatePropertyCondition(properties[key], value))
    deadline = time.monotonic()+seconds
    visited, elements, seen = 0, [], set()
    truncated = False

    def inside(element, boundary):
        # Filtered walkers may skip a nonmatching window ancestor and return a
        # sibling from another window. Check raw ancestry BEFORE reading fields.
        for _ in range(64):
            if not element:
                return False
            if uia.CompareElements(element, boundary):
                return True
            element = uia.RawViewWalker.GetParentElement(element)
        raise AxisError("OBSERVATION_INCOMPLETE", "Cannot establish accessibility scope ancestry")

    class TraversalCycle(Exception):
        pass

    def children(element, boundary, walker):
        siblings = set()
        child = walker.GetFirstChildElement(element)
        while child:
            if not inside(child, boundary):
                break
            native_id = str(child.GetRuntimeId())
            if native_id in siblings or uia.CompareElements(child, element):
                raise TraversalCycle()
            siblings.add(native_id)
            yield child
            child = walker.GetNextSiblingElement(child)

    def search_root(root):
        # Unlike plain FindFirst, BuildCache can search the raw tree. Only the
        # returned element is cached; never materialize a descendant array.
        cache = uia.CreateCacheRequest()
        cache.TreeScope = 1  # TreeScope_Element
        cache.TreeFilter = uia.CreateTrueCondition()
        remaining = condition
        found = set()
        while True:
            diagnostic["stage"] = "search"
            element = root.Element.FindFirstBuildCache(7, remaining, cache)  # TreeScope_Subtree
            if not element:
                return
            if not inside(element, root.Element):
                raise AxisError("OBSERVATION_UNAVAILABLE", "Native accessibility search escaped its window scope")
            diagnostic["stage"] = "identity"
            identity = tuple(element.GetRuntimeId())
            if (not identity or len(identity) > 64 or
                    any(type(part) is not int or not -(2**31) <= part < 2**31 for part in identity)):
                raise AxisError("OBSERVATION_UNAVAILABLE", "Native accessibility runtime identity is invalid")
            if identity in found:
                raise TraversalCycle()
            found.add(identity)
            # SAFEARRAY(I4), not a tuple/list marshalled as SAFEARRAY(VARIANT).
            exclusion = uia.CreatePropertyCondition(auto.PropertyId.RuntimeIdProperty, array("i", identity))
            remaining = uia.CreateAndCondition(remaining, uia.CreateNotCondition(exclusion))
            yield element

    def walk_root(root, *, search=False):
        nonlocal visited, truncated
        diagnostic["stage"] = "root"
        if search:
            iterator = search_root(root)
        else:
            # Keep the window boundary in the filtered tree. Some native menu
            # providers nevertheless cycle through normalized filtered siblings.
            root_condition = uia.CreatePropertyCondition(auto.PropertyId.NativeWindowHandleProperty,
                                                          root.Element.CurrentNativeWindowHandle)
            walker = uia.CreateTreeWalker(uia.CreateOrCondition(condition, root_condition))
            first = root.Element.FindFirst(1, condition)
            iterator = iter([first]) if first else children(root.Element, root.Element, walker)
        stack = [(iterator, frozenset())]
        while stack:
            if visited >= limit or time.monotonic() >= deadline:
                truncated = True
                break
            if cancel is not None and cancel.is_set():
                raise AxisError("CANCELLED", "Accessibility read cancelled")
            diagnostic["stage"] = "walk"
            iterator, ancestors = stack[-1]
            element = next(iterator, None)
            # A late NULL is not proof of exhaustion within the requested budget.
            if time.monotonic() >= deadline:
                truncated = True
                break
            if cancel is not None and cancel.is_set():
                raise AxisError("CANCELLED", "Accessibility read cancelled")
            if element is None:
                stack.pop()
                continue
            visited += 1
            diagnostic["stage"] = "identity"
            node = auto.Control.CreateControlFromElement(element)
            if node is None:
                raise AxisError("OBSERVATION_UNAVAILABLE", "Native control cannot be represented")
            native_id = str(node.GetRuntimeId())
            if native_id in ancestors:
                raise TraversalCycle()
            if native_id in seen:
                # Owned roots may also appear under their owner's UIA tree.
                continue
            seen.add(native_id)
            if not query.get("native_id") or query["native_id"] == native_id:
                diagnostic["stage"] = "properties"
                sensitive = bool(node.IsPassword)
                value = None
                value_source = None
                selected = None
                if not sensitive:
                    diagnostic["stage"] = "value"
                    pattern = node.GetPattern(auto.PatternId.ValuePattern)
                    if pattern:
                        value = pattern.Value
                    else:
                        pattern = node.GetPattern(auto.PatternId.RangeValuePattern)
                        if pattern:
                            value = pattern.Value
                        elif node.ControlTypeName == "EditControl":
                            # Excel cell/formula editors expose TextPattern, not
                            # ValuePattern. Do not treat arbitrary document text
                            # as a scalar value or use application-specific APIs.
                            value = edit_text(auto, node)
                            if value is not None:
                                value_source = "uia_text_pattern"
                    diagnostic["stage"] = "selection"
                    selection = node.GetPattern(auto.PatternId.SelectionItemPattern)
                    if selection:
                        selected = selection.IsSelected
                        if type(selected) is not bool:
                            raise AxisError("OBSERVATION_UNAVAILABLE", "Native selection state is not a boolean")
                diagnostic["stage"] = "geometry"
                rect = node.BoundingRectangle
                diagnostic["stage"] = "properties"
                item = {"native_id": native_id, "role": node.ControlTypeName.removesuffix("Control"),
                        "name": "[redacted]" if sensitive else node.Name,
                        "automation_id": node.AutomationId, "value": "[redacted]" if sensitive else value,
                        "enabled": bool(node.IsEnabled), "visible": not node.IsOffscreen,
                        "focused": bool(node.HasKeyboardFocus), "sensitive": sensitive,
                        "selected": selected,
                        "bounds": [rect.left, rect.top, rect.right, rect.bottom]}
                if value_source:
                    item["value_source"] = value_source
                if all(item.get(k) == v for k, v in query.items()):
                    elements.append(item)
            if search:
                continue  # Native subtree search already includes descendants.
            if len(stack) >= 32:
                diagnostic["stage"] = "walk"
                if walker.GetFirstChildElement(element):
                    truncated = True
            else:
                stack.append((children(element, root.Element, walker), ancestors | {native_id}))

    for root in roots:
        first_element, prior_seen = len(elements), seen.copy()
        try:
            walk_root(root)
        except TraversalCycle:
            # A cycle is not proof of exhaustion. Discard this root's partial
            # snapshot and try bounded native raw-tree search once in the SAME
            # window, deadline and node budget. Never retry a gesture or a COM
            # exception. Missing previously observed matches are not absence.
            known_matches = {item["native_id"] for item in elements[first_element:]}
            del elements[first_element:]
            seen.intersection_update(prior_seen)
            try:
                walk_root(root, search=True)
            except TraversalCycle:
                raise AxisError("OBSERVATION_UNAVAILABLE", "Native accessibility traversal cycle") from None
            if not truncated and not known_matches <= {item["native_id"] for item in elements[first_element:]}:
                raise AxisError("OBSERVATION_UNAVAILABLE", "Native accessibility search contradicted the preceding observation")
        if truncated:
            break
    return {"elements": elements, "coverage": "truncated" if truncated else "complete"}
