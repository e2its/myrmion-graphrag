#!/usr/bin/env python3
"""
Lógica de backends de almacenamiento de LightRAG y de modelos Ollama.

LightRAG usa 4 capas de storage (KV, VECTOR, GRAPH, DOC_STATUS) seleccionables por
variables de entorno. Este módulo concentra toda la lógica *testeable* alrededor de
esa configuración (detección de perfil, validación, generación de bloques de env,
healthcheck de la BD y comprobación del modelo Ollama), de modo que el docker-compose
y los .env queden como thin wrappers.

Perfiles soportados:
  - filesystem : Json/Nano/NetworkX (por defecto, sin BD externa)
  - neo4j      : grafo en Neo4j; KV/vector/estado siguen locales
  - postgres   : todo-en-uno en PostgreSQL (pgvector + Apache AGE)
  - hibrido    : Postgres para KV/vector/estado + Neo4j para el grafo (recomendado pro)

CLI:  python -m backends healthcheck {neo4j|postgres}
"""

from __future__ import annotations

import os
import pathlib
import sys

# Nombre de var -> capa lógica
STORAGE_VARS = {
    "LIGHTRAG_KV_STORAGE": "kv",
    "LIGHTRAG_VECTOR_STORAGE": "vector",
    "LIGHTRAG_GRAPH_STORAGE": "graph",
    "LIGHTRAG_DOC_STATUS_STORAGE": "doc_status",
}

# Firma (kv, vector, graph, doc_status) de cada perfil conocido.
PROFILE_SIGNATURES = {
    "filesystem": (
        "JsonKVStorage",
        "NanoVectorDBStorage",
        "NetworkXStorage",
        "JsonDocStatusStorage",
    ),
    "postgres": (
        "PGKVStorage",
        "PGVectorStorage",
        "PGGraphStorage",
        "PGDocStatusStorage",
    ),
    "neo4j": (
        "JsonKVStorage",
        "NanoVectorDBStorage",
        "Neo4JStorage",
        "JsonDocStatusStorage",
    ),
    "hibrido": (
        "PGKVStorage",
        "PGVectorStorage",
        "Neo4JStorage",
        "PGDocStatusStorage",
    ),
}


def parse_env(text: str) -> dict:
    """Parsea el contenido de un fichero .env a un dict.

    Ignora líneas en blanco y comentarios (`#`), respeta el primer `=` como
    separador y quita comillas envolventes.
    """
    env: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def detect_profile(env: dict) -> str:
    """Devuelve el perfil de storage: filesystem|neo4j|postgres|hibrido|mixed."""
    sig = tuple(
        env.get(var, PROFILE_SIGNATURES["filesystem"][i])
        for i, var in enumerate(STORAGE_VARS)
    )
    for name, ref in PROFILE_SIGNATURES.items():
        if sig == ref:
            return name
    return "mixed"


def _uses_neo4j(env: dict) -> bool:
    return env.get("LIGHTRAG_GRAPH_STORAGE") == "Neo4JStorage"


def _uses_postgres(env: dict) -> bool:
    return any(str(env.get(v, "")).startswith("PG") for v in STORAGE_VARS)


def validate_storage_config(env: dict) -> list:
    """Devuelve una lista de mensajes (errores/avisos) sobre la config de storage."""
    msgs: list[str] = []
    profile = detect_profile(env)

    if _uses_neo4j(env):
        if not env.get("NEO4J_URI"):
            msgs.append("ERROR: backend Neo4j sin NEO4J_URI.")
        if not env.get("NEO4J_PASSWORD"):
            msgs.append("ERROR: backend Neo4j sin NEO4J_PASSWORD.")

    if _uses_postgres(env):
        if not env.get("POSTGRES_HOST"):
            msgs.append("ERROR: backend PostgreSQL sin POSTGRES_HOST.")
        if not env.get("POSTGRES_PASSWORD"):
            msgs.append("ERROR: backend PostgreSQL sin POSTGRES_PASSWORD.")

    if profile == "mixed":
        msgs.append(
            "AVISO: perfil de storage no estandar (mezcla de backends). Revisa las "
            "4 vars LIGHTRAG_*_STORAGE."
        )

    if profile != "filesystem":
        msgs.append(
            "AVISO: cambiar de perfil de storage con documentos ya indexados obliga a "
            "RE-INDEXAR desde cero (LightRAG exige elegir storage antes del primer doc)."
        )

    return msgs


