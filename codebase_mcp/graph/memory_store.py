"""InMemoryGraphStore: almacén del grafo de código en memoria (dict/set puro, SIN SQLite).

Usos: (a) doble de tests hermético, (b) overlay efímero de sesión, (c) modo local sin BD
(`memory`) con snapshot JSON opcional. Las anotaciones y snapshots viven en estructuras
separadas del set de nodos/aristas, por eso `clear()` (reindexado) no los borra.
"""

from __future__ import annotations

import json
import pathlib

from ..models import Annotation, ChangeRecord, Edge, Node, Snapshot
from .store import GraphStore


class InMemoryGraphStore(GraphStore):
    def __init__(self):
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple, Edge] = {}
        # anotaciones: node_id -> {label: note} (persisten a clear())
        self._annotations: dict[str, dict[str, str]] = {}
        self._snapshots: list[Snapshot] = []
        self._changes: list[ChangeRecord] = []
        self._file_hashes: dict[str, str] = {}

    # --- escritura ---------------------------------------------------------
    def upsert_node(self, node: Node) -> None:
        self._nodes[node.id] = node

    def upsert_edge(self, edge: Edge) -> None:
        self._edges[edge.key] = edge

    def delete_by_file(self, file: str) -> None:
        borrados = {nid for nid, n in self._nodes.items() if n.file == file}
        for nid in borrados:
            del self._nodes[nid]
        self._edges = {
            k: e for k, e in self._edges.items() if e.src not in borrados
        }

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._file_hashes.clear()
        # anotaciones y snapshots se conservan a propósito

    def replace_edges(self, edges) -> None:
        self._edges = {e.key: e for e in edges}

    # --- lectura -----------------------------------------------------------
    def get_node(self, node_id: str):
        return self._nodes.get(node_id)

    def all_nodes(self) -> list:
        return list(self._nodes.values())

    def all_edges(self) -> list:
        return list(self._edges.values())

    def find_nodes(self, name=None, kind=None, qualified=None) -> list:
        out = []
        for n in self._nodes.values():
            if name is not None and n.name != name:
                continue
            if kind is not None and n.kind != kind:
                continue
            if qualified is not None and n.qualified_name != qualified:
                continue
            out.append(n)
        return out

    def callers(self, node_id: str) -> list:
        return [e for e in self._edges.values() if e.kind == "CALLS" and e.dst == node_id]

    def callees(self, node_id: str) -> list:
        return [e for e in self._edges.values() if e.kind == "CALLS" and e.src == node_id]

    def search(self, texto: str) -> list:
        t = (texto or "").lower()
        return [
            n for n in self._nodes.values()
            if t in n.name.lower() or t in n.qualified_name.lower()
        ]

    # --- anotaciones -------------------------------------------------------
    def set_annotation(self, node_id: str, label: str, note: str = "") -> None:
        self._annotations.setdefault(node_id, {})[label] = note

    def get_annotations(self, node_id: str | None = None) -> list:
        out = []
        items = (
            [(node_id, self._annotations.get(node_id, {}))]
            if node_id is not None
            else self._annotations.items()
        )
        for nid, labels in items:
            for label, note in labels.items():
                out.append(Annotation(node_id=nid, label=label, note=note))
        return out

    # --- historia ----------------------------------------------------------
    def create_snapshot(self, snap: Snapshot) -> int:
        new_id = snap.id or (len(self._snapshots) + 1)
        stored = Snapshot(
            id=new_id,
            commit_sha=snap.commit_sha,
            commit_time=snap.commit_time,
            branch=snap.branch,
            created_at=snap.created_at,
            node_count=snap.node_count,
            edge_count=snap.edge_count,
        )
        self._snapshots.append(stored)
        return new_id

    def record_changes(self, changes) -> None:
        self._changes.extend(changes)

    def latest_snapshot(self):
        return self._snapshots[-1] if self._snapshots else None

    def history_of(self, node_id: str) -> list:
        return [c for c in self._changes if c.node_id == node_id]

    def diff(self, snap_a: int, snap_b: int) -> list:
        lo, hi = min(snap_a, snap_b), max(snap_a, snap_b)
        return [c for c in self._changes if lo < c.snapshot_id <= hi]

    # --- hashes por fichero ------------------------------------------------
    def get_file_hash(self, file: str):
        return self._file_hashes.get(file)

    def set_file_hash(self, file: str, digest: str) -> None:
        self._file_hashes[file] = digest

    # --- persistencia opcional (modo local `memory`) -----------------------
    def save_json(self, path) -> None:
        data = {
            "nodes": [n.__dict__ for n in self._nodes.values()],
            "edges": [e.__dict__ for e in self._edges.values()],
            "annotations": self._annotations,
            "file_hashes": self._file_hashes,
            "snapshots": [s.__dict__ for s in self._snapshots],
            "changes": [c.__dict__ for c in self._changes],
        }
        pathlib.Path(path).write_text(json.dumps(data), encoding="utf-8")

    def load_json(self, path) -> None:
        p = pathlib.Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        for nd in data.get("nodes", []):
            self.upsert_node(Node(**nd))
        for ed in data.get("edges", []):
            self.upsert_edge(Edge(**ed))
        self._annotations = {k: dict(v) for k, v in data.get("annotations", {}).items()}
        self._file_hashes = dict(data.get("file_hashes", {}))
        # snapshots y changes tambien se persisten -> el historico sobrevive a reload.
        self._snapshots = [Snapshot(**s) for s in data.get("snapshots", [])]
        self._changes = [ChangeRecord(**c) for c in data.get("changes", [])]
