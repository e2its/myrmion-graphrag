"""PostgresGraphStore: grafo de código en PostgreSQL (tablas relacionales). Import perezoso.

Alternativa a Neo4j. Como los algoritmos de grafo (BFS, inventario) corren en Python sobre
`all_nodes()/all_edges()`, aquí basta con persistencia relacional simple (sin AGE). Excluido
de la cobertura (requiere un Postgres real; tests de integración).
"""

from __future__ import annotations

from ..models import Annotation, ChangeRecord, Edge, Node, Snapshot
from .store import GraphStore

_DDL = """
CREATE TABLE IF NOT EXISTS cb_nodes (
  id TEXT PRIMARY KEY, kind TEXT, qualified_name TEXT, name TEXT, file TEXT,
  lineno INT, end_lineno INT, lang TEXT, body_hash TEXT);
CREATE TABLE IF NOT EXISTS cb_edges (
  src TEXT, kind TEXT, dst TEXT, callee_name TEXT, receiver TEXT,
  confidence TEXT, external BOOLEAN, PRIMARY KEY (src, kind, dst, callee_name, receiver));
CREATE TABLE IF NOT EXISTS cb_annotations (
  node_id TEXT, label TEXT, note TEXT, PRIMARY KEY (node_id, label));
CREATE TABLE IF NOT EXISTS cb_snapshots (
  id SERIAL PRIMARY KEY, commit_sha TEXT, commit_time TEXT, branch TEXT,
  created_at TEXT, node_count INT, edge_count INT);
CREATE TABLE IF NOT EXISTS cb_changes (
  snapshot_id INT, node_id TEXT, change TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS cb_file_hashes (file TEXT PRIMARY KEY, digest TEXT);
"""


