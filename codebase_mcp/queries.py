"""Consultas sobre el grafo: callers/callees transitivos y blast-radius (impacto).

Lógica pura sobre la interfaz `GraphStore`: idéntica para InMemory/Neo4j/Postgres.
"""

from __future__ import annotations

from collections import deque

_IMPACT_KINDS = {"CALLS", "INHERITS", "IMPLEMENTS"}


def resolve_symbol(store, symbol: str):
    """Resuelve `symbol` (qualified_name o nombre simple) a un node_id.

    Devuelve (node_id | None, candidatos). Si hay ambigüedad, node_id=None y candidatos
    lista los qualified_name posibles (no se adivina).
    """
    # coincidencia exacta por qualified_name
    exact = store.find_nodes(qualified=symbol)
    if len(exact) == 1:
        return exact[0].id, []
    if len(exact) > 1:
        return None, [n.qualified_name for n in exact]
    # por nombre simple
    by_name = [n for n in store.find_nodes(name=symbol) if n.kind != "Module"]
    if len(by_name) == 1:
        return by_name[0].id, []
    if len(by_name) > 1:
        return None, [n.qualified_name for n in by_name]
    return None, []


def _adjacency(edges, kinds, reverse=False):
    adj: dict = {}
    for e in edges:
        if e.kind in kinds and e.dst:
            a, b = (e.dst, e.src) if reverse else (e.src, e.dst)
            adj.setdefault(a, []).append((b, e))
    return adj


def _bfs_simple(start, adj, depth):
    seen = {start}
    out = []
    q = deque([(start, 0)])
    while q:
        node, d = q.popleft()
        if d >= depth:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                out.append((nxt, d + 1, edge))
                q.append((nxt, d + 1))
    return out


def _format(store, results):
    out = []
    for node_id, dist, edge in results:
        n = store.get_node(node_id)
        out.append({
            "id": node_id,
            "qualified_name": n.qualified_name if n else node_id,
            "kind": n.kind if n else "?",
            "file": n.file if n else "",
            "distance": dist,
            "confidence": edge.confidence,
        })
    return out


def callees_transitive(store, node_id, depth=1):
    adj = _adjacency(store.all_edges(), {"CALLS"}, reverse=False)
    return _format(store, _bfs_simple(node_id, adj, depth))


def callers_transitive(store, node_id, depth=1):
    adj = _adjacency(store.all_edges(), {"CALLS"}, reverse=True)
    return _format(store, _bfs_simple(node_id, adj, depth))


def blast_radius(store, node_id, depth=5):
    """Símbolos afectados si cambia `node_id`: dependientes transitivos (CALLS/INHERITS)."""
    adj = _adjacency(store.all_edges(), _IMPACT_KINDS, reverse=True)
    return _format(store, _bfs_simple(node_id, adj, depth))