def render_env_block(profile: str, params: dict | None = None) -> str:
    """Genera el bloque de env (líneas LIGHTRAG_*_STORAGE + credenciales) del perfil."""
    params = params or {}
    if profile not in PROFILE_SIGNATURES:
        raise ValueError(f"perfil desconocido: {profile}")
    kv, vector, graph, doc_status = PROFILE_SIGNATURES[profile]
    lines = [
        f"LIGHTRAG_KV_STORAGE={kv}",
        f"LIGHTRAG_VECTOR_STORAGE={vector}",
        f"LIGHTRAG_GRAPH_STORAGE={graph}",
        f"LIGHTRAG_DOC_STATUS_STORAGE={doc_status}",
    ]
    if graph == "Neo4JStorage":
        lines += [
            f"NEO4J_URI={params.get('NEO4J_URI', 'neo4j://localhost:7687')}",
            f"NEO4J_USERNAME={params.get('NEO4J_USERNAME', 'neo4j')}",
            f"NEO4J_PASSWORD={params.get('NEO4J_PASSWORD', 'cambia-esta-clave-neo4j')}",
            f"NEO4J_DATABASE={params.get('NEO4J_DATABASE', 'neo4j')}",
        ]
    if kv.startswith("PG") or vector.startswith("PG") or doc_status.startswith("PG"):
        lines += [
            f"POSTGRES_HOST={params.get('POSTGRES_HOST', 'localhost')}",
            f"POSTGRES_PORT={params.get('POSTGRES_PORT', '5432')}",
            f"POSTGRES_USER={params.get('POSTGRES_USER', 'rag')}",
            f"POSTGRES_PASSWORD={params.get('POSTGRES_PASSWORD', 'cambia-esta-clave-postgres')}",
            f"POSTGRES_DATABASE={params.get('POSTGRES_DATABASE', 'lightrag')}",
        ]
    return "\n".join(lines) + "\n"


def parse_health_config(health_json: dict) -> dict:
    """Extrae el storage activo de la respuesta de `GET /health` de LightRAG.

    Tolera variantes: la info puede venir bajo "configuration" o en la raíz. Devuelve
    un dict {campo_storage: valor} (vacío si no hay info; degradación elegante).
    """
    if not isinstance(health_json, dict):
        return {}
    conf = health_json.get("configuration")
    if not isinstance(conf, dict):
        conf = health_json
    out: dict[str, str] = {}
    for key, value in conf.items():
        kl = str(key).lower()
        if "storage" in kl and isinstance(value, (str, int, float)):
            out[kl] = str(value)
    return out


# --- healthcheck de la base de datos ---------------------------------------
def _ping_neo4j(env: dict) -> None:  # pragma: no cover - I/O real, cubierto por integración
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        env.get("NEO4J_URI", "neo4j://localhost:7687"),
        auth=(env.get("NEO4J_USERNAME", "neo4j"), env.get("NEO4J_PASSWORD", "")),
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


def _ping_postgres(env: dict) -> None:  # pragma: no cover - I/O real, cubierto por integración
    import psycopg

    conn = psycopg.connect(
        host=env.get("POSTGRES_HOST", "localhost"),
        port=env.get("POSTGRES_PORT", "5432"),
        user=env.get("POSTGRES_USER", "rag"),
        password=env.get("POSTGRES_PASSWORD", ""),
        dbname=env.get("POSTGRES_DATABASE", "lightrag"),
        connect_timeout=5,
    )
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()


