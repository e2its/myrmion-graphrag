#!/usr/bin/env bash
# Prepara el servidor MCP. Toda la configuracion PERSONAL (rutas, API key,
# modelos) vive en config/ y esta gitignoreada; en la raiz solo se crean los
# enlaces simbolicos .env y .mcp.json que LightRAG y Claude Code esperan ahi.
# Nada personal llega nunca al repo (solo se versionan las plantillas *.example).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$REPO_DIR/venv/bin/python"
CONFIG_DIR="$REPO_DIR/config"
ENV_FILE="$CONFIG_DIR/lightrag.env"
MCP_FILE="$CONFIG_DIR/mcp.json"

echo "==> Creando entorno virtual en $REPO_DIR/venv"
python3 -m venv "$REPO_DIR/venv"

echo "==> Instalando dependencias"
"$REPO_DIR/venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

echo "==> Preparando config/ (tu configuracion personal, fuera del repo)"
mkdir -p "$CONFIG_DIR"
# El .env del servidor LightRAG vive en config/lightrag.env; lo enlazamos a la raiz.
if [ ! -e "$ENV_FILE" ]; then
  cp "$REPO_DIR/lightrag.env.example" "$ENV_FILE"
  echo "    Creado config/lightrag.env desde la plantilla."
  echo "    EDITALO (rutas, LIGHTRAG_API_KEY) y vuelve a ejecutar ./setup.sh."
fi
ln -sfn config/lightrag.env "$REPO_DIR/.env"

echo "==> Leyendo config/lightrag.env para inyectar puerto y API key"
API_KEY="$(grep -E '^LIGHTRAG_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | xargs || true)"
PORT="$(grep -E '^PORT=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | xargs || true)"
PORT="${PORT:-9621}"

echo "==> Generando config/mcp.json y enlazando .mcp.json en la raiz"
cat > "$MCP_FILE" <<JSON
{
  "mcpServers": {
    "graphrag-local": {
      "command": "$PY",
      "args": ["$REPO_DIR/mcp_server.py"],
      "env": {
        "LIGHTRAG_BASE_URL": "http://127.0.0.1:$PORT",
        "LIGHTRAG_MODE": "mix",
        "LIGHTRAG_TIMEOUT": "120",
        "LIGHTRAG_API_KEY": "$API_KEY"
      }
    }
  }
}
JSON
ln -sfn config/mcp.json "$REPO_DIR/.mcp.json"

echo ""
echo "Listo. Siguientes pasos:"
echo "  1) Ollama + modelos:  ollama pull qwen2.5:7b nomic-embed-text"
echo "  2) Config servidor:   edita config/lightrag.env (rutas + LIGHTRAG_API_KEY)"
echo "  3) Re-ejecuta:        ./setup.sh   (reinyecta la API key en config/mcp.json)"
echo "  4) Arranca el server: lightrag-server   (otra terminal, desde la raiz del repo)"
echo "  5) Indexa tu carpeta: $PY ingest.py \"\$INPUT_DIR\" --api-key \"\$LIGHTRAG_API_KEY\""
echo "  6) Abre el repo en VS Code con Claude Code y comprueba /mcp"
