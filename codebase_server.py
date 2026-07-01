#!/usr/bin/env python3
"""
Servidor MCP de análisis de codebases (segundo servidor: `myrmion-codebase`).

Expone, vía MCP, consultas sobre el grafo de código: dependencias, quién llama a qué, a qué
afecta un cambio (blast radius), inventario (reutilizable/obligatoria/muerta), histórico y
sincronización incremental. El razonamiento en lenguaje natural lo hace el cliente (Claude);
este servidor solo aporta hechos estructurados. Espejo fino de `mcp_server.py`.

Config por variables de entorno (ver codebase.env.example): CODEBASE_ROOT, CODEBASE_STORAGE
(filesystem|neo4j|postgres), CODEBASE_SNAPSHOT, CODEBASE_ENTRYPOINTS, ...
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from codebase_mcp import config, gitutil, indexer, inventory, queries

mcp = FastMCP("myrmion-codebase")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _save(store) -> None:
    if hasattr(store, "save_json"):
        try:
            store.save_json(config.snapshot_path())
        except OSError:
            pass


def _resolve(store, simbolo):
    node_id, candidatos = queries.resolve_symbol(store, simbolo)
    if node_id is None:
        if candidatos:
            return None, f"Símbolo ambiguo '{simbolo}'. Candidatos: {', '.join(candidatos[:20])}"
        return None, f"No encontré el símbolo '{simbolo}'. Prueba con su qualified_name."
    return node_id, None


@mcp.tool()
def indexar_codebase(ruta: str = "", incremental: bool = False) -> str:
    """Indexa (o reindexa) un codebase en el grafo de código.

    Args:
        ruta: Raíz del codebase. Si se omite, usa CODEBASE_ROOT.
        incremental: Reservado; el indexado completo es idempotente.
    """
    root = ruta or config.codebase_root()
    store = config.make_store()
    try:
        res = indexer.index(store, root, sha=gitutil.current_sha(root),
                            branch=gitutil.current_branch(root),
                            commit_time=gitutil.commit_time(root))
    except Exception as e:  # noqa: BLE001
        return f"Error indexando {root}: {type(e).__name__}: {e}"
    _save(store)
    return _json(res)


@mcp.tool()
def sincronizar_codigo(rutas: list) -> str:
    """Sincroniza el grafo del código tras editar ficheros, SIN duplicados ni residuos.

    Reindexa solo los ficheros dados (borra sus símbolos previos, re-parsea y re-resuelve las
    llamadas cruzadas) y persiste en el store configurado (CODEBASE_STORAGE). Idempotente.

    Args:
        rutas: Rutas (relativas a CODEBASE_ROOT) de los ficheros editados.
    """
    root = config.codebase_root()
    store = config.make_store()
    try:
        res = indexer.sync_paths(store, root, rutas, sha=gitutil.current_sha(root),
                                 branch=gitutil.current_branch(root))
    except Exception as e:  # noqa: BLE001
        return f"Error sincronizando: {type(e).__name__}: {e}"
    _save(store)
    return _json(res)


@mcp.tool()
def dependencias_de(simbolo: str, profundidad: int = 1) -> str:
    """Devuelve de qué depende un símbolo (a qué llama), hasta `profundidad` niveles.

    Args:
        simbolo: Nombre simple o qualified_name (p.ej. "run" o "svc.Service.run").
        profundidad: Niveles de llamadas a seguir (1 = directas).
    """
    store = config.make_store()
    nid, err = _resolve(store, simbolo)
    if err:
        return err
    return _json(queries.callees_transitive(store, nid, depth=int(profundidad)))


@mcp.tool()
def quien_llama_a(simbolo: str, profundidad: int = 1) -> str:
    """Devuelve quién llama a un símbolo (callers), hasta `profundidad` niveles.

    Args:
        simbolo: Nombre simple o qualified_name del símbolo objetivo.
        profundidad: Niveles de callers a seguir (1 = directos).
    """
    store = config.make_store()
    nid, err = _resolve(store, simbolo)
    if err:
        return err
    return _json(queries.callers_transitive(store, nid, depth=int(profundidad)))


@mcp.tool()
def a_que_afecta(simbolo: str, profundidad: int = 5) -> str:
    """Blast radius: qué símbolos se ven afectados si cambias `simbolo` (dependientes).

    Args:
        simbolo: Nombre simple o qualified_name del símbolo que vas a cambiar.
        profundidad: Alcance de la propagación de impacto (1-5).
    """
    store = config.make_store()
    nid, err = _resolve(store, simbolo)
    if err:
        return err
    return _json(queries.blast_radius(store, nid, depth=int(profundidad)))


@mcp.tool()
def inventario(filtro: str = "") -> str:
    """Inventario de símbolos con etiquetas reusable/mandatory/dead.

    Args:
        filtro: `reusable`|`mandatory`|`dead` para filtrar por etiqueta, o un texto para
            filtrar por qualified_name. Vacío = todos.
    """
    store = config.make_store()
    items = inventory.build(store, entrypoints=config.entrypoints(),
                            reusable_min_modules=config.reusable_min_modules())
    f = (filtro or "").strip().lower()
    if f in ("reusable", "mandatory", "dead"):
        items = [it for it in items if it[f]]
    elif f:
        items = [it for it in items if f in it["qualified_name"].lower()]
    return _json(items)


@mcp.tool()
def codigo_muerto() -> str:
    """Funciones/clases sin callers y no exportadas (candidatas a eliminar)."""
    store = config.make_store()
    return _json(inventory.dead_code(store, entrypoints=config.entrypoints()))


@mcp.tool()
def arquitectura() -> str:
    """Vista general: lenguajes, módulos, hotspots (mayor fan-in), reutilizables, muertos."""
    store = config.make_store()
    return _json(inventory.architecture_overview(store, entrypoints=config.entrypoints()))


@mcp.tool()
def cambios_desde(git_ref: str) -> str:
    """Ficheros cambiados desde `git_ref` y el blast radius de los símbolos tocados.

    Args:
        git_ref: Referencia git (commit/tag/rama) contra la que comparar el working tree.
    """
    root = config.codebase_root()
    store = config.make_store()
    ficheros = gitutil.changed_files(git_ref, cwd=root)
    fset = set(ficheros)
    # una sola pasada sobre los nodos, agrupando por fichero (evita O(ficheros x nodos))
    por_fichero = {}
    for n in store.find_nodes():
        if n.file in fset and n.kind in ("Function", "Method", "Class"):
            por_fichero.setdefault(n.file, []).append(n)
    afectados = {}
    for f in ficheros:
        for n in por_fichero.get(f, []):
            afectados[n.qualified_name] = queries.blast_radius(store, n.id, depth=3)
    return _json({"ficheros": ficheros, "afectados": afectados})


@mcp.tool()
def anotar_simbolo(simbolo: str, etiqueta: str, nota: str = "") -> str:
    """Fija una anotación persistente en un símbolo (sobrevive reindexados).

    Args:
        simbolo: Nombre simple o qualified_name del símbolo a anotar.
        etiqueta: `mandatory`|`reusable`|`deprecated`|`keep` o una etiqueta libre.
        nota: Texto opcional asociado a la anotación.
    """
    store = config.make_store()
    nid, err = _resolve(store, simbolo)
    if err:
        return err
    store.set_annotation(nid, etiqueta, nota)
    _save(store)
    return f"Anotación '{etiqueta}' fijada en {simbolo}."


@mcp.tool()
def historico(simbolo: str) -> str:
    """Evolución de un símbolo (added/modified/removed por commit).

    Args:
        simbolo: Nombre simple o qualified_name del símbolo.
    """
    store = config.make_store()
    nid, err = _resolve(store, simbolo)
    if err:
        return err
    recs = store.history_of(nid)
    return _json([{"snapshot": r.snapshot_id, "cambio": r.change, "detalle": r.detail} for r in recs])


@mcp.tool()
def estado_indexado() -> str:
    """Último snapshot del inventario y si el codebase cambió desde entonces."""
    store = config.make_store()
    snap = store.latest_snapshot()
    root = config.codebase_root()
    actual = gitutil.current_sha(root)
    return _json({
        "ultimo_snapshot": snap.__dict__ if snap else None,
        "sha_actual": actual,
        "desincronizado": bool(snap and snap.commit_sha and snap.commit_sha != actual),
    })


if __name__ == "__main__":  # pragma: no cover
    mcp.run(transport="stdio")
