#!/usr/bin/env python3
"""
Ledger de VERSIONADO de documentos para el servidor myrmion-graphrag.

LightRAG solo guarda la versión ACTUAL de cada documento y deduplica por nombre de fichero
(archiva los duplicados en vez de actualizar). Este ledger, por encima de LightRAG, aporta:
  - detección de cambios por HASH de contenido (no por nombre) -> nunca se pierde un update
    ni se reindexa en balde;
  - histórico (added/modified/removed) por snapshot, etiquetado con el commit git.

Reutiliza la MISMA maquinaria que el inventario de código (`codebase_mcp`): cada documento
es un `Node(kind="Document")` cuyo `body_hash` es el hash de su contenido, y se versiona con
`history.diff_nodes` + snapshots. La identidad es el basename (igual que la dedup de LightRAG).
"""

from __future__ import annotations

import hashlib
import pathlib

from codebase_mcp import history
from codebase_mcp.graph import InMemoryGraphStore
from codebase_mcp.models import Node, Snapshot


def content_hash(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8", "replace")).hexdigest()


def file_hash(path) -> str:
    """Hash de los BYTES del fichero (robusto para binarios: pdf/docx/pptx)."""
    return hashlib.md5(pathlib.Path(path).read_bytes()).hexdigest()


def _name(path) -> str:
    return pathlib.Path(str(path)).name


def _doc_node(path, chash: str) -> Node:
    name = _name(path)
    # identidad por basename (coincide con la deduplicación de LightRAG)
    return Node(kind="Document", qualified_name=name, name=name, file=name,
                body_hash=chash, lang="doc")


def load(path) -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    if path:
        store.load_json(path)
    return store


def save(store, path) -> None:
    if path and hasattr(store, "save_json"):
        try:
            store.save_json(path)
        except OSError:
            pass


def doc_hash(store, path):
    """Hash registrado del documento (por basename), o None si no está en el ledger."""
    n = store.get_node(f"Document:{_name(path)}")
    return n.body_hash if n else None


def _snapshot(store, diffs, sha, branch):
    sid = store.create_snapshot(Snapshot(
        id=0, commit_sha=sha, branch=branch,
        node_count=len(store.all_nodes()), edge_count=0))
    store.record_changes(history.to_change_records(sid, diffs))
    return sid


def record_one(store, path, chash: str, sha="", branch="") -> list:
    """Registra un documento (added/modified) y devuelve los cambios detectados."""
    name = _name(path)
    old = [n for n in store.all_nodes() if n.file == name]
    new = [_doc_node(path, chash)]
    diffs = history.diff_nodes(old, new)
    store.delete_by_file(name)
    store.upsert_node(new[0])
    _snapshot(store, diffs, sha, branch)
    return diffs


def remove_one(store, path, sha="", branch="") -> list:
    """Registra el borrado de un documento."""
    name = _name(path)
    old = [n for n in store.all_nodes() if n.file == name]
    if not old:
        return []
    diffs = history.diff_nodes(old, [])
    store.delete_by_file(name)
    _snapshot(store, diffs, sha, branch)
    return diffs


def record_batch(store, docs: dict, sha="", branch="") -> list:
    """Diffea TODO el conjunto de documentos (dict {ruta: hash}) contra el estado previo.

    Devuelve la lista de (node_id, cambio, detalle). No toca LightRAG: el llamador aplica los
    cambios (upsert/delete) sobre el motor RAG.
    """
    old = store.all_nodes()
    new = [_doc_node(p, h) for p, h in docs.items()]
    diffs = history.diff_nodes(old, new)
    store.clear()  # conserva snapshots/anotaciones
    for n in new:
        store.upsert_node(n)
    _snapshot(store, diffs, sha, branch)
    return diffs


def history_of(store, path) -> list:
    return store.history_of(f"Document:{_name(path)}")


def summary(diffs) -> dict:
    out = {"added": 0, "modified": 0, "removed": 0}
    for _nid, change, _detail in diffs:
        out[change] = out.get(change, 0) + 1
    return out
