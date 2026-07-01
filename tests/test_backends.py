import httpx
import respx

import backends


def test_parse_env_ignora_comentarios_y_comillas():
    env = backends.parse_env('# c\nA=1\nB="dos"\n\nC=tres # inline\n')
    assert env["A"] == "1"
    assert env["B"] == "dos"
    assert env["C"] == "tres # inline"


FS = {
    "LIGHTRAG_KV_STORAGE": "JsonKVStorage",
    "LIGHTRAG_VECTOR_STORAGE": "NanoVectorDBStorage",
    "LIGHTRAG_GRAPH_STORAGE": "NetworkXStorage",
    "LIGHTRAG_DOC_STATUS_STORAGE": "JsonDocStatusStorage",
}


def test_detect_profile():
    assert backends.detect_profile(FS) == "filesystem"
    assert backends.detect_profile({**FS, "LIGHTRAG_GRAPH_STORAGE": "Neo4JStorage"}) == "neo4j"
    pg = {k: v.replace("Json", "PG").replace("NanoVectorDB", "PGVector").replace("NetworkX", "PGGraph")
          for k, v in FS.items()}
    pg["LIGHTRAG_KV_STORAGE"] = "PGKVStorage"
    pg["LIGHTRAG_DOC_STATUS_STORAGE"] = "PGDocStatusStorage"
    assert backends.detect_profile(pg) == "postgres"
    hib = {"LIGHTRAG_KV_STORAGE": "PGKVStorage", "LIGHTRAG_VECTOR_STORAGE": "PGVectorStorage",
           "LIGHTRAG_GRAPH_STORAGE": "Neo4JStorage", "LIGHTRAG_DOC_STATUS_STORAGE": "PGDocStatusStorage"}
    assert backends.detect_profile(hib) == "hibrido"
    assert backends.detect_profile({**FS, "LIGHTRAG_VECTOR_STORAGE": "Milvus"}) == "mixed"


def test_validate_storage_config():
    assert backends.validate_storage_config(FS) == []
    errs = backends.validate_storage_config({**FS, "LIGHTRAG_GRAPH_STORAGE": "Neo4JStorage"})
    assert any("NEO4J_URI" in e for e in errs) and any("NEO4J_PASSWORD" in e for e in errs)
    ok = backends.validate_storage_config({**FS, "LIGHTRAG_GRAPH_STORAGE": "Neo4JStorage",
                                           "NEO4J_URI": "neo4j://x", "NEO4J_PASSWORD": "p"})
    assert not any(e.startswith("ERROR") for e in ok)
    assert any("RE-INDEXAR" in e for e in ok)


def test_render_env_block():
    b = backends.render_env_block("hibrido", {"NEO4J_PASSWORD": "np", "POSTGRES_PASSWORD": "pp"})
    assert "Neo4JStorage" in b and "PGVectorStorage" in b
    assert "NEO4J_PASSWORD=np" in b and "POSTGRES_PASSWORD=pp" in b
    assert backends.render_env_block("filesystem") == backends.render_env_block("filesystem")


def test_render_env_block_desconocido():
    import pytest
    with pytest.raises(ValueError):
        backends.render_env_block("noexiste")


def test_parse_health_config():
    assert backends.parse_health_config({"configuration": {"graph_storage": "Neo4JStorage"}}) == {
        "graph_storage": "Neo4JStorage"}
    assert backends.parse_health_config({"kv_storage": "JsonKVStorage"}) == {"kv_storage": "JsonKVStorage"}
    assert backends.parse_health_config("no dict") == {}
    assert backends.parse_health_config({"status": "ok"}) == {}


class _Auth(Exception):
    pass


class _ServiceUnavailable(Exception):
    pass


def test_healthcheck_clasifica(monkeypatch):
    monkeypatch.setattr(backends, "_ping_neo4j", lambda env: None)
    assert backends.healthcheck("neo4j", {})[0] is True

    def raise_auth(env):
        raise _Auth("bad")
    monkeypatch.setattr(backends, "_ping_neo4j", raise_auth)
    ok, msg = backends.healthcheck("neo4j", {})
    assert ok is False and "credenciales" in msg

    def raise_down(env):
        raise _ServiceUnavailable("down")
    monkeypatch.setattr(backends, "_ping_neo4j", raise_down)
    assert "no responde" in backends.healthcheck("neo4j", {})[1]

    def raise_import(env):
        raise ImportError("no driver")
    monkeypatch.setattr(backends, "_ping_postgres", raise_import)
    assert "requirements-backends" in backends.healthcheck("postgres", {})[1]

    assert backends.healthcheck("otro", {})[0] is False


@respx.mock
def test_check_ollama_model():
    env = {"LLM_BINDING_HOST": "http://ollama", "LLM_MODEL": "qwen2.5:7b"}
    respx.get("http://ollama/api/tags").mock(return_value=httpx.Response(200, json={
        "models": [{"name": "qwen2.5:7b"}]}))
    assert backends.check_ollama_model(env)[0] is True

    respx.get("http://ollama/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
    ok, msg = backends.check_ollama_model(env)
    assert ok is False and "ollama pull" in msg

    respx.get("http://ollama/api/tags").mock(side_effect=httpx.ConnectError("x"))
    assert "no responde" in backends.check_ollama_model(env)[1]
    assert backends.check_ollama_model({})[0] is False

    # pediste 7b pero solo hay 32b -> NO disponible (no basta la misma base)
    respx.get("http://ollama/api/tags").mock(return_value=httpx.Response(200, json={
        "models": [{"name": "qwen2.5:32b"}]}))
    ok, msg = backends.check_ollama_model(env)
    assert ok is False and "ollama pull" in msg


class _Gai(Exception):  # simula socket.gaierror por nombre de tipo
    pass


_Gai.__name__ = "gaierror"


def test_healthcheck_dns_failure(monkeypatch):
    def raise_dns(env):
        raise _Gai("name resolution failed")
    monkeypatch.setattr(backends, "_ping_postgres", raise_dns)
    ok, msg = backends.healthcheck("postgres", {})
    assert ok is False and "no responde" in msg


def test_render_model_block():
    assert "qwen2.5:7b" in backends.render_model_block("local")
    assert "qwen2.5:32b" in backends.render_model_block("profesional")
    import pytest
    with pytest.raises(ValueError):
        backends.render_model_block("otro")


def test_cli_main(monkeypatch, capsys):
    monkeypatch.setattr(backends, "_ping_neo4j", lambda env: None)
    assert backends.main(["healthcheck", "neo4j"]) == 0
    assert backends.main([]) == 2
