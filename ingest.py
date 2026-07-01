#!/usr/bin/env python3
"""
Ingesta en lote: sube todos los documentos de una carpeta al servidor LightRAG
e informa del progreso por consola en todo momento.

Dos fases, las dos con feedback:
  1) SUBIDA   -> contador [i/N], %, ETA, tamano y estado por fichero + resumen.
  2) INDEXADO -> es asincrono en el servidor. Con --watch se monitoriza en vivo
                 (pending/processing/processed/failed) hasta que el pipeline
                 queda inactivo. Sin --watch se muestra una foto del estado y
                 como seguir mirando.

La API key se toma de --api-key o, si no, de la variable LIGHTRAG_API_KEY.
La URL de --url o de LIGHTRAG_BASE_URL (por defecto http://localhost:9621).

Uso:
    python ingest.py ./mis_documentos
    python ingest.py "$INPUT_DIR" --api-key "$LIGHTRAG_API_KEY" --watch
"""

import argparse
import os
import pathlib
import sys
import time

import httpx

EXTS = {".md", ".txt", ".pdf", ".docx", ".doc", ".pptx", ".csv", ".rst", ".html"}

# Directorios de dependencias / build / control de versiones: su contenido NO
# son documentos del usuario, contamina el grafo y dispara el tiempo de indexado.
# Si una carpeta con cualquiera de estos nombres aparece en la ruta, se omite.
EXCLUDE_DIRS = {
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
    "site-packages", "dist", "build", ".next", ".nuxt", "target", "vendor",
    "bower_components", ".idea", ".vscode", ".cache", ".gradle", ".tox",
    ".pytest_cache", ".mypy_cache", ".angular", ".terraform",
}


def descubrir_ficheros(raiz, excluir=True):
    """Descubre ficheros indexables bajo `raiz` (recursivo).

    Filtra por extensión (`EXTS`) y, si `excluir`, omite los que caen en directorios de
    dependencias/build/VCS (`EXCLUDE_DIRS`). Devuelve `(ficheros_ordenados, n_omitidos)`.
    Lógica pura (sin red) para poder testearla directamente.
    """
    raiz = pathlib.Path(raiz)
    candidatos = [p for p in raiz.rglob("*")
                  if p.is_file() and p.suffix.lower() in EXTS]
    if not excluir:
        return sorted(candidatos), 0
    ficheros = sorted(
        p for p in candidatos
        if not any(parte in EXCLUDE_DIRS for parte in p.relative_to(raiz).parts)
    )
    return ficheros, len(candidatos) - len(ficheros)


def fmt_size(n):
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return f"{n:.0f}{unidad}" if unidad == "B" else f"{n:.1f}{unidad}"
        n /= 1024


def fmt_dur(seg):
    seg = int(seg)
    if seg < 60:
        return f"{seg}s"
    if seg < 3600:
        return f"{seg // 60}m{seg % 60:02d}s"
    return f"{seg // 3600}h{(seg % 3600) // 60:02d}m"


def _get_json(client, url, headers):
    try:
        r = client.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def status_counts(client, base, headers):
    """Cuenta documentos por estado desde GET /documents. None si no disponible."""
    data = _get_json(client, f"{base}/documents", headers)
    if isinstance(data, dict) and isinstance(data.get("statuses"), dict):
        return {k.upper(): len(v) for k, v in data["statuses"].items()}
    return None


def pipeline_busy(client, base, headers):
    """True/False segun GET /documents/pipeline_status, o None si no disponible."""
    data = _get_json(client, f"{base}/documents/pipeline_status", headers)
    if isinstance(data, dict) and "busy" in data:
        return bool(data["busy"])
    return None


