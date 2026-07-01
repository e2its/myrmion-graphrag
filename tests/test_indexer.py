from codebase_mcp import indexer
from codebase_mcp.graph import InMemoryGraphStore


def test_index_summary_and_snapshot(indexed_store):
    store, root = indexed_store
    assert any(n.qualified_name == "svc.Service.run" for n in store.all_nodes())
    snap = store.latest_snapshot()
    assert snap is not None and snap.node_count > 0


def test_discover_excludes(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.py").write_text("def g():\n    return 1\n")
    files = indexer.discover_code_files(tmp_path)
    assert {p.name for p in files} == {"a.py"}


def test_index_full_reindex_no_duplicates(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    (root / "m.py").write_text("def f():\n    return 1\n")
    store = InMemoryGraphStore()
    r1 = indexer.index(store, root)
    n1 = len(store.all_nodes())
    r2 = indexer.index(store, root)
    assert len(store.all_nodes()) == n1  # sin duplicados
    assert r1["ficheros"] == r2["ficheros"] == 1
