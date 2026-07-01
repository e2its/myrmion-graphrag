"""Resolución de llamadas y herencias contra la tabla global de símbolos.

El parser emite CALLS/INHERITS/IMPLEMENTS "crudas" (dst=""). Aquí se resuelven a un
`Node.id` cuando es posible, con `confidence`:
  - exact     : resuelto sin ambigüedad (símbolo local, método de la clase, import directo).
  - heuristic : resuelto por unicidad de nombre en el proyecto o por import de módulo.
  - unresolved: no se pudo (varios candidatos o desconocido) — no se adivina.
`external=True` marca destinos importados/externos sin nodo interno.
"""

from __future__ import annotations

from .models import Edge

_SELF_LIKE = {"self", "me", "this", "mybase", "myclass", "mi"}


def _build_indexes(nodes, edges):
    by_id = {n.id: n for n in nodes}
    file_to_module = {n.file: n.qualified_name for n in nodes if n.kind == "Module"}

    defines: dict = {}
    imports_by_module: dict = {}
    for e in edges:
        if e.kind == "DEFINES" and e.dst:
            defines.setdefault(e.src, []).append(e.dst)
        elif e.kind == "IMPORTS":
            src_node = by_id.get(e.src)
            if src_node:
                imports_by_module.setdefault(src_node.qualified_name, set()).add(e.callee_name)

    module_top: dict = {}
    class_methods: dict = {}
    name_to_ids: dict = {}
    class_name_to_ids: dict = {}
    for n in nodes:
        if n.kind in ("Function", "Method", "Class"):
            name_to_ids.setdefault(n.name, []).append(n.id)
        if n.kind == "Class":
            class_name_to_ids.setdefault(n.name, []).append(n.id)

    for n in nodes:
        children = [by_id[c] for c in defines.get(n.id, []) if c in by_id]
        if n.kind == "Module":
            module_top[n.qualified_name] = {c.name: c.id for c in children}
        elif n.kind == "Class":
            class_methods[n.qualified_name] = {
                c.name: c.id for c in children if c.kind in ("Method", "Function")
            }
    return {
        "by_id": by_id, "file_to_module": file_to_module, "imports": imports_by_module,
        "module_top": module_top, "class_methods": class_methods,
        "name_to_ids": name_to_ids, "class_name_to_ids": class_name_to_ids,
    }


def _resolve_call(e, src_node, idx):
    module_qn = idx["file_to_module"].get(src_node.file)
    class_qn = None
    if src_node.kind == "Method" and "." in src_node.qualified_name:
        class_qn = src_node.qualified_name.rsplit(".", 1)[0]
    receiver = (e.receiver or "").lower()
    name = e.callee_name

    # 1. self.metodo() dentro de la clase
    if receiver in _SELF_LIKE and class_qn:
        hit = idx["class_methods"].get(class_qn, {}).get(name)
        if hit:
            return hit, "exact", False
    # 2. llamada sin receptor
    if not e.receiver:
        top = idx["module_top"].get(module_qn, {})
        if name in top:
            return top[name], "exact", False
        if class_qn and name in idx["class_methods"].get(class_qn, {}):
            return idx["class_methods"][class_qn][name], "exact", False
        # un símbolo del proyecto con ese nombre (aunque venga por import) → enlázalo
        ids = idx["name_to_ids"].get(name, [])
        if len(ids) == 1:
            return ids[0], "heuristic", False
        if name in idx["imports"].get(module_qn, set()):
            return "", "heuristic", True  # importado y sin símbolo interno único → externo
        return "", "unresolved", False
    # 3. receptor concreto (obj.metodo / modulo.func)
    if e.receiver in idx["imports"].get(module_qn, set()):
        return "", "heuristic", True
    ids = idx["name_to_ids"].get(name, [])
    if len(ids) == 1:
        return ids[0], "heuristic", False
    return "", "unresolved", False


def _resolve_type(e, src_node, idx):
    name = e.callee_name.split(".")[-1]
    module_qn = idx["file_to_module"].get(src_node.file)
    top = idx["module_top"].get(module_qn, {})
    if name in top:
        return top[name], "exact", False
    ids = idx["class_name_to_ids"].get(name, [])
    if len(ids) == 1:
        return ids[0], "heuristic", False
    return "", "heuristic", True  # base externa (otra librería)


def resolve_all(nodes, edges) -> list:
    """Devuelve una lista NUEVA de aristas con CALLS/INHERITS/IMPLEMENTS resueltas."""
    idx = _build_indexes(nodes, edges)
    out: list = []
    for e in edges:
        if e.kind in ("DEFINES", "IMPORTS"):
            out.append(e)
            continue
        src_node = idx["by_id"].get(e.src)
        if src_node is None:
            out.append(e)
            continue
        if e.kind == "CALLS":
            dst, conf, ext = _resolve_call(e, src_node, idx)
        else:  # INHERITS / IMPLEMENTS
            dst, conf, ext = _resolve_type(e, src_node, idx)
        out.append(Edge(src=e.src, kind=e.kind, dst=dst, callee_name=e.callee_name,
                        receiver=e.receiver, confidence=conf, external=ext))
    return out
