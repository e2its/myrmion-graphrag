import json
import pathlib

import pytest

import codebase_server

MINI = pathlib.Path(__file__).parent / "fixtures" / "mini_codebase"


@pytest.fixture
def server_env(tmp_path, monkeypatch):
    root = tmp_path / "code"
    root.mkdir()
    for name in ("util.py", "svc.py", "app.py", "orphan.py"):
        (root / name).write_text((MINI / name).read_text())
    monkeypatch.setenv("CODEBASE_STORAGE", "memory")
    monkeypatch.setenv("CODEBASE_ROOT", str(root))
    monkeypatch.setenv("CODEBASE_MEMORY_SNAPSHOT", str(tmp_path / "snap.json"))
    return root


def test_index_and_queries(server_env):
    res = json.loads(codebase_server.indexar_codebase())
    assert res["ficheros"] == 4 and res["nodos"] > 0

    callers = json.loads(codebase_server.quien_llama_a("helper", profundidad=3))
    assert any(c["qualified_name"] == "app.main" for c in callers)

    afecta = json.loads(codebase_server.a_que_afecta("run", profundidad=5))
    assert any(c["qualified_name"] == "app.main" for c in afecta)

    deps = json.loads(codebase_server.dependencias_de("main", profundidad=2))
    assert any("run" in d["qualified_name"] for d in deps)

    inv = json.loads(codebase_server.inventario("dead"))
    assert any(it["qualified_name"].endswith("nunca_llamada") for it in inv)

    muerto = json.loads(codebase_server.codigo_muerto())
    assert len(muerto) >= 1

    arch = json.loads(codebase_server.arquitectura())
    assert arch["modulos"] == 4


def test_annotate_and_history(server_env):
    codebase_server.indexar_codebase()
    msg = codebase_server.anotar_simbolo("orphan.nunca_llamada", "keep")
    assert "fijada" in msg
    inv = json.loads(codebase_server.inventario())
    orphan = next(it for it in inv if it["qualified_name"].endswith("nunca_llamada"))
    assert orphan["dead"] is False  # keep anula dead y persiste vía snapshot

    hist = json.loads(codebase_server.historico("app.main"))
    assert isinstance(hist, list)

    estado = json.loads(codebase_server.estado_indexado())
    assert "ultimo_snapshot" in estado


def test_symbol_not_found_and_ambiguous(server_env):
    codebase_server.indexar_codebase()
    assert "No encontré" in codebase_server.quien_llama_a("noexiste")


def test_sincronizar_y_cambios(server_env):
    codebase_server.indexar_codebase()
    (server_env / "util.py").write_text("def helper():\n    return 99\n\ndef extra():\n    return 0\n")
    res = json.loads(codebase_server.sincronizar_codigo(["util.py"]))
    assert res["destino"] == "overlay"
    inv = json.loads(codebase_server.inventario())
    assert any(it["qualified_name"] == "util.extra" for it in inv)

    # cambios_desde sin repo git -> ficheros vacíos, no revienta
    cambios = json.loads(codebase_server.cambios_desde("HEAD"))
    assert "ficheros" in cambios
