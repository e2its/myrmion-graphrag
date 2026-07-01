"""Inventario de código: clasificación reusable / mandatory / dead + anotaciones.

Vista derivada del grafo (heurísticas) fusionada con anotaciones persistentes del usuario
(por node_id estable, sobreviven reindexados y prevalecen sobre la heurística).
"""

from __future__ import annotations

from collections import deque

_SYMBOL_KINDS = {"Function", "Method", "Class"}
_DEP_KINDS = {"CALLS", "INHERITS", "IMPLEMENTS"}


def _module_of(nodes):
    return {n.file: n.qualified_name for n in nodes if n.kind == "Module"}


def _reachable_from(entrypoint_ids, edges):
    adj: dict = {}
    for e in edges:
        if e.kind in _DEP_KINDS and e.dst:
            adj.setdefault(e.src, []).append(e.dst)
    seen = set(entrypoint_ids)
    q = deque(entrypoint_ids)
    while q:
        node = q.popleft()
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def build(store, entrypoints=None, reusable_min_modules=2):
    nodes = store.all_nodes()
    edges = store.all_edges()
    by_id = {n.id: n for n in nodes}
    file_to_module = _module_of(nodes)
    entryset = {e.lower() for e in (entrypoints or [])}

    # aristas entrantes por destino
    incoming: dict = {}
    for e in edges:
        if e.kind in _DEP_KINDS and e.dst:
            incoming.setdefault(e.dst, []).append(e)

    entrypoint_ids = {
        n.id for n in nodes
        if n.kind in _SYMBOL_KINDS and (n.name.lower() in entryset or n.name.lower() == "main")
    }
    reachable = _reachable_from(entrypoint_ids, edges)

    items = []
    for n in nodes:
        if n.kind not in _SYMBOL_KINDS:
            continue
        inc = incoming.get(n.id, [])
        modules = set()
        call_in = 0
        for e in inc:
            src = by_id.get(e.src)
            if src:
                modules.add(file_to_module.get(src.file, src.file))
            if e.kind == "CALLS":
                call_in += 1
        public = not n.name.startswith("_")

        ann = {a.label: a.note for a in store.get_annotations(n.id)}
        reusable = (len(modules) >= reusable_min_modules and public) or "reusable" in ann
        mandatory = (n.id in reachable) or "mandatory" in ann
        dead = (
            call_in == 0
            and not mandatory
            and public
            and not n.name.startswith("__")
            and "keep" not in ann
        )
        labels = []
        if reusable:
            labels.append("reusable")
        if mandatory:
            labels.append("mandatory")
        if dead:
            labels.append("dead")
        for extra in ann:
            if extra not in ("reusable", "mandatory", "keep"):
                labels.append(extra)

        items.append({
            "qualified_name": n.qualified_name,
            "kind": n.kind,
            "lang": n.lang,
            "file": n.file,
            "fan_in": len(inc),
            "fan_in_modules": len(modules),
            "reusable": reusable,
            "mandatory": mandatory,
            "dead": dead,
            "labels": labels,
            "annotations": ann,
        })
    return items


def dead_code(store, entrypoints=None):
    return [it for it in build(store, entrypoints) if it["dead"]]


def architecture_overview(store, entrypoints=None):
    nodes = store.all_nodes()
    inv = build(store, entrypoints)
    langs: dict = {}
    for n in nodes:
        langs[n.lang] = langs.get(n.lang, 0) + 1
    hotspots = sorted(inv, key=lambda it: it["fan_in"], reverse=True)[:5]
    return {
        "lenguajes": langs,
        "modulos": sum(1 for n in nodes if n.kind == "Module"),
        "simbolos": len(inv),
        "hotspots": [{"qualified_name": h["qualified_name"], "fan_in": h["fan_in"]} for h in hotspots],
        "reusables": sum(1 for it in inv if it["reusable"]),
        "mandatory": sum(1 for it in inv if it["mandatory"]),
        "muertos": sum(1 for it in inv if it["dead"]),
    }
