#!/usr/bin/env bash
# Hook PostToolUse de Claude Code (matcher Edit|Write|MultiEdit): mantiene CALIENTE el
# overlay de sesión del codebase_inventory tras cada edición. Lee el JSON del hook por
# stdin, extrae la ruta editada y sincroniza en modo --overlay (nunca toca el durable).
# No falla la operación del usuario si algo va mal (exit 0 siempre).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO_DIR/venv/bin/python"

FILE="$("$PY" - <<'PYEOF'
import json, sys
try:
    data = json.load(sys.stdin)
    ti = data.get("tool_input", {}) or {}
    print(ti.get("file_path") or ti.get("path") or "")
except Exception:
    print("")
PYEOF
)"

[ -n "$FILE" ] || exit 0
CODEBASE_STORAGE="${CODEBASE_STORAGE:-memory}" "$PY" -m codebase_mcp.sync --overlay "$FILE" >/dev/null 2>&1 || true
exit 0
