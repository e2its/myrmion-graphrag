#!/usr/bin/env bash
# Prepara el servidor MCP: crea el venv, instala dependencias y genera un
# .mcp.json con las rutas absolutas de ESTA maquina, para que Claude Code lo
# detecte al abrir el proyecto.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$REPO_DIR/venv/bin/python"

echo "==> Creando entorno virtual en $REPO_DIR/venv"
python3 -m venv "$REPO_DIR/venv"

echo "==> Instalando dependencias"
"$REPO_DIR/venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

echo "==> Generando .mcp.json con rutas absolutas"
cat > "$REPO_DIR/.mcp.json" <<JSON
{
  "mcpServers": {
    "graphrag-local": {
      "command": "$PY",
      "args": ["$REPO_DIR/mcp_server.py"],
      "env": {
        "LIGHTRAG_BASE_URL": "http://localhost:9621",
        "LIGHTRAG_MODE": "mix",
        "LIGHTRAG_TIMEOUT": "120"
      }
    }
  }
}
JSON

echo ""
echo "Listo. Siguientes pasos:"
echo "  1) Asegurate de tener Ollama y los modelos (ollama pull qwen2.5:7b nomic-embed-text)"
echo "  2) En otra terminal:  cp lightrag.env.example .env  &&  lightrag-server"
echo "  3) Indexa:            $PY ingest.py ./documentos"
echo "  4) Abre este repo en VS Code con Claude Code y comprueba /mcp"
