import httpx
import respx

import ingest


def test_descubrir_ficheros_excluye_y_filtra(tmp_path):
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("x")
    (tmp_path / "ignore.png").write_text("x")  # extensión no soportada
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.md").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "d.md").write_text("x")

    ficheros, omitidos = ingest.descubrir_ficheros(tmp_path, excluir=True)
    nombres = {p.name for p in ficheros}
    assert nombres == {"a.md", "b.txt"}
    assert omitidos == 2

    todos, om0 = ingest.descubrir_ficheros(tmp_path, excluir=False)
    assert om0 == 0 and len(todos) == 4


def test_fmt_size():
    assert ingest.fmt_size(500) == "500B"
    assert ingest.fmt_size(1536) == "1.5KB"
    assert ingest.fmt_size(5 * 1024 * 1024) == "5.0MB"


def test_fmt_dur():
    assert ingest.fmt_dur(30) == "30s"
    assert ingest.fmt_dur(90) == "1m30s"
    assert ingest.fmt_dur(3661).startswith("1h")


def test_render_estado():
    out = ingest.render_estado({"PENDING": 2, "PROCESSED": 5}, False)
    assert "pendientes=2" in out and "indexados=5" in out and "inactivo" in out
    assert ingest.render_estado(None, None) == "(el servidor no expone estado de indexado)"


@respx.mock
def test_status_counts_y_pipeline_busy():
    base = "http://test"
    respx.get(f"{base}/documents").mock(return_value=httpx.Response(200, json={
        "statuses": {"pending": [1, 2], "processed": [1]}}))
    respx.get(f"{base}/documents/pipeline_status").mock(return_value=httpx.Response(200, json={"busy": True}))
    with httpx.Client() as c:
        counts = ingest.status_counts(c, base, {})
        assert counts == {"PENDING": 2, "PROCESSED": 1}
        assert ingest.pipeline_busy(c, base, {}) is True


@respx.mock
def test_get_json_traga_errores():
    base = "http://test"
    respx.get(f"{base}/documents").mock(return_value=httpx.Response(500, text="boom"))
    with httpx.Client() as c:
        assert ingest.status_counts(c, base, {}) is None
        assert ingest.pipeline_busy(c, base, {}) is None
