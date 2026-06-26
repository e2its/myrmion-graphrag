#!/usr/bin/env python3
"""
Servidor MCP puente entre Claude Code y un servidor LightRAG local.

No reimplementa el GraphRAG: se limita a exponer, mediante el protocolo MCP,
tres herramientas que hablan con la API REST de LightRAG (por defecto en
http://localhost:9621). Toda la inteligencia (grafo de conocimiento, vectores,
modelos) vive en LightRAG + Ollama; este fichero es solo el "mostrador".

Variables de entorno (todas opcionales menos donde se indique):
  LIGHTRAG_BASE_URL   URL del servidor LightRAG (def. http://localhost:9621)
  LIGHTRAG_API_KEY    Clave si configuraste autenticacion en LightRAG (opcional)
  LIGHTRAG_MODE       Modo de busqueda por defecto: mix|hybrid|local|global|naive
  LIGHTRAG_TIMEOUT    Segundos de timeout HTTP (def. 120; el grafo puede tardar)
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("LIGHTRAG_BASE_URL", "http://localhost:9621").rstrip("/")
API_KEY = os.environ.get("LIGHTRAG_API_KEY", "").strip()
DEFAULT_MODE = os.environ.get("LIGHTRAG_MODE", "mix")
TIMEOUT = float(os.environ.get("LIGHTRAG_TIMEOUT", "120"))

VALID_MODES = {"mix", "hybrid", "local", "global", "naive"}

mcp = FastMCP("graphrag-local")


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        # LightRAG acepta la clave por cabecera X-API-Key
        h["X-API-Key"] = API_KEY
    return h


def _post(path: str, payload: dict) -> httpx.Response:
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.post(url, json=payload, headers=_headers())


@mcp.tool()
def buscar_conocimiento(
    consulta: str,
    modo: str = DEFAULT_MODE,
    solo_contexto: bool = True,
    top_k: int = 40,
) -> str:
    """Busca en la base de conocimiento GraphRAG local y devuelve material relevante.

    Usa esta herramienta cuando necesites informacion que viva en los documentos
    indexados del usuario (notas, manuales, codigo, papers, etc.) y que no este
    en tu contexto actual.

    Args:
        consulta: La pregunta o tema a buscar, en lenguaje natural.
        modo: Estrategia de recuperacion. "mix" (recomendado) combina grafo de
            conocimiento y busqueda vectorial. Otros: "hybrid", "local"
            (entidades concretas), "global" (temas amplios), "naive" (solo vectores).
        solo_contexto: Si True (recomendado), devuelve el contexto recuperado
            (entidades, relaciones y fragmentos) para que TU razones sobre el.
            Si False, devuelve la respuesta ya redactada por el LLM local de LightRAG.
        top_k: Numero maximo de elementos a recuperar del grafo/vectores.

    Returns:
        El contexto recuperado o la respuesta generada, como texto.
    """
    modo = modo if modo in VALID_MODES else DEFAULT_MODE
    payload = {
        "query": consulta,
        "mode": modo,
        "only_need_context": bool(solo_contexto),
        "top_k": int(top_k),
    }
    try:
        r = _post("/query", payload)
    except httpx.ConnectError:
        return (
            f"No pude conectar con LightRAG en {BASE_URL}. "
            "Comprueba que el servidor esta arrancado (lightrag-server) "
            "y que el puerto es correcto."
        )
    except httpx.TimeoutException:
        return (
            "La consulta supero el timeout. Con modelos locales pequenos "
            "esto puede pasar; sube LIGHTRAG_TIMEOUT o usa un modo mas ligero "
            "como 'local' o 'naive'."
        )
    if r.status_code != 200:
        return f"LightRAG devolvio HTTP {r.status_code}: {r.text[:500]}"

    data = r.json()
    # La API devuelve {"response": "..."} en versiones recientes; toleramos variantes.
    if isinstance(data, dict):
        for key in ("response", "data", "context", "result"):
            if key in data and data[key]:
                return str(data[key])
        return str(data)
    return str(data)


@mcp.tool()
def anadir_documento(texto: str, descripcion: str = "") -> str:
    """Anade texto a la base de conocimiento (se indexara en el grafo).

    Util para incorporar una nota, un fragmento de codigo o cualquier texto
    sobre la marcha sin tener que tocar la carpeta de documentos. La indexacion
    es asincrona: LightRAG extraera entidades y relaciones en segundo plano.

    Args:
        texto: El contenido a indexar.
        descripcion: Etiqueta o titulo opcional para identificar el documento.
    """
    payload = {"text": texto}
    if descripcion:
        payload["description"] = descripcion
    try:
        r = _post("/documents/text", payload)
    except httpx.ConnectError:
        return f"No pude conectar con LightRAG en {BASE_URL}."
    if r.status_code not in (200, 201, 202):
        return f"LightRAG devolvio HTTP {r.status_code}: {r.text[:500]}"
    return (
        "Documento aceptado. LightRAG lo esta indexando en segundo plano "
        "(extrayendo entidades y relaciones). Tardara unos segundos o minutos "
        "segun el tamano y el modelo local."
    )


@mcp.tool()
def estado_rag() -> str:
    """Comprueba si el servidor LightRAG esta vivo y responde.

    Devuelve el estado de salud y, si esta disponible, la configuracion activa
    (modelos, pipeline). Util como primera llamada para diagnosticar la conexion.
    """
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(f"{BASE_URL}/health", headers=_headers())
    except httpx.ConnectError:
        return (
            f"SIN CONEXION con {BASE_URL}. El servidor LightRAG no responde. "
            "Arrancalo con 'lightrag-server' y vuelve a intentarlo."
        )
    if r.status_code != 200:
        return f"LightRAG respondio pero con HTTP {r.status_code}: {r.text[:300]}"
    return f"LightRAG OK en {BASE_URL}. Detalle: {r.text[:800]}"


if __name__ == "__main__":
    # Transporte stdio: es el que usa Claude Code para servidores locales.
    mcp.run(transport="stdio")
