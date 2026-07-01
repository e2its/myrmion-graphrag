"""Histórico del inventario: diff de símbolos entre estados (por node_id estable)."""

from __future__ import annotations

from .models import ChangeRecord


def diff_nodes(old_nodes, new_nodes) -> list:
    """Compara dos conjuntos de nodos por id estable. Devuelve [(node_id, change, detail)].

    change ∈ {added, removed, modified}. 'modified' compara body_hash; si además cambió el
    fichero, el detalle es 'movida'.
    """
    old = {n.id: n for n in old_nodes}
    new = {n.id: n for n in new_nodes}
    out = []
    for nid, n in new.items():
        if nid not in old:
            out.append((nid, "added", ""))
        elif old[nid].body_hash != n.body_hash or old[nid].file != n.file:
            detail = "movida" if old[nid].file != n.file else "firma/cuerpo cambiado"
            out.append((nid, "modified", detail))
    for nid in old:
        if nid not in new:
            out.append((nid, "removed", ""))
    return out


def to_change_records(snapshot_id, diffs) -> list:
    return [
        ChangeRecord(snapshot_id=snapshot_id, node_id=nid, change=change, detail=detail)
        for nid, change, detail in diffs
    ]
