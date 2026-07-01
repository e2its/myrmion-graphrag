"""Cableado del supervisor de consistencia a los backends REALES del perfil híbrido.

Este módulo hace I/O contra LightRAG (API), Neo4j y Postgres, así que está excluido de la
cobertura y se ejercita con tests de integración. La lógica pura (saga, diff, plan) vive en
`consistency.py` y sí está testeada.

NOTA HONESTA: las consultas concretas de "doc_ids en el grafo / en vectores" dependen del
esquema interno de la versión de LightRAG instalada. Se implementan de forma best-effort y
puede que haya que ajustarlas a tu versión (por eso el dry-run por defecto).
"""

from __future__ import annotations

import os

import consistency
from backends import parse_env


def _env() -> dict:
    env = dict(os.environ)
    try:
        with open("config/lightrag.env", encoding="utf-8") as fh:
            env.update(parse_env(fh.read()))
    except OSError:
        pass
    return env


class _LightRAGDocSource:  # pragma: no cover
    def __init__(self, env):
        from mcp_server import LightRAGClient

        self.client = LightRAGClient(
            base_url=env.get("LIGHTRAG_BASE_URL", "http://localhost:9621"),
            api_key=env.get("LIGHTRAG_API_KEY", ""),
        )

    def ping(self) -> bool:
        return "OK" in self.client.health()

    def processed_doc_ids(self) -> set:
        r = self.client._get("/documents")
        if r.status_code != 200:
            return set()
        statuses = (r.json() or {}).get("statuses", {})
        out = set()
        for docs in statuses.values():
            for d in docs or []:
                if isinstance(d, dict) and (d.get("status") == "processed" or "processed" in str(d.get("status", "")).lower()):
                    out.add(d.get("id") or d.get("doc_id"))
        return {x for x in out if x}

    def reindex(self, doc_id):
        self.client._post("/documents/scan", {})

    def delete(self, doc_id):
        self.client.delete_document(doc_id)


class _Neo4jDocReader:  # pragma: no cover
    def __init__(self, env):
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(
            env.get("NEO4J_URI", "neo4j://localhost:7687"),
            auth=(env.get("NEO4J_USERNAME", "neo4j"), env.get("NEO4J_PASSWORD", "")),
        )

    def ping(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def doc_ids(self) -> set:
        with self._driver.session() as s:
            rows = s.run("MATCH (n) WHERE n.doc_id IS NOT NULL RETURN DISTINCT n.doc_id AS d")
            return {r["d"] for r in rows if r["d"]}

    def delete(self, doc_id):
        with self._driver.session() as s:
            s.run("MATCH (n {doc_id:$d}) DETACH DELETE n", d=doc_id)


class _PostgresDocReader:  # pragma: no cover
    def __init__(self, env):
        import psycopg

        self._conn = psycopg.connect(
            host=env.get("POSTGRES_HOST", "localhost"), port=env.get("POSTGRES_PORT", "5432"),
            user=env.get("POSTGRES_USER", "rag"), password=env.get("POSTGRES_PASSWORD", ""),
            dbname=env.get("POSTGRES_DATABASE", "lightrag"), autocommit=True,
        )

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def doc_ids(self) -> set:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT DISTINCT full_doc_id FROM lightrag_doc_chunks")
                return {r[0] for r in cur.fetchall() if r[0]}
        except Exception:
            return set()

    def delete(self, doc_id):
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM lightrag_doc_chunks WHERE full_doc_id=%s", (doc_id,))


def build_supervisor():  # pragma: no cover
    env = _env()
    return consistency.Supervisor(
        lightrag=_LightRAGDocSource(env),
        graph_reader=_Neo4jDocReader(env),
        vector_reader=_PostgresDocReader(env),
    )
