from codebase_mcp import indexer, sync
from codebase_mcp.graph import InMemoryGraphStore


def test_sync_add_edit_delete_no_duplicates(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    store = InMemoryGraphStore()
    (root / "m.py").write_text("def vieja():\n    return 1\n")
    indexer.sync_paths(store, root, ["m.py"])
    assert {n.qualified_name for n in store.all_nodes() if n.kind == "Function"} == {"m.vieja"}

    # editar: el símbolo viejo desaparece, aparece el nuevo (sin duplicados)
    (root / "m.py").write_text("def nueva():\n    return 2\n")
    res = indexer.sync_paths(store, root, ["m.py"])
    funcs = {n.qualified_name for n in store.all_nodes() if n.kind == "Function"}
    assert funcs == {"m.nueva"}
    assert res["sincronizados"] == 1

    # no-op si el contenido no cambia
    res2 = indexer.sync_paths(store, root, ["m.py"])
    assert res2["sin_cambios"] == 1 and res2["sincronizados"] == 0

    # borrar el fichero -> se eliminan sus nodos
    (root / "m.py").unlink()
    res3 = indexer.sync_paths(store, root, ["m.py"])
    assert res3["borrados"] == 1
    assert not any(n.kind == "Function" for n in store.all_nodes())


def test_sync_reresolves_cross_file(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    (root / "util.py").write_text("def helper():\n    return 1\n")
    (root / "app.py").write_text("from util import helper\ndef main():\n    return helper()\n")
    store = InMemoryGraphStore()
    indexer.index(store, root)
    from codebase_mcp import queries
    callers = queries.callers_transitive(store, "Function:util.helper", depth=2)
    assert any(c["qualified_name"] == "app.main" for c in callers)


def test_sync_run_and_main(tmp_path, monkeypatch, capsys):
    root = tmp_path / "code"
    root.mkdir()
    (root / "m.py").write_text("def f():\n    return 1\n")
    store = InMemoryGraphStore()
    res = sync.run(["m.py"], durable=True, root=root, store=store)
    assert res["destino"] == "durable"

    monkeypatch.setenv("CODEBASE_STORAGE", "filesystem")
    monkeypatch.setenv("CODEBASE_ROOT", str(root))
    monkeypatch.setenv("CODEBASE_SNAPSHOT", str(tmp_path / "snap.json"))
    assert sync.main(["--durable", "m.py"]) == 0
    assert sync.main([]) == 2
