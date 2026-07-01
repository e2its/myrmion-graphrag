import httpx
import pytest
import respx

import mcp_server
from mcp_server import LightRAGClient, content_md5

BASE = "http://test"


def client(**kw):
    return LightRAGClient(base_url=BASE, **kw)


@respx.mock
def test_query_response_key():
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={"response": "RESP"}))
    assert client().query("q") == "RESP"


@respx.mock
@pytest.mark.parametrize("key", ["data", "context", "result"])
def test_query_alt_keys(key):
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={key: "X"}))
    assert client().query("q") == "X"


@respx.mock
def test_query_dict_without_known_keys():
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={"otro": 1}))
    assert "otro" in client().query("q")


@respx.mock
def test_query_non_dict_json():
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json=["a", "b"]))
    assert "a" in client().query("q")


@respx.mock
def test_query_connect_error():
    respx.post(f"{BASE}/query").mock(side_effect=httpx.ConnectError("x"))
    assert "No pude conectar" in client().query("q")


@respx.mock
def test_query_timeout():
    respx.post(f"{BASE}/query").mock(side_effect=httpx.TimeoutException("x"))
    assert "timeout" in client().query("q")


@respx.mock
def test_query_http_500_truncated():
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(500, text="E" * 999))
    out = client().query("q")
    assert "HTTP 500" in out and len(out) < 600


@respx.mock
def test_query_invalid_mode_falls_back_to_default():
    route = respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={"response": "ok"}))
    client(default_mode="local").query("q", modo="bogus")
    import json
    body = json.loads(route.calls.last.request.content)
    assert body["mode"] == "local"


@respx.mock
def test_api_key_header_present_and_absent():
    route = respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={"response": "ok"}))
    client(api_key="secret").query("q")
    assert route.calls.last.request.headers.get("x-api-key") == "secret"
    client().query("q")
    assert route.calls.last.request.headers.get("x-api-key") is None


@respx.mock
def test_add_text_ok_and_error_and_connect():
    r = respx.post(f"{BASE}/documents/text")
    r.mock(return_value=httpx.Response(200, json={}))
    assert "aceptado" in client().add_text("hola", "desc")
    r.mock(return_value=httpx.Response(500, text="boom"))
    assert "HTTP 500" in client().add_text("hola")
    r.mock(side_effect=httpx.ConnectError("x"))
    assert "No pude conectar" in client().add_text("hola")


@respx.mock
def test_health_ok_with_backend_and_errors():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(
        200, json={"status": "ok", "configuration": {"graph_storage": "Neo4JStorage"}}))
    out = client().health()
    assert "OK" in out and "graph_storage=Neo4JStorage" in out

    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("x"))
    assert "SIN CONEXION" in client().health()

    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(503, text="down"))
    assert "HTTP 503" in client().health()


@respx.mock
def test_sincronizar_documento_delete_then_insert():
    respx.get(f"{BASE}/documents").mock(return_value=httpx.Response(200, json={
        "statuses": {"processed": [{"id": "doc-1", "file_path": "notas.md"}]}}))
    dele = respx.post(f"{BASE}/documents/delete_document").mock(return_value=httpx.Response(200, json={}))
    ins = respx.post(f"{BASE}/documents/text").mock(return_value=httpx.Response(200, json={}))
    out = client().upsert_document("notas.md", "nuevo contenido")
    assert "reemplazado" in out
    assert dele.called and ins.called


@respx.mock
def test_sincronizar_documento_timeout():
    respx.get(f"{BASE}/documents").mock(return_value=httpx.Response(200, json={"statuses": {}}))
    respx.post(f"{BASE}/documents/text").mock(side_effect=httpx.TimeoutException("x"))
    assert "timeout" in client().upsert_document("n.md", "x")


@respx.mock
def test_sincronizar_documento_insert_when_absent():
    respx.get(f"{BASE}/documents").mock(return_value=httpx.Response(200, json={"statuses": {}}))
    respx.post(f"{BASE}/documents/text").mock(return_value=httpx.Response(200, json={}))
    out = client().upsert_document("nuevo.md", "x")
    assert "insertado" in out


@respx.mock
def test_tool_wrappers(monkeypatch, tmp_path):
    monkeypatch.setenv("LIGHTRAG_BASE_URL", BASE)
    monkeypatch.setenv("LIGHTRAG_API_KEY", "")
    respx.post(f"{BASE}/query").mock(return_value=httpx.Response(200, json={"response": "R"}))
    respx.post(f"{BASE}/documents/text").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.get(f"{BASE}/documents").mock(return_value=httpx.Response(200, json={"statuses": {}}))
    assert mcp_server.buscar_conocimiento("q") == "R"
    assert "aceptado" in mcp_server.anadir_documento("t")
    assert "OK" in mcp_server.estado_rag()
    f = tmp_path / "n.md"
    f.write_text("contenido")
    assert "sin duplicar" in mcp_server.sincronizar_documento(str(f))


def test_content_md5_stable():
    assert content_md5("abc") == content_md5("abc")
    assert content_md5("abc") != content_md5("abd")


def test_consistency_tools_error_paths(monkeypatch):
    import sys
    import types

    # build_supervisor lanza -> "no disponible"
    fake = types.ModuleType("consistency_readers")
    fake.build_supervisor = lambda: (_ for _ in ()).throw(RuntimeError("sin backend"))
    monkeypatch.setitem(sys.modules, "consistency_readers", fake)
    assert "no disponible" in mcp_server.verificar_alineacion()
    assert "no disponible" in mcp_server.reconciliar(aplicar=True)

    # módulo sin build_supervisor -> "No pude preparar"
    vacio = types.ModuleType("consistency_readers")
    monkeypatch.setitem(sys.modules, "consistency_readers", vacio)
    assert "No pude preparar" in mcp_server.verificar_alineacion()
    assert "No pude preparar" in mcp_server.reconciliar()
