from codebase_mcp import inventory


def _by_name(items, name):
    return next(it for it in items if it["qualified_name"].endswith("." + name) or it["qualified_name"] == name)


def test_inventory_labels(py_graph):
    items = inventory.build(py_graph)
    helper = _by_name(items, "helper")
    assert helper["reusable"] is True   # llamado desde util y svc (2 módulos)
    assert helper["mandatory"] is True  # alcanzable desde main
    assert helper["dead"] is False

    run = _by_name(items, "run")
    assert run["reusable"] and run["mandatory"]

    orphan = _by_name(items, "nunca_llamada")
    assert orphan["dead"] is True


def test_keep_annotation_prevents_dead(py_graph):
    nid = "Function:orphan.nunca_llamada"
    py_graph.set_annotation(nid, "keep")
    orphan = _by_name(inventory.build(py_graph), "nunca_llamada")
    assert orphan["dead"] is False and "keep" not in orphan["labels"]


def test_mandatory_annotation(py_graph):
    py_graph.set_annotation("Function:orphan.nunca_llamada", "mandatory")
    orphan = _by_name(inventory.build(py_graph), "nunca_llamada")
    assert orphan["mandatory"] is True


def test_dead_code_and_architecture(py_graph):
    dead = inventory.dead_code(py_graph)
    assert any(it["qualified_name"].endswith("nunca_llamada") for it in dead)
    arch = inventory.architecture_overview(py_graph)
    assert arch["modulos"] == 4
    assert "python" in arch["lenguajes"]
    assert arch["muertos"] >= 1
    assert len(arch["hotspots"]) >= 1
