# GraphRAG local + MCP para Claude Code

Base de conocimiento **GraphRAG 100% local** (LightRAG + Ollama) expuesta a
**Claude Code** mediante un servidor **MCP**. Tus documentos nunca salen de tu
máquina.

```
Tus documentos ──indexar──▶ LightRAG (grafo + vectores + Ollama) ──REST──▶
        servidor MCP (este repo) ──stdio──▶ Claude Code en VS Code
```

El servidor MCP es un puente fino: toda la inteligencia vive en LightRAG. Expone
3 herramientas a Claude Code: `buscar_conocimiento`, `anadir_documento` y
`estado_rag`.

## Estructura

```
.
├── mcp_server.py          # servidor MCP (puente a la API REST de LightRAG)
├── ingest.py              # ingesta en lote de una carpeta
├── lightrag.env.example   # config del servidor LightRAG (afinada 24 GB / CPU)
├── .mcp.json              # config de Claude Code (la rellena setup.sh)
├── setup.sh               # crea venv, instala deps y resuelve rutas absolutas
├── requirements.txt
├── CLAUDE.md              # contexto del proyecto para Claude Code
└── documentos/            # deja aquí tus documentos a indexar
```

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado y corriendo
- VS Code con la extensión de **Claude Code**

## Puesta en marcha

```bash
# 1. Modelos locales (una vez)
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# 2. Servidor LightRAG (en otra terminal, déjalo corriendo)
uv tool install "lightrag-hku[api]"   # o: pip install "lightrag-hku[api]"
cp lightrag.env.example .env
lightrag-server                        # http://localhost:9621/webui

# 3. Indexar tus documentos (mételos en ./documentos)
python ingest.py ./documentos

# 4. Servidor MCP + config de Claude Code
./setup.sh
```

Abre el repo en VS Code con Claude Code y comprueba con `/mcp` que
`graphrag-local` aparece conectado con sus 3 herramientas. Pruébalo:

> Llama a `estado_rag` y dime si la base responde. Luego, según mis documentos,
> ¿qué conecta el módulo de pagos con el de autenticación?

## Memoria (referencia, 24 GB / CPU)

- Indexado con `qwen2.5:7b` a 32k + KV `q8_0`: ~11 GB → cabe con VS Code y
  Claude Code abiertos, con ~6 GB de margen.
- ¿Grafo más fino? Indexa una vez con `qwen2.5:14b` cerrando VS Code; luego
  vuelve a `7b`. Al consultar (`solo_contexto=True`) el modelo local apenas
  trabaja: razona Claude.
- ¿Tienes GPU NVIDIA? La VRAM es aparte: el indexado pasa de minutos y la RAM
  del sistema queda libre. Ajusta `*_BINDING_HOST` si hace falta.

## Ajustes útiles

- `solo_contexto=True` (por defecto): devuelve contexto crudo del grafo para que
  razone Claude. Ponlo a `False` para la respuesta del LLM local.
- Modos: `mix` (recomendado), `hybrid`, `local`, `global`, `naive`.
- Máquina con presión: baja `MAX_ASYNC` y `EMBEDDING_BATCH_NUM` a 1.
- Sube `LIGHTRAG_TIMEOUT` (env del MCP) si las consultas largas se cortan.

## Atajo

Existe el paquete `lightrag-mcp` (`pip install lightrag-mcp`) que hace casi lo
mismo en 3 líneas. Este repo te da el código para que lo entiendas, lo audites
y lo modifiques.

## Licencia

MIT.
