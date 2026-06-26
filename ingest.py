#!/usr/bin/env python3
"""
Ingesta en lote: sube todos los documentos de una carpeta al servidor LightRAG.

Alternativa mas simple: deja los ficheros en la carpeta INPUT_DIR del .env y
llama a POST /documents/scan (o usa la Web UI en http://localhost:9621). Este
script es comodo para cargas puntuales desde cualquier carpeta.

Uso:
    python ingest.py ./mis_documentos
    python ingest.py ./mis_documentos --url http://localhost:9621
"""

import argparse
import pathlib
import sys
import httpx

EXTS = {".md", ".txt", ".pdf", ".docx", ".doc", ".pptx", ".csv", ".rst", ".html"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta", help="Carpeta con los documentos a indexar")
    ap.add_argument("--url", default="http://localhost:9621")
    ap.add_argument("--api-key", default="")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    raiz = pathlib.Path(args.carpeta)
    if not raiz.is_dir():
        sys.exit(f"No existe la carpeta: {raiz}")

    ficheros = [p for p in raiz.rglob("*") if p.is_file() and p.suffix.lower() in EXTS]
    if not ficheros:
        sys.exit("No encontre documentos con extensiones soportadas.")

    print(f"Subiendo {len(ficheros)} ficheros a {base} ...")
    ok = 0
    with httpx.Client(timeout=300) as client:
        for p in ficheros:
            try:
                with open(p, "rb") as fh:
                    r = client.post(
                        f"{base}/documents/upload",
                        files={"file": (p.name, fh)},
                        headers=headers,
                    )
                estado = "OK" if r.status_code in (200, 201, 202) else f"HTTP {r.status_code}"
                if r.status_code in (200, 201, 202):
                    ok += 1
                print(f"  [{estado}] {p.relative_to(raiz)}")
            except Exception as e:
                print(f"  [ERROR] {p.name}: {e}")

    print(f"\nAceptados {ok}/{len(ficheros)}. La indexacion (grafo + vectores) "
          "continua en segundo plano en el servidor. Mira el progreso en la "
          "Web UI: " + base + "/webui  o con la herramienta estado_rag.")


if __name__ == "__main__":
    main()
