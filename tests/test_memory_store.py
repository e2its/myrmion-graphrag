from codebase_mcp.graph import InMemoryGraphStore
from codebase_mcp.models import Edge, Node, Snapshot


def _n(kind, qn, file="m.py"):
    return Node(kind=kind, qualified_name=qn, name=qn.split(".")[-1], file=file)


def test_upsert_idempotent():
    s = InMemoryGraphStore()
    n = _n("Function", "m.f")
    s.upsert_node(n)
    s.upsert_node(n)
    assert len(s.all_nodes()) == 1


def test_edge_dedup_and_callers_callees():
    s = InMemoryGraphStore()
    s.upsert_node(_n("Function", "m.a"))
    s.upsert_node(_n("Function", "m.b"))
    e = Edge(src="Function:m.a", kind="CALLS", dst="Function:m.b", callee_name="b")
    s.upsert_edge(e)
    s.upsert_edge(e)
    assert len(s.all_edges()) == 1
    assert s.callees("Function:m.a")[0].dst == "Function:m.b"
    assert s.callers("Function:m.b")[0].src == "Function:m.a"


def test_delete_by_file():
    s = InMemoryGraphStore()
    s.upsert_node(_n("Function", "a.f", file="a.py"))
    s.upsert_node(_n("Function", "b.g", file="b.py"))
    s.upsert_edge(Edge(src="Function:a.f", kind="CALLS", dst="Function:b.g"))
    s.delete_by_file("a.py")
    assert {n.qualified_name for n in s.all_nodes()} == {"b.g"}
    assert s.all_edges() == []


def test_clear_keeps_annotations_and_snapshots():
    s = InMemoryGraphStore()
    s.upsert_node(_n("Function", "m.f"))
    s.set_annotation("Function:m.f", "keep")
    s.create_snapshot(Snapshot(id=0, commit_sha="abc"))
    s.set_file_hash("m.py", "h")
    s.clear()
    assert s.all_nodes() == []
    assert s.get_annotations("Function:m.f")[0].label == "keep"
    assert s.latest_snapshot().commit_sha == "abc"
    assert s.get_file_hash("m.py") is None


def test_snapshots_changes_history():
    from codebase_mcp.models import ChangeRecord
    s = InMemoryGraphStore()
    sid = s.create_snapshot(Snapshot(id=0, commit_sha="c1"))
    s.record_changes([ChangeRecord(snapshot_id=sid, node_id="Function:m.f", change="added")])
    assert s.history_of("Function:m.f")[0].change == "added"
    sid2 = s.create_snapshot(Snapshot(id=0, commit_sha="c2"))
    s.record_changes([ChangeRecord(snapshot_id=sid2, node_id="Function:m.f", change="modified")])
    assert len(s.diff(sid, sid2)) == 1


def test_search_and_find():
    s = InMemoryGraphStore()
    s.upsert_node(_n("Function", "m.helper"))
    s.upsert_node(_n("Class", "m.Widget"))
    assert {n.name for n in s.search("help")} == {"helper"}
    assert s.find_nodes(kind="Class")[0].name == "Widget"
    assert s.find_nodes(qualified="m.helper")[0].name == "helper"


def test_load_json_replaces_not_accumulates(tmp_path):
    src = InMemoryGraphStore()
    src.upsert_node(_n("Function", "m.nuevo"))
    p = tmp_path / "g.json"
    src.save_json(p)
    dst = InMemoryGraphStore()
    dst.upsert_node(_n("Function", "m.viejo"))  # store ya poblado
    dst.load_json(p)                            # debe REEMPLAZAR, no acumular
    assert {n.qualified_name for n in dst.all_nodes()} == {"m.nuevo"}


def test_create_snapshot_id_survives_gaps():
    from codebase_mcp.models import Snapshot
    s = InMemoryGraphStore()
    s._snapshots = [Snapshot(id=1), Snapshot(id=5)]  # ids con hueco
    assert s.create_snapshot(Snapshot(id=0)) == 6    # max+1, no len+1


def test_save_load_json(tmp_path):
    s = InMemoryGraphStore()
    s.upsert_node(_n("Function", "m.f"))
    s.upsert_edge(Edge(src="Function:m.f", kind="CALLS", callee_name="g"))
    s.set_annotation("Function:m.f", "reusable")
    s.set_file_hash("m.py", "h1")
    p = tmp_path / "snap.json"
    s.save_json(p)
    s2 = InMemoryGraphStore()
    s2.load_json(p)
    assert {n.qualified_name for n in s2.all_nodes()} == {"m.f"}
    assert s2.get_annotations("Function:m.f")[0].label == "reusable"
    assert s2.get_file_hash("m.py") == "h1"
    InMemoryGraphStore().load_json(tmp_path / "noexiste.json")  # no revienta
