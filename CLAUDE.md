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

# 2. Servidor LightRAG (déjalo corriendo en otra terminal)
uv tool install "lightrag-hku[api]"   # o: pip install "lightrag-hku[api]"
cp lightrag.env.example .env
lightrag-server

# 3. Indexar documentos (carpeta ./documentos o con el script)
python ingest.py ./documentos

# 4. Entorno del servidor MCP
./setup.sh    # crea venv, instala deps y rellena las rutas de .mcp.json
```

El `.mcp.json` de la raíz hace que Claude Code descubra el servidor al abrir
este proyecto. Verifica con `/mcp` que `graphrag-local` aparece conectado.

## Notas

- El indexado es la única fase pesada y es de una vez (puede ir de noche). Las
  consultas son baratas porque el razonamiento lo haces tú, no el modelo local.
- Servidor LightRAG por defecto en `http://localhost:9621` (Web UI en `/webui`,
  Swagger en `/docs`).
- No edites `rag_storage/` a mano; lo gestiona LightRAG.
