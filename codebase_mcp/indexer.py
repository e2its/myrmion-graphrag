"""Orquestador de indexado: recorre el árbol, parsea, resuelve y persiste en el GraphStore.

- `index()`   : indexado completo (reindexa todo; crea snapshot + cambios).
- `sync_paths()`: sincronización incremental idempotente por fichero (SIN duplicados),
  con re-resolución de llamadas cruzadas para garantizar consistencia.
"""

from __future__ import annotations

import hashlib
import pathlib

from . import history, resolver
from .models import Snapshot
from .parser import get_parser_for_path, supported_extensions

EXCLUDE_DIRS = {
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
    "site-packages", "dist", "build", ".next", ".nuxt", "target", "vendor",
    "bower_components", ".idea", ".vscode", ".cache", ".gradle", ".tox",
    ".pytest_cache", ".mypy_cache", "bin", "obj",
}


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", "replace")).hexdigest()


def discover_code_files(root) -> list:
    root = pathlib.Path(root)
    exts = supported_extensions()
    out = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
            continue
        out.append(p)
    return sorted(out)


def _read(path) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")


def index(store, root, sha="", branch="", commit_time="", created_at="") -> dict:
    root = pathlib.Path(root)
    old_nodes = store.all_nodes()

    all_nodes: list = []
    all_edges: list = []
    hashes: dict = {}
    parsed = 0
    for f in discover_code_files(root):
        parser = get_parser_for_path(f)
        if parser is None:
            continue
        rel = f.relative_to(root).as_posix()
        text = _read(f)
        res = parser.parse_source(text, rel)
        all_nodes.extend(res.nodes)
        all_edges.extend(res.edges)
        hashes[rel] = _md5(text)
        parsed += 1

    resolved = resolver.resolve_all(all_nodes, all_edges)

    store.clear()
    store.upsert_many(all_nodes, [])
    store.replace_edges(resolved)
    for rel, h in hashes.items():
        store.set_file_hash(rel, h)

    diffs = history.diff_nodes(old_nodes, all_nodes)
    snap_id = store.create_snapshot(Snapshot(
        id=0, commit_sha=sha, commit_time=commit_time, branch=branch, created_at=created_at,
        node_count=len(all_nodes), edge_count=len(resolved),
    ))
    store.record_changes(history.to_change_records(snap_id, diffs))

    return {
        "ficheros": parsed,
        "nodos": len(all_nodes),
        "aristas": len(resolved),
        "snapshot_id": snap_id,
        "sha": sha,
        "cambios": len(diffs),
    }


def sync_paths(store, root, paths, sha="", branch="", commit_time="", created_at="") -> dict:
    """Sincroniza incrementalmente los ficheros `paths` (rutas relativas a `root`).

    Por cada fichero, en efecto atómico: no-op si el hash no cambió; si no, borra sus
    nodos/aristas, re-parsea y re-resuelve TODAS las llamadas (consistencia cruzada).
    Idempotente y sin duplicados (Node.id estable).
    """
    root = pathlib.Path(root)
    diffs_all: list = []
    tocados = 0
    saltados = 0
    borrados = 0
    for path in paths:
        rel = _rel(root, path)
        abs_path = root / rel
        old_file_nodes = [n for n in store.all_nodes() if n.file == rel]

        if not abs_path.exists():
            if old_file_nodes:
                store.delete_by_file(rel)
                diffs_all.extend((n.id, "removed", "") for n in old_file_nodes)
                borrados += 1
            continue

        text = _read(abs_path)
        h = _md5(text)
        if store.get_file_hash(rel) == h and old_file_nodes:
            saltados += 1
            continue

        parser = get_parser_for_path(abs_path)
        if parser is None:
            continue

        store.delete_by_file(rel)
        res = parser.parse_source(text, rel)
        store.upsert_many(res.nodes, res.edges)
        store.set_file_hash(rel, h)
        diffs_all.extend(history.diff_nodes(old_file_nodes, res.nodes))
        tocados += 1

    # Re-resolución global: ninguna arista cruzada queda colgando.
    resolved = resolver.resolve_all(store.all_nodes(), store.all_edges())
    store.replace_edges(resolved)

    snap_id = store.create_snapshot(Snapshot(
        id=0, commit_sha=sha, commit_time=commit_time, branch=branch, created_at=created_at,
        node_count=len(store.all_nodes()), edge_count=len(resolved),
    ))
    store.record_changes(history.to_change_records(snap_id, diffs_all))

    return {
        "sincronizados": tocados,
        "sin_cambios": saltados,
        "borrados": borrados,
        "snapshot_id": snap_id,
        "cambios": len(diffs_all),
    }


def _rel(root, path) -> str:
    p = pathlib.Path(path)
    try:
        if p.is_absolute():
            return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()
    return pathlib.PurePosixPath(str(path).replace("\\", "/")).as_posix()