def render_estado(counts, busy):
    partes = []
    if counts:
        orden = ["PENDING", "PROCESSING", "PROCESSED", "FAILED"]
        etiq = {"PENDING": "pendientes", "PROCESSING": "procesando",
                "PROCESSED": "indexados", "FAILED": "fallidos"}
        for k in orden + [k for k in counts if k not in orden]:
            if k in counts:
                partes.append(f"{etiq.get(k, k.lower())}={counts[k]}")
    if busy is not None:
        partes.append("pipeline=" + ("ocupado" if busy else "inactivo"))
    return "  ".join(partes) if partes else "(el servidor no expone estado de indexado)"


def watch_indexado(client, base, headers):
    print("\n== Indexado en vivo (Ctrl-C para dejar de mirar; continua en 2o plano) ==",
          flush=True)
    ultimo, inactivo_seguidos = None, 0
    try:
        while True:
            counts = status_counts(client, base, headers)
            busy = pipeline_busy(client, base, headers)
            linea = render_estado(counts, busy)
            if linea != ultimo:
                print(f"  {linea}", flush=True)
                ultimo = linea
            pendientes = (counts or {}).get("PENDING", 0) + (counts or {}).get("PROCESSING", 0)
            if busy is False and pendientes == 0:
                inactivo_seguidos += 1
            else:
                inactivo_seguidos = 0
            if counts is None and busy is None:
                print("  No puedo leer el estado de indexado en este servidor. "
                      "Mira la Web UI.", flush=True)
                return
            if inactivo_seguidos >= 2:
                print("Indexado completo (pipeline inactivo).", flush=True)
                return
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nDejo de mirar. El indexado sigue en segundo plano en el servidor.",
              flush=True)


def _sync_batch(base, api_key, ficheros, ledger_path):
    """Sincronización VERSIONADA: sube solo added/modified (borrando la version previa en
    LightRAG) y borra lo eliminado. Detecta cambios por hash de bytes (ledger), así que
    re-ejecutar NO deja que LightRAG archive el update como duplicado."""
    import doc_ledger
    from mcp_server import LightRAGClient, _delete_ok, _msg_ok

    client = LightRAGClient(base_url=base, api_key=api_key)
    ledger = doc_ledger.load(ledger_path)
    by_name = {p.name: str(p) for p in ficheros}
    docs = {str(p): doc_ledger.file_hash(p) for p in ficheros}
    diffs = doc_ledger.diff_batch(ledger, docs)  # calcula SIN mutar
    stats = {"nuevos": 0, "modificados": 0, "borrados": 0,
             "sin_cambios": len(ficheros), "errores": 0}
    applied = []
    for entry in diffs:
        nid, change, _detail = entry
        name = nid.split(":", 1)[1]
        if change in ("added", "modified"):
            msg = client.upsert_file(by_name[name])
            print("  " + msg, flush=True)
            if _msg_ok(msg):
                applied.append(entry)
                stats["nuevos" if change == "added" else "modificados"] += 1
                stats["sin_cambios"] -= 1
            else:
                stats["errores"] += 1
        elif change == "removed":
            if _delete_ok(client, name):
                applied.append(entry)
                print(f"  Borrado en LightRAG (ya no existe): {name}", flush=True)
                stats["borrados"] += 1
            else:
                stats["errores"] += 1
    # Versiona SOLO lo aplicado con éxito (lo fallido se reintenta la próxima vez).
    doc_ledger.commit(ledger, docs, applied)
    doc_ledger.save(ledger, ledger_path)
    print("-" * 72)
    print(f"Sync: {stats['nuevos']} nuevos, {stats['modificados']} modificados, "
          f"{stats['borrados']} borrados, {stats['sin_cambios']} sin cambios, "
          f"{stats['errores']} errores.")
    return stats


