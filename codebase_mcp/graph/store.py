"""Interfaz `GraphStore`: contrato común a todos los backends del grafo de código.

`queries.py`, `inventory.py`, `history.py` e `indexer.py` trabajan SOLO contra esta
interfaz, así que son idénticos para InMemory / Neo4j / Postgres y se testean contra el
store en memoria.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Annotation, ChangeRecord, Edge, Node, Snapshot


class GraphStore(ABC):
    # --- escritura (idempotente) ---
    @abstractmethod
    def upsert_node(self, node: Node) -> None: ...

    @abstractmethod
    def upsert_edge(self, edge: Edge) -> None: ...

    def upsert_many(self, nodes, edges) -> None:
        for n in nodes:
            self.upsert_node(n)
        for e in edges:
            self.upsert_edge(e)

    @abstractmethod
    def delete_by_file(self, file: str) -> None: ...

    @abstractmethod
    def clear(self) -> None:
        """Vacía nodos y aristas. NO borra anotaciones ni snapshots (sobreviven reindexado)."""

    @abstractmethod
    def replace_edges(self, edges) -> None:
        """Reemplaza TODAS las aristas (usado tras re-resolver llamadas)."""

    # --- lectura de grafo ---
    @abstractmethod
    def get_node(self, node_id: str): ...

    @abstractmethod
    def all_nodes(self) -> list: ...

    @abstractmethod
    def all_edges(self) -> list: ...

    @abstractmethod
    def find_nodes(self, name=None, kind=None, qualified=None) -> list: ...

    @abstractmethod
    def callers(self, node_id: str) -> list:
        """Aristas CALLS entrantes (quién llama a node_id)."""

    @abstractmethod
    def callees(self, node_id: str) -> list:
        """Aristas CALLS salientes (a qué llama node_id)."""

    @abstractmethod
    def search(self, texto: str) -> list: ...

    # --- inventario / anotaciones ---
    @abstractmethod
    def set_annotation(self, node_id: str, label: str, note: str = "") -> None: ...

    @abstractmethod
    def get_annotations(self, node_id: str | None = None) -> list: ...

    # --- historia ---
    @abstractmethod
    def create_snapshot(self, snap: Snapshot) -> int: ...

    @abstractmethod
    def record_changes(self, changes) -> None: ...

    @abstractmethod
    def latest_snapshot(self): ...

    @abstractmethod
    def history_of(self, node_id: str) -> list: ...

    # --- hashes por fichero (no-op en sync si no cambió) ---
    @abstractmethod
    def get_file_hash(self, file: str): ...

    @abstractmethod
    def set_file_hash(self, file: str, digest: str) -> None: ...
