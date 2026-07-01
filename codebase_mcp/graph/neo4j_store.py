"""Neo4jGraphStore: grafo de código en Neo4j (recomendado). Import perezoso de `neo4j`.

Excluido de la cobertura (requiere un Neo4j real; se prueba con tests de integración). El
grafo de código es un grafo puro y un solo store → sin deriva posible. Los algoritmos (BFS,
inventario) corren en Python sobre `all_nodes()/all_edges()`, así que el store solo persiste.
"""

from __future__ import annotations

from ..models import Annotation, Edge, Node, Snapshot
from .store import GraphStore

_LABEL = "CodeSymbol"


class Neo4jGraphStore(GraphStore):  # pragma: no cover
    def __init__(self, uri, user, password, database="neo4j"):
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._db = database
        self._init_schema()

    def _run(self, cypher, **params):
        with self._driver.session(database=self._db) as s:
            return list(s.run(cypher, **params))

    def _init_schema(self):
        self._run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{_LABEL}) REQUIRE n.id IS UNIQUE")

    # --- escritura ---
    def upsert_node(self, node: Node) -> None:
        self._run(
            f"MERGE (n:{_LABEL} {{id:$id}}) SET n += $props",
            id=node.id, props=dict(node.__dict__),
        )

    def upsert_edge(self, edge: Edge) -> None:
        if edge.dst:
            self._run(
                f"MATCH (a:{_LABEL} {{id:$src}}) "
                f"MERGE (b:{_LABEL} {{id:$dst}}) "
                "MERGE (a)-[r:REL {kind:$kind, callee:$callee, receiver:$recv}]->(b) "
                "SET r.confidence=$conf, r.external=$ext",
                src=edge.src, dst=edge.dst,
                kind=edge.kind, callee=edge.callee_name, recv=edge.receiver,
                conf=edge.confidence, ext=edge.external,
            )
        else:
            # Arista sin resolver: el destino NO es un símbolo real. Se guarda con una
            # etiqueta aparte (:Unresolved) para que all_nodes() (solo :CodeSymbol) no lo
            # devuelva y no contamine las queries.
            self._run(
                f"MATCH (a:{_LABEL} {{id:$src}}) "
                "MERGE (b:Unresolved {id:$ph}) "
                "MERGE (a)-[r:REL {kind:$kind, callee:$callee, receiver:$recv}]->(b) "
                "SET r.confidence=$conf, r.external=$ext",
                src=edge.src, ph=f"?{edge.callee_name}:{edge.receiver}",
                kind=edge.kind, callee=edge.callee_name, recv=edge.receiver,
                conf=edge.confidence, ext=edge.external,
            )

    def delete_by_file(self, file: str) -> None:
        self._run(f"MATCH (n:{_LABEL} {{file:$f}}) DETACH DELETE n", f=file)

    def clear(self) -> None:
        self._run(f"MATCH (n:{_LABEL}) DETACH DELETE n")
        self._run("MATCH (n:Unresolved) DETACH DELETE n")

    def replace_edges(self, edges) -> None:
        self._run(f"MATCH (:{_LABEL})-[r:REL]->() DELETE r")
        self._run("MATCH (n:Unresolved) DETACH DELETE n")
        for e in edges:
            self.upsert_edge(e)

    # --- lectura ---
    def _to_node(self, rec) -> Node:
        d = dict(rec["n"])
        return Node(kind=d["kind"], qualified_name=d["qualified_name"], name=d["name"],
                    file=d.get("file") or "", lineno=d.get("lineno") or 0,
                    end_lineno=d.get("end_lineno") or 0, lang=d.get("lang") or "",
                    body_hash=d.get("body_hash") or "")

    def get_node(self, node_id):
        rows = self._run(f"MATCH (n:{_LABEL} {{id:$id}}) RETURN n", id=node_id)
        return self._to_node(rows[0]) if rows else None

    def all_nodes(self) -> list:
        return [self._to_node(r) for r in self._run(f"MATCH (n:{_LABEL}) RETURN n")]

    def all_edges(self) -> list:
        rows = self._run(
            f"MATCH (a:{_LABEL})-[r:REL]->(b) RETURN a.id AS src, b.id AS dst, r")
        out = []
        for r in rows:
            rel = r["r"]
            dst = r["dst"] if not str(r["dst"]).startswith("?") else ""
            out.append(Edge(src=r["src"], kind=rel["kind"], dst=dst,
                            callee_name=rel.get("callee", ""), receiver=rel.get("receiver", ""),
                            confidence=rel.get("confidence", "exact"), external=rel.get("external", False)))
        return out

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

    # --- anotaciones (nodos :Annotation, sin arista al símbolo → sobreviven a clear) ---
    def set_annotation(self, node_id, label, note="") -> None:
        self._run("MERGE (a:Annotation {node_id:$n, label:$l}) SET a.note=$note",
                  n=node_id, l=label, note=note)

    def get_annotations(self, node_id=None) -> list:
        if node_id is None:
            rows = self._run("MATCH (a:Annotation) RETURN a")
        else:
            rows = self._run("MATCH (a:Annotation {node_id:$n}) RETURN a", n=node_id)
        return [Annotation(node_id=r["a"]["node_id"], label=r["a"]["label"], note=r["a"].get("note", "")) for r in rows]

    # --- historia ---
    def create_snapshot(self, snap: Snapshot) -> int:
        rows = self._run("MATCH (s:Snapshot) RETURN coalesce(max(s.id),0)+1 AS nid")
        nid = rows[0]["nid"]
        self._run("CREATE (s:Snapshot $props)",
                  props={**snap.__dict__, "id": nid})
        return nid

    def record_changes(self, changes) -> None:
        for c in changes:
            self._run("CREATE (:Change $props)", props=dict(c.__dict__))

    def latest_snapshot(self):
        rows = self._run("MATCH (s:Snapshot) RETURN s ORDER BY s.id DESC LIMIT 1")
        if not rows:
            return None
        d = dict(rows[0]["s"])
        return Snapshot(**d)

    def history_of(self, node_id) -> list:
        from ..models import ChangeRecord
        rows = self._run("MATCH (c:Change {node_id:$n}) RETURN c", n=node_id)
        return [ChangeRecord(**dict(r["c"])) for r in rows]

    def get_file_hash(self, file):
        rows = self._run("MATCH (h:FileHash {file:$f}) RETURN h.digest AS d", f=file)
        return rows[0]["d"] if rows else None

    def set_file_hash(self, file, digest) -> None:
        self._run("MERGE (h:FileHash {file:$f}) SET h.digest=$d", f=file, d=digest)
