from codebase_mcp import history
from codebase_mcp.models import Node


def _n(qn, body="h1", file="m.py"):
    return Node(kind="Function", qualified_name=qn, name=qn.split(".")[-1], file=file, body_hash=body)


def test_diff_nodes_added_removed_modified_moved():
    old = [_n("m.a"), _n("m.b"), _n("m.c")]
    new = [_n("m.a"), _n("m.b", body="h2"), _n("m.d"), _n("m.c", file="otro.py")]
    diffs = dict((nid, (change, detail)) for nid, change, detail in history.diff_nodes(old, new))
    assert diffs["Function:m.d"][0] == "added"
    assert diffs["Function:m.c"] == ("modified", "movida")
    assert diffs["Function:m.b"][0] == "modified"
    assert diffs["Function:m.a"] if "Function:m.a" in diffs else True  # sin cambios -> ausente
    assert "Function:m.a" not in diffs


def test_removed():
    diffs = history.diff_nodes([_n("m.a")], [])
    assert diffs == [("Function:m.a", "removed", "")]


def test_to_change_records():
    recs = history.to_change_records(7, [("Function:m.a", "added", "")])
    assert recs[0].snapshot_id == 7 and recs[0].change == "added"
