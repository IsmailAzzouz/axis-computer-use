import pytest
from cu_suite.v2.contracts import AxisError
from cu_suite.v2.platforms.window_ownership import owned_handles


def window(target_id, handle, pid=10, owner=None):
    return {"target_id": target_id, "identity": target_id+":birth", "handle": handle,
            "pid": pid, "owner_target_id": owner}


def test_cross_process_picker_is_owned_but_same_process_sibling_is_not():
    root = window("main", 1)
    windows = [root, window("picker", 2, pid=20, owner="main"),
               window("popup", 3, pid=21, owner="picker"), window("unrelated", 4)]
    assert owned_handles(root, windows) == {1, 2, 3}


def test_old_owner_identity_and_unrelated_cycles_do_not_grant_authority():
    root = window("main", 1)
    windows = [root, window("old-dialog", 2, owner="old-main"),
               window("cycle-a", 3, owner="cycle-b"), window("cycle-b", 4, owner="cycle-a")]
    assert owned_handles(root, windows) == {1}


@pytest.mark.parametrize("windows", [[], [window("replacement", 1)], [{**window("main", 1), "identity": "reused"}]])
def test_replaced_owner_never_inherits_held_target(windows):
    with pytest.raises(AxisError, match="identity"):
        owned_handles(window("main", 1), windows)


def test_ownership_depth_is_bounded():
    root = window("main", 1)
    windows = [root]+[window(str(i), i+2, owner="main" if i == 0 else str(i-1)) for i in range(100)]
    assert owned_handles(root, windows) == set(range(1, 10))
