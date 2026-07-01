import doc_ledger


def test_content_and_file_hash(tmp_path):
    assert doc_ledger.content_hash("a") == doc_ledger.content_hash("a")
    assert doc_ledger.content_hash("a") != doc_ledger.content_hash("b")
    f = tmp_path / "x.md"
    f.write_bytes(b"hola")
    assert doc_ledger.file_hash(f) == doc_ledger.file_hash(f)


def test_record_one_added_modified_noop():
    s = doc_ledger.load(None)
    assert doc_ledger.record_one(s, "notas/a.md", "h1") == [("Document:a.md", "added", "")]
    # identidad por basename
    assert doc_ledger.doc_hash(s, "a.md") == "h1"
    assert doc_ledger.doc_hash(s, "/otra/ruta/a.md") == "h1"
    # mismo hash -> no hay cambios
    assert doc_ledger.record_one(s, "a.md", "h1") == []
    # cambia -> modified
    d = doc_ledger.record_one(s, "a.md", "h2")
    assert d[0][0] == "Document:a.md" and d[0][1] == "modified"


def test_record_batch_history_and_summary():
    s = doc_ledger.load(None)
    doc_ledger.record_batch(s, {"a.md": "h1", "b.md": "h1"})
    diffs = doc_ledger.record_batch(s, {"a.md": "h2", "c.md": "h1"})  # a mod, b removed, c added
    changes = {nid.split(":", 1)[1]: ch for nid, ch, _ in diffs}
    assert changes == {"a.md": "modified", "b.md": "removed", "c.md": "added"}
    assert doc_ledger.summary(diffs) == {"added": 1, "modified": 1, "removed": 1}
    assert any(r.change == "modified" for r in doc_ledger.history_of(s, "a.md"))


def test_remove_one_and_absent():
    s = doc_ledger.load(None)
    assert doc_ledger.doc_hash(s, "nope.md") is None
    doc_ledger.record_one(s, "a.md", "h1")
    d = doc_ledger.remove_one(s, "a.md")
    assert d == [("Document:a.md", "removed", "")]
    assert doc_ledger.doc_hash(s, "a.md") is None


def test_persist_roundtrip(tmp_path):
    p = tmp_path / "ledger.json"
    s = doc_ledger.load(p)
    doc_ledger.record_one(s, "a.md", "h1")
    doc_ledger.save(s, p)
    s2 = doc_ledger.load(p)
    assert doc_ledger.doc_hash(s2, "a.md") == "h1"
