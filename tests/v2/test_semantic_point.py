import copy
import pytest
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.semantic_point import verify_semantic_point


POINT = {"x": 5, "y": 5, "native_id": "button", "resolved_bounds": [0, 0, 10, 10]}
ELEMENT = {"native_id": "button", "bounds": [0, 0, 10, 10], "enabled": True, "visible": True}


def test_unchanged_point_is_revalidated():
    verify_semantic_point(POINT, {"coverage": "complete", "elements": [ELEMENT]})


@pytest.mark.parametrize("patch,code", [({"bounds": [20, 20, 30, 30]}, "STALE_ELEMENT_GEOMETRY"),
    ({"native_id": "replacement"}, "STALE_REFERENCE"), ({"enabled": False}, "ELEMENT_NOT_ACTIONABLE"),
    ({"visible": False}, "ELEMENT_NOT_ACTIONABLE")])
def test_element_changes_inside_same_window_are_rejected(patch, code):
    with pytest.raises(AxisError) as failure:
        verify_semantic_point(POINT, {"coverage": "complete", "elements": [{**ELEMENT, **patch}]})
    assert failure.value.code == code


@pytest.mark.parametrize("observation", [{"coverage": "truncated", "elements": [ELEMENT]},
    {"coverage": "complete", "elements": []}, {"coverage": "complete", "elements": [ELEMENT, copy.deepcopy(ELEMENT)]}])
def test_incomplete_or_ambiguous_point_cannot_be_reused(observation):
    with pytest.raises(AxisError):
        verify_semantic_point(POINT, observation)
