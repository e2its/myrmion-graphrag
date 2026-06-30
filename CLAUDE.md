# CLAUDE.md

Contexto del proyecto para Claude Code.

## Qué es esto

Una base de conocimiento **GraphRAG 100% local** (LightRAG + Ollama) expuesta a
Claude Code mediante un servidor **MCP**. Todo corre en la máquina del usuario;
ningún documento sale al exterior.

Flujo: documentos → LightRAG (grafo + vectores + Ollama) → servidor MCP (`mcp_server.py`) → Claude Code.

## Herramientas MCP disponibles (servidor `graphrag-local`)

Cuando el usuario pregunte por algo que probablemente viva en sus documentos
indexados (notas, manuales, código, papers, decisiones de proyecto…) y no esté
en el contexto de la conversación, usa estas herramientas en lugar de suponer:

- `buscar_conocimiento(consulta, modo="mix", solo_contexto=True, top_k=40)`
  Recupera material relevante del grafo. Con `solo_contexto=True` (por defecto)
  devuelve el contexto crudo (entidades, relaciones, fragmentos) para que **tú**
  razones sobre él, en vez de la respuesta del LLM local pequeño. Úsalo como
  primera opción para preguntas sobre el contenido del usuario.
- `anadir_documento(texto, descripcion="")`
  Indexa un texto nuevo sobre la marcha (asíncrono).
- `estado_rag()`
  Comprueba que el servidor LightRAG responde. Llámalo primero si una búsqueda falla.

Modos de búsqueda: `mix` (recomendado, grafo + vectores), `hybrid`, `local`
(entidades concretas), `global` (temas amplios), `naive` (solo vectores).

## Puesta en marcha

```bash
# 1. Modelos locales (una vez)
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# 2. Entorno del servidor MCP + config personal
./setup.sh    # crea venv, config/ y los enlaces .env / .mcp.json
# edita config/lightrag.env (rutas + LIGHTRAG_API_KEY) y re-ejecuta ./setup.sh

# 3. Servidor LightRAG (déjalo corriendo en otra terminal)
uv tool install "lightrag-hku[api]"   # o: pip install "lightrag-hku[api]"
lightrag-server                        # lee .env -> config/lightrag.env

# 4. Indexar documentos (informa de progreso; --watch sigue el indexado)
python ingest.py "$INPUT_DIR" --api-key "$LIGHTRAG_API_KEY" --watch
```

Toda la config personal (rutas, API key, modelos) vive en `config/`, que está
**gitignoreada**; en la raíz solo hay enlaces `.env -> config/lightrag.env` y
`.mcp.json -> config/mcp.json` (también ignorados). El repo solo versiona las
plantillas `*.example`. El `.mcp.json` de la raíz hace que Claude Code descubra
el servidor al abrir el proyecto. Verifica con `/mcp` que `graphrag-local`
aparece conectado.

## Notas

- El indexado es la única fase pesada y es de una vez (puede ir de noche). Las
  consultas son baratas porque el razonamiento lo haces tú, no el modelo local.
- Servidor LightRAG por defecto en `http://localhost:9621` (Web UI en `/webui`,
  Swagger en `/docs`).
- No edites `rag_storage/` a mano; lo gestiona LightRAG.
