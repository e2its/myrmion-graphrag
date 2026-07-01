#!/usr/bin/env python3
"""
Servidor MCP puente entre Claude Code y un servidor LightRAG local.

No reimplementa el GraphRAG: se limita a exponer, mediante el protocolo MCP,
herramientas que hablan con la API REST de LightRAG (por defecto en
http://localhost:9621). Toda la inteligencia (grafo de conocimiento, vectores,
modelos) vive en LightRAG + Ollama; este fichero es solo el "mostrador".

La lógica HTTP vive en la clase fina `LightRAGClient` (inyectable y testeable);
las herramientas `@mcp.tool()` son wrappers delgados sobre un cliente por defecto.

Variables de entorno (todas opcionales menos donde se indique):
  LIGHTRAG_BASE_URL   URL del servidor LightRAG (def. http://localhost:9621)
  LIGHTRAG_API_KEY    Clave si configuraste autenticacion en LightRAG (opcional)
  LIGHTRAG_MODE       Modo de busqueda por defecto: mix|hybrid|local|global|naive
  LIGHTRAG_TIMEOUT    Segundos de timeout HTTP (def. 120; el grafo puede tardar)
"""

import hashlib
import os
import pathlib

import httpx
from mcp.server.fastmcp import FastMCP

VALID_MODES = {"mix", "hybrid", "local", "global", "naive"}


