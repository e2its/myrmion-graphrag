#!/usr/bin/env bash
# Prepara myrmion-graphRAG (dos servidores MCP + config personal fuera del repo).
# Toda la configuracion PERSONAL (rutas, API key, credenciales de BD, modelos) vive en
# config/ (gitignored); en la raiz solo se crean los enlaces .env y .mcp.json que
# LightRAG y Claude Code esperan ahi. Se versionan SOLO las plantillas *.example.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$REPO_DIR/venv/bin/python"
PIP="$REPO_DIR/venv/bin/pip"
CONFIG_DIR="$REPO_DIR/config"
ENV_FILE="$CONFIG_DIR/lightrag.env"
CB_ENV_FILE="$CONFIG_DIR/codebase.env"
MCP_FILE="$CONFIG_DIR/mcp.json"

echo "==> Creando entorno virtual en $REPO_DIR/venv"
python3 -m venv "$REPO_DIR/venv"

echo "==> Instalando dependencias (MCP LightRAG + servidor de codebase)"
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -r "$REPO_DIR/requirements.txt"
"$PIP" install --quiet -r "$REPO_DIR/requirements-codebase.txt" || \
  echo "    AVISO: no pude instalar requirements-codebase.txt (tree-sitter/neo4j). El servidor de codebase lo necesita."

echo "==> Preparando config/ (tu configuracion personal, fuera del repo)"
mkdir -p "$CONFIG_DIR"
if [ ! -e "$ENV_FILE" ]; then
  cp "$REPO_DIR/lightrag.env.example" "$ENV_FILE"
  echo "    Creado config/lightrag.env desde la plantilla (EDITALO: rutas, API key, perfil de storage)."
fi
if [ ! -e "$CB_ENV_FILE" ]; then
  cp "$REPO_DIR/codebase.env.example" "$CB_ENV_FILE"
  echo "    Creado config/codebase.env desde la plantilla (EDITALO: CODEBASE_ROOT, CODEBASE_STORAGE)."
fi
ln -sfn config/lightrag.env "$REPO_DIR/.env"

# Copia local de los scripts de conveniencia (gitignored)
for s in db-up migrate-backend; do
  if [ ! -e "$REPO_DIR/$s.sh" ]; then cp "$REPO_DIR/$s.sh.example" "$REPO_DIR/$s.sh"; chmod +x "$REPO_DIR/$s.sh"; fi
done

echo "==> Leyendo config para inyectar puerto/API key/rutas"
getcfg() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | xargs || true; }
API_KEY="$(getcfg LIGHTRAG_API_KEY "$ENV_FILE")"
if [ -z "$API_KEY" ]; then
  # Auth ON por defecto: si no hay clave, generamos una aleatoria y la persistimos.
  API_KEY="$(openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  if grep -qE '^LIGHTRAG_API_KEY=' "$ENV_FILE"; then
    sed -i "s|^LIGHTRAG_API_KEY=.*|LIGHTRAG_API_KEY=$API_KEY|" "$ENV_FILE"
  else
    printf '\nLIGHTRAG_API_KEY=%s\n' "$API_KEY" >> "$ENV_FILE"
  fi
  echo "    Generada LIGHTRAG_API_KEY aleatoria en config/lightrag.env (auth ON por defecto)."
fi
PORT="$(getcfg PORT "$ENV_FILE")"; PORT="${PORT:-9621}"
GRAPH_STORAGE="$(getcfg LIGHTRAG_GRAPH_STORAGE "$ENV_FILE")"
CB_ROOT="$(getcfg CODEBASE_ROOT "$CB_ENV_FILE")"; CB_ROOT="${CB_ROOT:-$REPO_DIR}"
CB_STORAGE="$(getcfg CODEBASE_STORAGE "$CB_ENV_FILE")"; CB_STORAGE="${CB_STORAGE:-filesystem}"

echo "==> Generando config/mcp.json (2 servidores) y enlazando .mcp.json"
cat > "$MCP_FILE" <<JSON
{
  "mcpServers": {
    "myrmion-graphrag": {
      "command": "$PY",
      "args": ["$REPO_DIR/mcp_server.py"],
      "env": {
        "LIGHTRAG_BASE_URL": "http://127.0.0.1:$PORT",
        "LIGHTRAG_MODE": "mix",
        "LIGHTRAG_TIMEOUT": "120",
        "LIGHTRAG_API_KEY": "$API_KEY"
      }
    },
    "myrmion-codebase": {
      "command": "$PY",
      "args": ["$REPO_DIR/codebase_server.py"],
      "env": {
        "CODEBASE_ROOT": "$CB_ROOT",
        "CODEBASE_STORAGE": "$CB_STORAGE",
        "CODEBASE_SNAPSHOT": "$REPO_DIR/config/codebase.json"
      }
    }
  }
}
JSON
ln -sfn config/mcp.json "$REPO_DIR/.mcp.json"

echo "==> Activando el git pre-push hook (gate del codebase_inventory en main)"
git -C "$REPO_DIR" config core.hooksPath hooks >/dev/null 2>&1 || true
if [ -f "$REPO_DIR/hooks/pre-push.example" ] && [ ! -e "$REPO_DIR/hooks/pre-push" ]; then
  cp "$REPO_DIR/hooks/pre-push.example" "$REPO_DIR/hooks/pre-push"
fi
chmod +x "$REPO_DIR/hooks/"*.sh "$REPO_DIR/hooks/pre-push" 2>/dev/null || true

# Healthcheck no bloqueante si el perfil usa BD externas
case "$GRAPH_STORAGE" in
  Neo4JStorage) echo "==> Backend Neo4j detectado; validando (no bloqueante)"
                "$PY" -m backends healthcheck neo4j || echo "    AVISO: Neo4j no responde. Levantalo con ./db-up.sh neo4j." ;;
  PG*Storage)   echo "==> Backend Postgres detectado; validando (no bloqueante)"
                "$PY" -m backends healthcheck postgres || echo "    AVISO: Postgres no responde. Levantalo con ./db-up.sh postgres." ;;
esac

echo ""
echo "Listo (myrmion-graphRAG). Siguientes pasos:"
echo "  1) Ollama + modelos:  ollama pull qwen2.5:7b nomic-embed-text"
echo "  2) Backend pro (opc):  ./db-up.sh pro start   # HIBRIDO Neo4j+Postgres"
echo "  3) Edita config/lightrag.env (perfil de storage) y config/codebase.env; re-ejecuta ./setup.sh"
echo "  4) Arranca LightRAG:   lightrag-server   (otra terminal)"
echo "  5) Indexa documentos:  $PY ingest.py \"\$INPUT_DIR\" --api-key \"\$LIGHTRAG_API_KEY\" --watch"
echo "  6) Indexa el codigo:   (desde Claude Code) tool  indexar_codebase"
echo "  7) Abre en VS Code con Claude Code y comprueba /mcp (myrmion-graphrag, myrmion-codebase)"
echo "  8) Tests:              $PY -m pytest    (requiere requirements-dev.txt)"
