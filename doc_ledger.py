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


def diff_batch(store, docs: dict) -> list:
    """Calcula los cambios (added/modified/removed) del conjunto {ruta: hash} contra el
    estado previo, SIN mutar el store. El llamador aplica a LightRAG y luego commitea SOLO
    lo aplicado con éxito (evita que el ledger se adelante a LightRAG)."""
    old = store.all_nodes()
    new = [_doc_node(p, h) for p, h in docs.items()]
    return history.diff_nodes(old, new)


def commit(store, docs: dict, applied: list, sha="", branch="") -> list:
    """Persiste en el ledger SOLO los cambios `applied` (ya aplicados a LightRAG) y crea un
    snapshot. Lo no aplicado no avanza -> se reintenta en la próxima sincronización."""
    name_hash = {_name(p): h for p, h in docs.items()}
    for nid, change, _detail in applied:
        name = nid.split(":", 1)[1]
        if change in ("added", "modified"):
            store.upsert_node(_doc_node(name, name_hash.get(name, "")))
        elif change == "removed":
            store.delete_by_file(name)
    _snapshot(store, applied, sha, branch)
    return applied


def record_batch(store, docs: dict, sha="", branch="") -> list:
    """Conveniencia: diffea y COMMITEA todos los cambios de golpe (sin garantía de que se
    aplicaron a un sistema externo). Para versionado seguro usa diff_batch + aplicar + commit."""
    diffs = diff_batch(store, docs)
    return commit(store, docs, diffs, sha, branch)


def history_of(store, path) -> list:
    return store.history_of(f"Document:{_name(path)}")


def summary(diffs) -> dict:
    out = {"added": 0, "modified": 0, "removed": 0}
    for _nid, change, _detail in diffs:
        out[change] = out.get(change, 0) + 1
    return out
