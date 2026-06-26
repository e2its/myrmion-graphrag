# GraphRAG local + MCP para Claude Code

> Base de conocimiento **GraphRAG 100% local** (LightRAG + Ollama) conectada a
> **Claude Code** vía **MCP**. Tus documentos nunca salen de tu máquina.

Le das a Claude Code memoria sobre *tus* propios documentos —notas, manuales,
código, papers, decisiones de proyecto— sin enviar nada a la nube y sin claves
de API. Toda la inteligencia corre en tu equipo.

---

## Índice

- [¿Por qué grafo y no un RAG normal?](#por-qué-grafo-y-no-un-rag-normal)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Cómo funciona una consulta](#cómo-funciona-una-consulta)
- [Las tres herramientas MCP](#las-tres-herramientas-mcp)
- [Uso diario](#uso-diario)
- [Indexar documentos](#indexar-documentos)
- [Memoria y rendimiento](#memoria-y-rendimiento)
- [Configuración](#configuración)
- [Modos de búsqueda](#modos-de-búsqueda)
- [Solución de problemas](#solución-de-problemas)
- [FAQ](#faq)
- [Estructura del repo](#estructura-del-repo)
- [Créditos](#créditos)
- [Licencia](#licencia)

---

## ¿Por qué grafo y no un RAG normal?

Un RAG clásico trocea tus documentos, los convierte en vectores y, cuando
preguntas, te trae los *fragmentos más parecidos* a tu pregunta. Funciona bien
para "¿qué dice el documento sobre X?", pero se queda corto cuando lo que
importa son las **conexiones** entre ideas que viven en sitios distintos.

GraphRAG, además de los vectores, construye un **grafo de conocimiento**: al
indexar, un LLM lee tus documentos y extrae *entidades* (conceptos, módulos,
personas, componentes) y las *relaciones* entre ellas. Eso permite responder
preguntas que un RAG normal no puede.

**Ejemplo.** Tienes tres documentos: la spec del módulo de pagos, las notas de
una reunión de seguridad y el changelog de autenticación. Preguntas:

> ¿Qué conecta el módulo de pagos con el sistema de autenticación?

- Un RAG normal te traería trozos que mencionan "pagos" o "autenticación" por
  separado, y tendrías que atar cabos tú.
- GraphRAG recorre las aristas del grafo: pagos → *usa* → tokens JWT → *emitidos
  por* → servicio de auth → *cambió en* → changelog v2.3. Te devuelve esa
  cadena, aunque ningún documento la cuente entera.

La analogía: un RAG normal es un buscador de páginas; GraphRAG es un
bibliotecario que ha leído todo y sabe **cómo se relacionan** las ideas.

---

## Arquitectura

```
Tus documentos ──indexar──▶ LightRAG (grafo + vectores + Ollama) ──REST──▶
        servidor MCP (este repo) ──stdio──▶ Claude Code en VS Code
```

| Pieza | Rol | Dónde corre |
|-------|-----|-------------|
| Ollama | LLM local (extrae entidades) + embeddings | localhost:11434 |
| LightRAG | Grafo de conocimiento + índice vectorial + API REST | localhost:9621 |
| `mcp_server.py` | Puente: traduce MCP ⇄ API REST de LightRAG | proceso local (stdio) |
| Claude Code | Cliente que consume las herramientas | VS Code |

El servidor MCP de este repo es un **puente fino** (~100 líneas): no reimplementa
nada, solo expone las capacidades de LightRAG a Claude Code de forma estándar.

---

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado y en ejecución
- VS Code con la extensión de **Claude Code**
- ~11 GB de RAM libres para indexar con `qwen2.5:7b` (ver [Memoria](#memoria-y-rendimiento))

---

## Instalación

```bash
# 1. Modelos locales (una sola vez)
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# 2. Servidor LightRAG (en otra terminal, déjalo corriendo)
uv tool install "lightrag-hku[api]"   # o: pip install "lightrag-hku[api]"
cp lightrag.env.example .env
lightrag-server                        # Web UI: http://localhost:9621/webui

# 3. Indexar tus documentos (mételos antes en ./documentos)
python ingest.py ./documentos

# 4. Servidor MCP + config de Claude Code
./setup.sh
```

`setup.sh` crea el entorno virtual, instala dependencias y reescribe `.mcp.json`
con las rutas absolutas de tu máquina. Abre el repo en VS Code con Claude Code y
comprueba con `/mcp` que `graphrag-local` aparece conectado con sus 3
herramientas.

---

## Cómo funciona una consulta

El detalle clave del diseño: la herramienta `buscar_conocimiento` viene con
`solo_contexto=True` por defecto.

- **Indexar** (una vez, fase pesada): LightRAG usa el LLM local para extraer
  entidades y relaciones de cada documento. Aquí se construye el grafo.
- **Consultar** (a diario, fase barata): LightRAG *recupera* del grafo el
  contexto relevante (entidades + relaciones + fragmentos) y se lo entrega a
  Claude. El razonamiento lo hace **Claude**, no el modelo local pequeño.

Esto te da lo mejor de los dos mundos: privacidad y coste cero del local para
guardar y recuperar, y la capacidad de razonamiento de Claude para responder.
Si prefieres que conteste el LLM local (sin pasar por Claude), pon
`solo_contexto=False`.

---

## Las tres herramientas MCP

| Herramienta | Qué hace | Parámetros |
|-------------|----------|------------|
| `buscar_conocimiento` | Recupera material relevante del grafo | `consulta`, `modo="mix"`, `solo_contexto=True`, `top_k=40` |
| `anadir_documento` | Indexa un texto nuevo al vuelo (asíncrono) | `texto`, `descripcion=""` |
| `estado_rag` | Comprueba que LightRAG responde | — |

Claude Code decide solo cuándo usarlas (el `CLAUDE.md` se lo explica), pero
también puedes pedírselas de forma explícita.

---

## Uso diario

Pídele a Claude Code en lenguaje natural. Algunos ejemplos:

```
Llama a estado_rag y dime si la base responde.

Según mis documentos, ¿qué decisiones tomamos sobre el sistema de caché?

Busca en mi base de conocimiento cómo se relaciona el módulo de pagos con
el de autenticación, y resúmelo.

Añade esta nota a la base: "El endpoint /v2/orders deja de soportar XML
en marzo; migrar a JSON antes."
```

Como el grafo recupera y Claude razona, las respuestas mejoran cuanto mejor
indexado esté tu material. Reindexa cuando añadas documentos importantes.

---

## Indexar documentos

Tres formas, la que prefieras:

1. **Carpeta vigilada:** deja ficheros en `./documentos` (el `INPUT_DIR` del
   `.env`) y dispara un escaneo desde la Web UI o con `POST /documents/scan`.
2. **Web UI:** arrastra ficheros en `http://localhost:9621/webui` (además
   visualizas el grafo).
3. **Script en lote:** `python ingest.py ./mis_documentos`

Formatos soportados: `.md`, `.txt`, `.pdf`, `.docx`, `.doc`, `.pptx`, `.csv`,
`.rst`, `.html`. La indexación corre en segundo plano; la primera vez tarda
(es donde se construye el grafo), las consultas posteriores son rápidas.

---

## Memoria y rendimiento

Referencia para **24 GB de RAM, Linux, CPU** (sin GPU), con VS Code + Claude
Code abiertos. La cifra que importa no es el peso del modelo, sino la **KV cache
a 32k de contexto** que LightRAG necesita para extraer entidades.

| Modelo | RAM aprox. (indexado a 32k) | Veredicto con 24 GB |
|--------|-----------------------------|---------------------|
| `qwen2.5:3b` | ~7 GB | Sobra; algo menos de calidad en relaciones |
| `qwen2.5:7b` + KV `q8_0` | ~11 GB | **Recomendado**: cómodo con todo abierto |
| `qwen2.5:14b` | ~17 GB | Cabe, pero sin margen junto a las apps |

Trucos para máquinas justas (ya aplicados en `lightrag.env.example`):
`OLLAMA_KV_CACHE_TYPE=q8_0` (corta la KV cache ~a la mitad), `MAX_ASYNC=1` y
`EMBEDDING_BATCH_NUM=1`.

Dos cosas que quitan presión:

- **El indexado es de una vez y puede ir de noche.** Aunque tire algo de swap,
  lo lanzas y por la mañana está. En CPU pura cuenta con ~3-6 tokens/s.
- **Consultar es barato.** Con `solo_contexto=True`, el modelo local apenas
  genera. Puedes indexar una vez con `qwen2.5:14b` (mejor grafo, cerrando
  VS Code) y luego trabajar con `7b`.

**¿Tienes GPU NVIDIA?** La VRAM es aparte de la RAM del sistema: Ollama descarga
el modelo a la tarjeta, el indexado pasa de minutos y la RAM queda libre para
VS Code. Con 8 GB de VRAM entra `7b` holgado; con 12 GB, hasta `14b`.

---

## Configuración

Variables del **servidor LightRAG** (en `.env`, ver `lightrag.env.example`):

| Variable | Por defecto | Para qué |
|----------|-------------|----------|
| `PORT` | 9621 | Puerto del servidor LightRAG |
| `LLM_MODEL` | qwen2.5:7b | Modelo que extrae entidades/relaciones |
| `OLLAMA_LLM_NUM_CTX` | 32768 | Contexto mínimo (crítico, no bajar de 32k) |
| `OLLAMA_KV_CACHE_TYPE` | q8_0 | Cuantización de la KV cache (ahorra RAM) |
| `EMBEDDING_MODEL` | nomic-embed-text | Modelo de embeddings |
| `MAX_ASYNC` | 2 | Llamadas LLM en paralelo |
| `EMBEDDING_BATCH_NUM` | 8 | Tamaño de lote de embeddings |

Variables del **servidor MCP** (en `.mcp.json`, sección `env`):

| Variable | Por defecto | Para qué |
|----------|-------------|----------|
| `LIGHTRAG_BASE_URL` | http://localhost:9621 | URL del servidor LightRAG |
| `LIGHTRAG_MODE` | mix | Modo de búsqueda por defecto |
| `LIGHTRAG_TIMEOUT` | 120 | Timeout HTTP en segundos |
| `LIGHTRAG_API_KEY` | (vacío) | Clave si activaste autenticación en LightRAG |

---

## Modos de búsqueda

Se pasan en `buscar_conocimiento(consulta, modo="...")`:

| Modo | Cuándo usarlo |
|------|---------------|
| `mix` | **Recomendado.** Combina grafo y vectores. |
| `hybrid` | Grafo + vectores, otra estrategia de fusión. |
| `local` | Entidades concretas y sus atributos directos. |
| `global` | Temas amplios, visión de conjunto. |
| `naive` | Solo vectores (RAG clásico, ignora el grafo). |

---

## Solución de problemas

**`No pude conectar con LightRAG en http://localhost:9621`**
El servidor LightRAG no está arrancado. Lánzalo con `lightrag-server` en otra
terminal y comprueba `http://localhost:9621/docs`.

**`context length exceeded` al indexar**
Ollama está usando 8k de contexto en vez de 32k. Asegúrate de tener
`OLLAMA_LLM_NUM_CTX=32768` en el `.env` y reinicia el servidor. Es el fallo
más común.

**Los embeddings dan timeout (CPU)**
Baja `EMBEDDING_BATCH_NUM=1` en el `.env`. Si persiste, usa un modelo de
extracción más pequeño (`qwen2.5:3b`).

**Las consultas largas se cortan por timeout**
Sube `LIGHTRAG_TIMEOUT` en la sección `env` de `.mcp.json` (p. ej. a `300`),
o usa un modo más ligero (`local`, `naive`).

**Claude Code no muestra el servidor en `/mcp`**
Reabre el proyecto tras ejecutar `./setup.sh`. Verifica que `.mcp.json` tiene
rutas absolutas válidas (el `python` del venv y `mcp_server.py`). Llama primero
a `estado_rag` para aislar si el problema es la conexión a LightRAG.

**El grafo no encuentra relaciones que esperabas**
Falta indexado o el modelo de extracción es pequeño. Reindexa, o haz una pasada
con `qwen2.5:14b` para un grafo más rico.

---

## FAQ

**¿De verdad es todo local?** Sí. LightRAG y Ollama corren en tu máquina y el
grafo se guarda en `rag_storage/`. Lo único que sale es lo que Claude Code envía
a Anthropic al razonar tu pregunta (igual que cualquier uso de Claude Code).

**¿Puedo usar Claude para indexar en vez del modelo local?** El razonamiento de
respuesta sí puede ir por Claude (es el modo por defecto). La *extracción* al
indexar usa el LLM local; podrías apuntarla a un proveedor externo, pero
perderías el "100% local".

**¿Cuántos documentos aguanta?** Con almacenamiento en ficheros, miles sin
problema. Para volúmenes grandes, LightRAG soporta Neo4j / PostgreSQL / Milvus
cambiando las variables de almacenamiento.

**¿Tengo que reindexar todo al añadir un documento?** No. La indexación es
incremental: solo se procesa lo nuevo.

**¿Funciona en Windows / Mac?** Sí. En `setup.sh` y rutas, usa el equivalente de
tu sistema (en Windows, la ruta completa al `python.exe` del venv).

---

## Estructura del repo

```
.
├── mcp_server.py          # servidor MCP (puente a la API REST de LightRAG)
├── ingest.py              # ingesta en lote de una carpeta
├── lightrag.env.example   # config del servidor LightRAG (afinada 24 GB / CPU)
├── .mcp.json              # config de Claude Code (la rellena setup.sh)
├── setup.sh               # crea venv, instala deps y resuelve rutas absolutas
├── requirements.txt
├── CLAUDE.md              # contexto del proyecto para Claude Code
├── documentos/            # deja aquí tus documentos a indexar
├── LICENSE
└── README.md
```

---

## Créditos

- [LightRAG](https://github.com/HKUDS/LightRAG) (HKUDS) — el motor GraphRAG.
- [Ollama](https://ollama.com) — modelos locales (LLM y embeddings).
- [Model Context Protocol](https://modelcontextprotocol.io) — el estándar que
  conecta las herramientas con Claude Code.

Atajo: existe el paquete `lightrag-mcp` (`pip install lightrag-mcp`) que hace
algo parecido en 3 líneas. Este repo te da el código para entenderlo, auditarlo
y modificarlo.

---

## Licencia

MIT. Ver [LICENSE](LICENSE).