def main():
    ap = argparse.ArgumentParser(description="Sube una carpeta de documentos a LightRAG.")
    ap.add_argument("carpeta", help="Carpeta con los documentos a indexar")
    ap.add_argument("--url", default=os.environ.get("LIGHTRAG_BASE_URL", "http://localhost:9621"))
    ap.add_argument("--api-key", default=os.environ.get("LIGHTRAG_API_KEY", ""))
    ap.add_argument("--watch", action="store_true",
                    help="monitoriza el indexado en vivo hasta que termine")
    ap.add_argument("--no-exclude", action="store_true",
                    help="no omitir node_modules/.git/build/etc. (sube TODO)")
    ap.add_argument("--sync", action="store_true",
                    help="modo VERSIONADO: salta lo no cambiado y ACTUALIZA (borra+sube) lo "
                         "modificado por hash, con un ledger (no pierde updates ni duplica)")
    ap.add_argument("--ledger", default=os.environ.get("DOCS_LEDGER", "config/docs.json"),
                    help="ruta del ledger de versionado (para --sync)")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    raiz = pathlib.Path(args.carpeta)
    if not raiz.is_dir():
        sys.exit(f"No existe la carpeta: {raiz}")

    ficheros, omitidos = descubrir_ficheros(raiz, excluir=not args.no_exclude)
    total = len(ficheros)
    if not total:
        sys.exit("No encontre documentos con extensiones soportadas.")

    if args.sync:
        print(f"Sincronizando {total} ficheros con {base} (versionado por hash)")
        print("-" * 72)
        _sync_batch(base, args.api_key, ficheros, args.ledger)
        if args.watch:
            with httpx.Client(timeout=300) as client:
                watch_indexado(client, base, headers)
        return

    tam_total = sum(p.stat().st_size for p in ficheros)
    if omitidos:
        print(f"Omitidos {omitidos} ficheros en node_modules/.git/build/etc. "
              f"(usa --no-exclude para incluirlos).")
    print(f"Subiendo {total} ficheros ({fmt_size(tam_total)}) a {base}")
    if not headers:
        print("AVISO: sin API key. Si el servidor exige LIGHTRAG_API_KEY, las "
              "subidas daran 401/403. Pasa --api-key o exporta LIGHTRAG_API_KEY.")
    print("-" * 72)

    ok = fallidos = 0
    track_ids = []
    t0 = time.monotonic()
    with httpx.Client(timeout=300) as client:
        for i, p in enumerate(ficheros, 1):
            size = p.stat().st_size
            try:
                with open(p, "rb") as fh:
                    r = client.post(
                        f"{base}/documents/upload",
                        files={"file": (p.name, fh)},
                        headers=headers,
                    )
                if r.status_code in (200, 201, 202):
                    ok += 1
                    estado = "OK"
                    try:
                        tid = r.json().get("track_id")
                        if tid:
                            track_ids.append(tid)
                    except Exception:
                        pass
                else:
                    fallidos += 1
                    estado = f"HTTP {r.status_code}"
            except Exception as e:
                fallidos += 1
                estado = f"ERROR: {type(e).__name__}"

            transcurrido = time.monotonic() - t0
            pct = i * 100 // total
            eta = (transcurrido / i) * (total - i)
            rel = p.relative_to(raiz)
            print(f"[{i}/{total} {pct:3d}%  ETA {fmt_dur(eta):>6}]  "
                  f"{estado:>9}  {fmt_size(size):>8}  {rel}", flush=True)

        dur = time.monotonic() - t0
        print("-" * 72)
        print(f"Subida terminada en {fmt_dur(dur)}: {ok} aceptados, "
              f"{fallidos} fallidos de {total}.")

        # --- Fase de indexado (asincrona en el servidor) ---
        if args.watch:
            watch_indexado(client, base, headers)
        else:
            counts = status_counts(client, base, headers)
            busy = pipeline_busy(client, base, headers)
            print("\nIndexado (grafo + vectores) en marcha en segundo plano:")
            print(f"  {render_estado(counts, busy)}")
            print("Para seguirlo en vivo:  vuelve a lanzar con  --watch")

    print(f"\nProgreso tambien en la Web UI: {base}/webui   "
          "o con la herramienta MCP  estado_rag.")


if __name__ == "__main__":
    main()