class LightRAGClient:
    """Cliente HTTP fino contra la API REST de LightRAG.

    Encapsula toda la I/O para que las herramientas MCP queden como wrappers
    delgados y para poder testear cada caso (OK, timeouts, errores) con mocks.
    """

    def __init__(self, base_url, api_key="", default_mode="mix", timeout=120.0):
        self.base_url = str(base_url).rstrip("/")
        self.api_key = (api_key or "").strip()
        self.default_mode = default_mode if default_mode in VALID_MODES else "mix"
        self.timeout = float(timeout)

    # --- primitivas HTTP ---------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            # LightRAG acepta la clave por cabecera X-API-Key
            h["X-API-Key"] = self.api_key
        return h

    def _post(self, path: str, payload: dict, timeout=None) -> httpx.Response:
        with httpx.Client(timeout=timeout or self.timeout) as client:
            return client.post(
                f"{self.base_url}{path}", json=payload, headers=self._headers()
            )

    def _get(self, path: str, timeout=None) -> httpx.Response:
        with httpx.Client(timeout=timeout or self.timeout) as client:
            return client.get(f"{self.base_url}{path}", headers=self._headers())

    # --- operaciones de alto nivel (devuelven texto legible) ---------------
    def query(self, consulta, modo=None, solo_contexto=True, top_k=40) -> str:
        modo = modo if modo in VALID_MODES else self.default_mode
        payload = {
            "query": consulta,
            "mode": modo,
            "only_need_context": bool(solo_contexto),
            "top_k": int(top_k),
        }
        try:
            r = self._post("/query", payload)
        except httpx.ConnectError:
            return (
                f"No pude conectar con LightRAG en {self.base_url}. "
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

    def add_text(self, texto, descripcion="") -> str:
        payload = {"text": texto}
        if descripcion:
            payload["description"] = descripcion
        try:
            r = self._post("/documents/text", payload)
        except httpx.ConnectError:
            return f"No pude conectar con LightRAG en {self.base_url}."
        if r.status_code not in (200, 201, 202):
            return f"LightRAG devolvio HTTP {r.status_code}: {r.text[:500]}"
        return (
            "Documento aceptado. LightRAG lo esta indexando en segundo plano "
            "(extrayendo entidades y relaciones). Tardara unos segundos o minutos "
            "segun el tamano y el modelo local."
        )

    def health(self) -> str:
        try:
            r = self._get("/health", timeout=15)
        except httpx.ConnectError:
            return (
                f"SIN CONEXION con {self.base_url}. El servidor LightRAG no responde. "
                "Arrancalo con 'lightrag-server' y vuelve a intentarlo."
            )
        if r.status_code != 200:
            return f"LightRAG respondio pero con HTTP {r.status_code}: {r.text[:300]}"

        backend = ""
        try:
            data = r.json()
            if isinstance(data, dict):
                from backends import parse_health_config

                storages = parse_health_config(data)
                if storages:
                    backend = ", ".join(f"{k}={v}" for k, v in sorted(storages.items()))
        except Exception:
            backend = ""

        cabecera = f"LightRAG OK en {self.base_url}."
        if backend:
            cabecera += f" Backend activo: {backend}."
        return f"{cabecera} Detalle: {r.text[:800]}"

    # --- sincronización idempotente de documentos --------------------------
    def find_doc_by_path(self, ruta) -> str | None:
        """Devuelve el doc_id cuyo file_path coincide (por basename) con `ruta`, o None."""
        base = pathlib.Path(str(ruta)).name.lower()
        try:
            r = self._get("/documents")
        except httpx.ConnectError:
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except Exception:
            return None
        statuses = data.get("statuses") if isinstance(data, dict) else None
        if not isinstance(statuses, dict):
            return None
        for docs in statuses.values():
            if not isinstance(docs, list):
                continue
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                fp = doc.get("file_path") or doc.get("file_source") or ""
                if pathlib.Path(str(fp)).name.lower() == base:
                    return doc.get("id") or doc.get("doc_id")
        return None

    def delete_document(self, doc_id) -> httpx.Response:
        return self._post("/documents/delete_document", {"doc_ids": [doc_id]})

    def upsert_document(self, ruta, texto) -> str:
        """Actualiza un documento SIN duplicar: borra la versión previa (si existe)
        por su ruta y reinserta el texto con file_source=ruta.

        LightRAG deduplica por nombre de fichero y ARCHIVA los duplicados en vez de
        actualizar, así que la única vía de "update" es delete + insert.
        """
        try:
            doc_id = self.find_doc_by_path(ruta)
            if doc_id:
                self.delete_document(doc_id)
            r = self._post(
                "/documents/text", {"text": texto, "file_source": str(ruta)}
            )
        except httpx.ConnectError:
            return f"No pude conectar con LightRAG en {self.base_url}."
        except httpx.TimeoutException:
            return "La sincronizacion del documento supero el timeout; reintentalo."
        if r.status_code not in (200, 201, 202):
            return f"LightRAG devolvio HTTP {r.status_code}: {r.text[:500]}"
        accion = "reemplazado" if doc_id else "insertado"
        return f"Documento {accion} sin duplicar (file_source={ruta}). Reindexando en 2o plano."


def _default_client() -> LightRAGClient:
    return LightRAGClient(
        base_url=os.environ.get("LIGHTRAG_BASE_URL", "http://localhost:9621"),
        api_key=os.environ.get("LIGHTRAG_API_KEY", ""),
        default_mode=os.environ.get("LIGHTRAG_MODE", "mix"),
        timeout=float(os.environ.get("LIGHTRAG_TIMEOUT", "120")),
    )


mcp = FastMCP("myrmion-graphrag")


@mcp.tool()
def buscar_conocimiento(
    consulta: str,
    modo: str = "mix",
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
    return _default_client().query(consulta, modo, solo_contexto, top_k)


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
    return _default_client().add_text(texto, descripcion)


@mcp.tool()
def sincronizar_documento(ruta: str, texto: str = "") -> str:
    """Actualiza en el grafo un documento tras editarlo, SIN generar duplicados.

    Localiza la version anterior por su ruta, la borra y reinserta el contenido
    nuevo (delete + insert), que es la unica via de "update" soportada por
    LightRAG (deduplica por nombre de fichero y archiva los duplicados).

    Args:
        ruta: Ruta del fichero (se usa como file_source / clave de deduplicacion).
        texto: Contenido nuevo. Si se omite, se lee del fichero en `ruta`.
    """
    contenido = texto
    if not contenido:
        try:
            contenido = pathlib.Path(ruta).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"No pude leer {ruta}: {type(e).__name__}."
    return _default_client().upsert_document(ruta, contenido)


@mcp.tool()
def estado_rag() -> str:
    """Comprueba si el servidor LightRAG esta vivo y responde.

    Devuelve el estado de salud y, si esta disponible, el backend de almacenamiento
    activo (filesystem / Neo4j / PostgreSQL) y la configuracion. Util como primera
    llamada para diagnosticar la conexion.
    """
    return _default_client().health()


@mcp.tool()
def verificar_alineacion() -> str:
    """Comprueba que Neo4j (grafo) y Postgres (vectores) del perfil HÍBRIDO estén alineados.

    Solo aplica al backend híbrido. Reporta la deriva (docs sin grafo/sin vectores, huérfanos)
    sin modificar nada. Usa `reconciliar` para repararla.
    """
    try:
        from consistency_readers import build_supervisor  # pragma: no cover
    except Exception as e:  # noqa: BLE001
        return f"No pude preparar la verificacion: {type(e).__name__}: {e}"
    try:
        sup = build_supervisor()  # pragma: no cover
        return str(sup.reconcile(apply=False))  # pragma: no cover
    except Exception as e:  # noqa: BLE001
        return f"Verificacion no disponible: {type(e).__name__}: {e}"


@mcp.tool()
def reconciliar(aplicar: bool = False) -> str:
    """Reconcilia Neo4j y Postgres del perfil HÍBRIDO (saga + reparación auto).

    Args:
        aplicar: Si False (por defecto) es un dry-run que solo reporta el plan. Si True,
            ejecuta la reparación (reindexar docs con deriva, borrar huérfanos).
    """
    try:
        from consistency_readers import build_supervisor  # pragma: no cover
    except Exception as e:  # noqa: BLE001
        return f"No pude preparar la reconciliacion: {type(e).__name__}: {e}"
    try:
        sup = build_supervisor()  # pragma: no cover
        return str(sup.reconcile(apply=bool(aplicar)))  # pragma: no cover
    except Exception as e:  # noqa: BLE001
        return f"Reconciliacion no disponible: {type(e).__name__}: {e}"


# Hash de contenido reutilizable por herramientas de sincronización externas.
def content_md5(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8", errors="replace")).hexdigest()


if __name__ == "__main__":
    # Transporte stdio: es el que usa Claude Code para servidores locales.
    mcp.run(transport="stdio")
