"""CLI de sincronización del inventario, compartido por la tool MCP y los git/Claude hooks.

  python -m codebase_mcp.sync [--durable|--overlay] <fichero> [<fichero> ...]

- --durable (por defecto): reconcilia el inventario canónico (usado por el pre-push a main).
- --overlay: mantiene caliente el overlay de sesión (usado por el hook PostToolUse).

Una sola función `run()` es la fuente de verdad; los hooks son thin wrappers sobre ella.
"""

from __future__ import annotations

import json
import sys

from . import config, gitutil, indexer


def run(paths, durable=True, root=None, store=None) -> dict:
    root = root or config.codebase_root()
    if store is None:  # pragma: no cover - construye backend real (neo4j/postgres/memory)
        store = config.make_store()
    summary = indexer.sync_paths(
        store, root, list(paths),
        sha=gitutil.current_sha(root), branch=gitutil.current_branch(root),
    )
    summary["destino"] = "durable" if durable else "overlay"
    if hasattr(store, "save_json"):
        target = config.snapshot_path() if durable else config.snapshot_path() + ".overlay"
        try:
            store.save_json(target)
        except OSError:
            pass
    return summary


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    durable = True
    paths = []
    for a in argv:
        if a == "--durable":
            durable = True
        elif a == "--overlay":
            durable = False
        else:
            paths.append(a)
    if not paths:
        print("Uso: python -m codebase_mcp.sync [--durable|--overlay] <fichero> ...")
        return 2
    try:
        summary = run(paths, durable=durable)
    except Exception as e:  # noqa: BLE001 - el hook debe fallar (exit!=0) si no reconcilia
        print(f"ERROR de sincronizacion: {type(e).__name__}: {e}")
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
