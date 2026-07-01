"""Almacenamiento pluggable del grafo de código (sin SQLite).

Backends: InMemoryGraphStore (por defecto para tests, overlay y modo local),
Neo4jGraphStore y PostgresGraphStore (profesionales, import perezoso).
"""

from .memory_store import InMemoryGraphStore
from .store import GraphStore

__all__ = ["GraphStore", "InMemoryGraphStore"]
