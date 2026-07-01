"""Configuración del servidor de codebase, por variables de entorno con fallbacks."""

from __future__ import annotations

import os


def _get(name, default=""):
    return os.environ.get(name, default)


def codebase_root() -> str:
    return _get("CODEBASE_ROOT", ".")


def storage_kind() -> str:
    # filesystem (por defecto, como el de LightRAG) | neo4j | postgres
    return _get("CODEBASE_STORAGE", "filesystem").lower()


def snapshot_path() -> str:
    # Backend 'filesystem': el grafo de código se persiste en un JSON local (equivalente al
    # NetworkX pickled del filesystem de LightRAG). CODEBASE_MEMORY_SNAPSHOT es alias legacy.
    return (_get("CODEBASE_SNAPSHOT", "") or _get("CODEBASE_MEMORY_SNAPSHOT", "")
            or "config/codebase.json")


def entrypoints() -> list:
    raw = _get("CODEBASE_ENTRYPOINTS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def reusable_min_modules() -> int:
    try:
        return int(_get("CODEBASE_REUSABLE_MIN_MODULES", "2"))
    except ValueError:
        return 2


def langs() -> list:
    raw = _get("CODEBASE_LANGS", "python,js,ts,java,csharp,vb6,vbnet,vbscript,asp")
    return [x.strip() for x in raw.split(",") if x.strip()]


def make_store():
    """Crea el GraphStore según CODEBASE_STORAGE. Import perezoso de los backends de BD."""
    kind = storage_kind()
    if kind == "neo4j":  # pragma: no cover - requiere driver/servicio
        from .graph.neo4j_store import Neo4jGraphStore
        return Neo4jGraphStore(
            uri=_get("CODEBASE_NEO4J_URI", "neo4j://localhost:7687"),
            user=_get("CODEBASE_NEO4J_USER", "neo4j"),
            password=_get("CODEBASE_NEO4J_PASSWORD", ""),
            database=_get("CODEBASE_NEO4J_DATABASE", "neo4j"),
        )
    if kind == "postgres":  # pragma: no cover - requiere driver/servicio
        from .graph.postgres_store import PostgresGraphStore
        return PostgresGraphStore(dsn=_get("CODEBASE_POSTGRES_DSN", ""))
    # filesystem (por defecto): grafo en memoria persistido a un JSON local.
    from .graph.memory_store import InMemoryGraphStore
    store = InMemoryGraphStore()
    snap = snapshot_path()
    if snap:
        store.load_json(snap)
    return store
