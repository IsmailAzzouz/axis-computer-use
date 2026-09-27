"""Portable probe checks; no native actions or qualification claims."""
from types import SimpleNamespace as NS

from .native_uia_walk_probe import walk


class Node:
    def __init__(self, name, *children):
        self.CurrentName, self.CurrentControlType = name, 1
        self.children, self.parent = list(children), None
        for child in children:
            child.parent = self
    def GetRuntimeId(self):
        return (id(self),)


def provider():
    def sibling(node):
        if node.parent is None:
            return None
        siblings = node.parent.children
        i = siblings.index(node)+1
        return siblings[i] if i < len(siblings) else None
    walker = NS(GetFirstChildElement=lambda node: next(iter(node.children), None),
                GetNextSiblingElement=sibling, GetParentElement=lambda node: node.parent)
    return NS(RawViewWalker=walker, CompareElements=lambda a, b: a is b), walker


def test_finite_walk_records_only_known_test_labels():
    root = Node("private", Node("Starter"), Node("Team"), Node("Business"), Node("not-retained"))
    uia, walker = provider()
    result = walk(uia, walker, root)
    assert result["complete"] is True and result["visited"] == 5
    assert [x["name"] for x in result["matches"]] == ["Starter", "Team", "Business"]
    assert "private" not in str(result) and "not-retained" not in str(result)


def test_sibling_cycle_is_not_finite_exhaustion():
    root = Node("root", Node("Starter"), Node("Team"))
    uia, walker = provider()
    walker.GetNextSiblingElement = lambda node: root.children[1] if node is root.children[0] else root.children[0]
    result = walk(uia, walker, root)
    assert result["complete"] is False and result["error"] == "sibling_cycle"


def test_scope_escape_is_rejected_before_name_read():
    root, foreign = Node("root"), Node("private")
    uia, walker = provider()
    walker.GetFirstChildElement = lambda _: foreign
    result = walk(uia, walker, root)
    assert not result["complete"] and result["error"] == "scope_escape"
    assert not result["matches"]


def test_budget_and_ancestor_cycle_do_not_look_like_completion():
    root = Node("root", Node("Starter"))
    uia, walker = provider()
    assert walk(uia, walker, root, limit=1)["error"] == "budget_exhausted"
    walker.GetFirstChildElement = lambda node: node
    result = walk(uia, walker, root)
    assert not result["complete"] and result["error"] == "ancestor_cycle"


def test_native_exception_text_is_not_reported():
    class COMError(Exception):
        hresult = -2147220991
    root = Node("root")
    uia, walker = provider()
    def fail(_):
        raise COMError("private contents")
    walker.GetFirstChildElement = fail
    result = walk(uia, walker, root)
    assert not result["complete"]
    assert result["error"] == {"type": "COMError", "hresult": "0x80040201"}
    assert "private contents" not in str(result)