class PostgresGraphStore(GraphStore):  # pragma: no cover
    def __init__(self, dsn):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(_DDL)

    def _q(self, sql, params=()):
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            try:
                return cur.fetchall()
            except Exception:
                return []

    def upsert_node(self, node: Node) -> None:
        d = node.__dict__
        self._q(
            "INSERT INTO cb_nodes VALUES (%(id)s,%(kind)s,%(qualified_name)s,%(name)s,%(file)s,"
            "%(lineno)s,%(end_lineno)s,%(lang)s,%(body_hash)s) ON CONFLICT (id) DO UPDATE SET "
            "kind=EXCLUDED.kind, qualified_name=EXCLUDED.qualified_name, name=EXCLUDED.name, "
            "file=EXCLUDED.file, lineno=EXCLUDED.lineno, end_lineno=EXCLUDED.end_lineno, "
            "lang=EXCLUDED.lang, body_hash=EXCLUDED.body_hash",
            {**d, "id": node.id},
        )

    def upsert_edge(self, edge: Edge) -> None:
        # ON CONFLICT DO UPDATE: si la misma arista se re-inserta tras resolverse, actualiza
        # confidence/external en vez de descartar el update.
        self._q(
            "INSERT INTO cb_edges VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (src,kind,dst,callee_name,receiver) "
            "DO UPDATE SET confidence=EXCLUDED.confidence, external=EXCLUDED.external",
            (edge.src, edge.kind, edge.dst, edge.callee_name, edge.receiver, edge.confidence, edge.external),
        )

    def delete_by_file(self, file: str) -> None:
        ids = [r[0] for r in self._q("SELECT id FROM cb_nodes WHERE file=%s", (file,))]
        self._q("DELETE FROM cb_nodes WHERE file=%s", (file,))
        for nid in ids:
            # borra aristas donde el nodo es origen O destino (no deja aristas colgando)
            self._q("DELETE FROM cb_edges WHERE src=%s OR dst=%s", (nid, nid))

    def clear(self) -> None:
        self._q("DELETE FROM cb_nodes")
        self._q("DELETE FROM cb_edges")
        self._q("DELETE FROM cb_file_hashes")

    def replace_edges(self, edges) -> None:
        self._q("DELETE FROM cb_edges")
        for e in edges:
            self.upsert_edge(e)

    def _node(self, r) -> Node:
        return Node(kind=r[1], qualified_name=r[2], name=r[3], file=r[4], lineno=r[5],
                    end_lineno=r[6], lang=r[7], body_hash=r[8])

    def get_node(self, node_id):
        rows = self._q("SELECT * FROM cb_nodes WHERE id=%s", (node_id,))
        return self._node(rows[0]) if rows else None

    def all_nodes(self) -> list:
        return [self._node(r) for r in self._q("SELECT * FROM cb_nodes")]

    def all_edges(self) -> list:
        return [Edge(src=r[0], kind=r[1], dst=r[2], callee_name=r[3], receiver=r[4],
                     confidence=r[5], external=r[6]) for r in self._q("SELECT * FROM cb_edges")]

    def find_nodes(self, name=None, kind=None, qualified=None) -> list:
        return [n for n in self.all_nodes()
                if (name is None or n.name == name)
                and (kind is None or n.kind == kind)
                and (qualified is None or n.qualified_name == qualified)]

    def callers(self, node_id) -> list:
        return [e for e in self.all_edges() if e.kind == "CALLS" and e.dst == node_id]

    def callees(self, node_id) -> list:
        return [e for e in self.all_edges() if e.kind == "CALLS" and e.src == node_id]

    def search(self, texto) -> list:
        t = (texto or "").lower()
        return [n for n in self.all_nodes() if t in n.name.lower() or t in n.qualified_name.lower()]

    def set_annotation(self, node_id, label, note="") -> None:
        self._q("INSERT INTO cb_annotations VALUES (%s,%s,%s) ON CONFLICT (node_id,label) "
                "DO UPDATE SET note=EXCLUDED.note", (node_id, label, note))

    def get_annotations(self, node_id=None) -> list:
        if node_id is None:
            rows = self._q("SELECT node_id,label,note FROM cb_annotations")
        else:
            rows = self._q("SELECT node_id,label,note FROM cb_annotations WHERE node_id=%s", (node_id,))
        return [Annotation(node_id=r[0], label=r[1], note=r[2]) for r in rows]

    def create_snapshot(self, snap: Snapshot) -> int:
        rows = self._q(
            "INSERT INTO cb_snapshots (commit_sha,commit_time,branch,created_at,node_count,edge_count) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (snap.commit_sha, snap.commit_time, snap.branch, snap.created_at, snap.node_count, snap.edge_count),
        )
        return rows[0][0]

    def record_changes(self, changes) -> None:
        for c in changes:
            self._q("INSERT INTO cb_changes VALUES (%s,%s,%s,%s)",
                    (c.snapshot_id, c.node_id, c.change, c.detail))

    def latest_snapshot(self):
        rows = self._q("SELECT id,commit_sha,commit_time,branch,created_at,node_count,edge_count "
                       "FROM cb_snapshots ORDER BY id DESC LIMIT 1")
        if not rows:
            return None
        r = rows[0]
        return Snapshot(id=r[0], commit_sha=r[1], commit_time=r[2], branch=r[3],
                        created_at=r[4], node_count=r[5], edge_count=r[6])

    def history_of(self, node_id) -> list:
        rows = self._q("SELECT snapshot_id,node_id,change,detail FROM cb_changes WHERE node_id=%s", (node_id,))
        return [ChangeRecord(snapshot_id=r[0], node_id=r[1], change=r[2], detail=r[3]) for r in rows]

    def get_file_hash(self, file):
        rows = self._q("SELECT digest FROM cb_file_hashes WHERE file=%s", (file,))
        return rows[0][0] if rows else None

    def set_file_hash(self, file, digest) -> None:
        self._q("INSERT INTO cb_file_hashes VALUES (%s,%s) ON CONFLICT (file) DO UPDATE SET digest=EXCLUDED.digest",
                (file, digest))