def healthcheck(backend: str, env: dict) -> tuple:
    """Comprueba la conexión al backend. Devuelve (ok, mensaje).

    El acceso real al driver está aislado en `_ping_*`; los tests los mockean para
    ejercitar la clasificación de errores sin necesidad de una BD real.
    """
    ping = {"neo4j": _ping_neo4j, "postgres": _ping_postgres}.get(backend)
    if ping is None:
        return (False, f"backend desconocido: {backend}")
    try:
        ping(env)
        return (True, f"{backend} responde correctamente.")
    except ImportError:
        return (
            False,
            "Driver no instalado. Instala los drivers de BD: "
            "pip install -r requirements-backends.txt",
        )
    except Exception as e:  # noqa: BLE001 - clasificamos por nombre de tipo
        name = type(e).__name__
        if "Auth" in name:
            return (False, f"{backend}: credenciales invalidas ({name}).")
        if any(t in name for t in ("ServiceUnavailable", "Connection", "Operational")):
            return (
                False,
                f"{backend} no responde. Levantalo con ./db-up.sh {backend}.",
            )
        return (False, f"Fallo de {backend}: {name}: {e}")


# --- modelos Ollama ---------------------------------------------------------
def render_model_block(tier: str) -> str:
    """Genera el bloque de env del perfil de modelo (local|profesional)."""
    if tier == "local":
        return (
            "LLM_MODEL=qwen2.5:7b\n"
            "OLLAMA_LLM_NUM_CTX=8192\n"
            "MAX_ASYNC=1\n"
            "EMBEDDING_MODEL=nomic-embed-text\n"
            "EMBEDDING_DIM=768\n"
        )
    if tier in ("profesional", "pro"):
        return (
            "LLM_MODEL=qwen2.5:32b\n"
            "OLLAMA_LLM_NUM_CTX=32768\n"
            "MAX_ASYNC=4\n"
            "EMBEDDING_MODEL=nomic-embed-text\n"
            "EMBEDDING_DIM=768\n"
        )
    raise ValueError(f"tier de modelo desconocido: {tier}")


def check_ollama_model(env: dict) -> tuple:
    """Comprueba si el LLM_MODEL configurado está descargado en Ollama.

    Consulta GET {LLM_BINDING_HOST}/api/tags. Devuelve (ok, mensaje).
    """
    import httpx

    host = str(env.get("LLM_BINDING_HOST", "http://localhost:11434")).rstrip("/")
    modelo = env.get("LLM_MODEL", "")
    if not modelo:
        return (False, "No hay LLM_MODEL configurado.")
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{host}/api/tags")
    except httpx.HTTPError:
        return (False, f"Ollama no responde en {host}. Arranca 'ollama serve'.")
    if r.status_code != 200:
        return (False, f"Ollama devolvio HTTP {r.status_code}.")
    try:
        modelos = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return (False, "Respuesta de Ollama no parseable.")
    base = modelo.split(":")[0]
    for name in modelos:
        if name == modelo or name.split(":")[0] == base:
            return (True, f"Modelo '{modelo}' disponible en Ollama.")
    return (
        False,
        f"Modelo '{modelo}' NO descargado. Ejecuta: ollama pull {modelo}",
    )


def _load_env() -> dict:
    """Carga config/lightrag.env (si existe) sobre os.environ para la CLI."""
    env = dict(os.environ)
    cfg = pathlib.Path(__file__).resolve().parent / "config" / "lightrag.env"
    if cfg.exists():
        env.update(parse_env(cfg.read_text(encoding="utf-8", errors="replace")))
    return env


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "healthcheck":
        ok, msg = healthcheck(argv[1], _load_env())
        print(msg)
        return 0 if ok else 1
    print("Uso: python -m backends healthcheck {neo4j|postgres}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
