<p align="center">
  <img src="https://raw.githubusercontent.com/e2its/myrmion-framework/main/assets/myrmion-logo.png" alt="Myrmion" width="140">
</p>

<h1 align="center">Myrmion graphRAG</h1>

<p align="center"><i>Memoria 100% local para Claude Code — GraphRAG de tus documentos y grafo de tu código, vía MCP. Sin nube, sin claves de API.</i></p>

<p align="center">
  <a href="#licencia"><img src="https://img.shields.io/badge/license-MIT-1D9E75" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/Claude_Code-MCP_server-378ADD" alt="Claude Code MCP server">
  <img src="https://img.shields.io/badge/engine-LightRAG_%2B_Ollama-7F77DD" alt="LightRAG + Ollama">
  <img src="https://img.shields.io/badge/parser-tree--sitter-444" alt="tree-sitter">
  <img src="https://img.shields.io/badge/storage-Neo4j_%C2%B7_PostgreSQL-444" alt="Neo4j / PostgreSQL">
  <img src="https://img.shields.io/badge/100%25-local-444" alt="100% local">
  <a href="https://github.com/e2its/myrmion-framework"><img src="https://img.shields.io/badge/Myrmion-ecosystem-1b3a5c" alt="Myrmion ecosystem"></a>
</p>

<p align="center">
  <b>Dos servidores MCP locales: <code>myrmion-graphrag</code> (documentos) y <code>myrmion-codebase</code> (código).</b>
</p>

---

## Parte del ecosistema Myrmion

[Myrmion](https://github.com/e2its/myrmion-framework) es un ecosistema opensource para
adoptar IA corporativa con cultura propia. **Myrmion graphRAG** es una de sus **herramientas**:
da a Claude Code memoria local sobre *tus documentos* y *tu código* sin que nada salga de tu
máquina. Se usa **por sí sola**, sin requerir el resto del ecosistema.

Dos memorias locales, expuestas como dos servidores MCP:

- **`myrmion-graphrag`** — grafo de conocimiento sobre *tus documentos* (notas, manuales,
  papers, decisiones). Motor: LightRAG + Ollama.
- **`myrmion-codebase`** — grafo de *tu código*: dependencias, "¿a qué afecta esta función?",
  "¿quién llama a X?", inventario (reutilizable / obligatoria / muerta) e histórico. Parser
  multi-lenguaje (Python vía `ast`; JS/TS, Java, C# y VB.NET vía tree-sitter; VB6/VBScript y
  ASP clásico con parser propio).

Todo corre en tu equipo, sin claves de API para el indexado. Solo sale lo que Claude Code
envía a Anthropic al razonar tu pregunta.

> Otras piezas del ecosistema: [myrmion-blackbar-pii-guard](https://github.com/e2its/myrmion-blackbar-pii-guard)
> (redacción de PII para Claude) · [myrmion-AI-factory](https://github.com/e2its/myrmion-AI-factory)
> (SDLC agéntico gobernado) · [myrmion-framework](https://github.com/e2its/myrmion-framework) (el paraguas).

---

## Índice

- [Parte del ecosistema Myrmion](#parte-del-ecosistema-myrmion)

- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación y conexionado](#instalación-y-conexionado)
- [Backends de almacenamiento (filesystem / Neo4j / PostgreSQL / híbrido)](#backends-de-almacenamiento)
- [Consistencia del híbrido (saga + reconciliación)](#consistencia-del-híbrido)
- [Perfiles de modelo (local vs profesional)](#perfiles-de-modelo)
- [Parametrizar según tu hardware (CPU/RAM/GPU/modelo)](#parametrizar-según-tu-hardware)
- [Herramientas MCP](#herramientas-mcp)
- [Lenguajes y parsers cubiertos](#lenguajes-y-parsers-cubiertos)
- [Mantenimiento automático del codebase_inventory](#mantenimiento-automático-del-codebase_inventory)
- [Sincronización incremental sin duplicados](#sincronización-incremental-sin-duplicados)
- [Versionado de documentos](#versionado-de-documentos)
- [Tests](#tests)
- [Estructura del repo](#estructura-del-repo)
- [Referencias / créditos](#referencias--créditos)
- [Licencia](#licencia)

---

## Arquitectura

```
                         Claude Code (VS Code) ── cliente MCP
                           │ stdio            │ stdio
            ┌──────────────▼───────┐   ┌──────▼────────────────┐
            │  myrmion-graphrag    │   │  myrmion-codebase     │
            │  mcp_server.py       │   │  codebase_server.py   │
            │  (documentos)        │   │  (código)             │
            └──────────┬───────────┘   └──────┬────────────────┘
               HTTP :9621                GraphStore pluggable
            ┌──────────▼───────────┐   ┌──────▼────────────────────────────┐
            │  lightrag-server     │   │ filesystem(def) │ neo4j │ postgres │
            │  storage PLUGGABLE:  │   └────────────────────────────────────┘
            │  filesystem/neo4j/pg │
            │  /híbrido            │
            └──────────────────────┘
```

> **`def` = backend por defecto.** Ambos servidores usan el mismo trío
> `filesystem / neo4j / postgres`. Para el grafo de código, `filesystem` persiste el grafo en
> un JSON en `config/` (sin BD externa, como el filesystem de LightRAG); `neo4j`/`postgres`
> son las opciones profesionales.

| Pieza | Rol | Dónde corre |
|-------|-----|-------------|
| Ollama | LLM local (extrae entidades) + embeddings | localhost:11434 |
| LightRAG | Grafo de conocimiento + índice vectorial + API REST | localhost:9621 |
| `mcp_server.py` | Servidor MCP de documentos (puente a LightRAG) | proceso local (stdio) |
| `codebase_server.py` | Servidor MCP de código (parser + grafo propio) | proceso local (stdio) |
| Neo4j / PostgreSQL | Backends profesionales (opcionales) | Docker `127.0.0.1` |

---

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado y en ejecución
- VS Code con la extensión de **Claude Code**
- ~11 GB de RAM libres para indexar documentos con `qwen2.5:7b`
- (Opcional, para backends profesionales) Docker + Docker Compose

---

## Instalación y conexionado

### 1. Modelos locales (una vez)

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 2. Setup del proyecto

```bash
./setup.sh
```

`setup.sh` crea el venv, instala dependencias (`requirements.txt` + `requirements-codebase.txt`),
crea tu config personal en `config/` (desde las plantillas `*.example`), genera
`config/mcp.json` con **los dos servidores** y sus rutas absolutas, crea los enlaces
`.env` y `.mcp.json` en la raíz, copia los scripts locales (`db-up.sh`, `migrate-backend.sh`)
y **activa el git `pre-push` hook** del inventario.

Toda tu configuración personal vive en **`config/`** (gitignored); el repo solo versiona
las plantillas. Edita `config/lightrag.env` (rutas, API key, perfil de storage) y
`config/codebase.env` (raíz del código, backend), y **re-ejecuta `./setup.sh`**.

### 3. Servidor LightRAG (documentos)

```bash
uv tool install "lightrag-hku[api]"   # o: pip install "lightrag-hku[api]"
lightrag-server                        # otra terminal; lee .env -> config/lightrag.env
```

### 4. Indexar

```bash
# Documentos -> myrmion-graphrag
python ingest.py "$INPUT_DIR" --api-key "$LIGHTRAG_API_KEY" --watch

# Código -> myrmion-codebase  (desde Claude Code: tool  indexar_codebase )
```

### 5. Conectar Claude Code

Abre el repo en VS Code con Claude Code. El `.mcp.json` de la raíz hace que Claude Code
descubra **ambos** servidores. Verifica con `/mcp` que aparecen conectados:
**`myrmion-graphrag`** y **`myrmion-codebase`**. Llama a `estado_rag` y a
`estado_indexado` para diagnosticar cada uno.

> El servidor `myrmion-codebase` puede apuntar a **cualquier** codebase: pon su ruta en
> `CODEBASE_ROOT` (en `config/codebase.env`) y re-ejecuta `./setup.sh`.

---

## Backends de almacenamiento

LightRAG usa 4 capas de storage (KV, Vector, Grafo, DocStatus). Eliges **un perfil** en
`config/lightrag.env` (bloque de almacenamiento). **Caveat**: el storage debe elegirse
**antes** de indexar el primer documento; cambiarlo obliga a **re-indexar** (usa
`./migrate-backend.sh`).

| Perfil | Qué usa | Cuándo |
|--------|---------|--------|
| **A · filesystem** (def.) | Json / Nano / NetworkX | Empezar, corpus pequeño/medio, 100% sin BD |
| **B · neo4j** | Neo4j (grafo) + resto local | Quieres visualizar/consultar el grafo con Cypher |
| **C · postgres** | PostgreSQL todo-en-uno (pgvector + AGE) | Unificación y garantía transaccional máxima |
| **D · híbrido** *(recomendado pro)* | Postgres (KV/vector/estado) + Neo4j (grafo) | pgvector escalable **y** grafo nativo/visual |

Levanta los backends con Docker (bind a `127.0.0.1`, nada sale de tu máquina):

```bash
./db-up.sh neo4j start        # Neo4j en :7474 (browser) / :7687 (bolt)
./db-up.sh postgres start     # Postgres en :5432
./db-up.sh pro start          # HÍBRIDO: ambos a la vez
```

Valida la conexión y qué backend está activo:

```bash
python -m backends healthcheck neo4j     # o postgres
# y desde Claude Code:  estado_rag   (reporta el backend activo)
```

**El inventario de código** (`myrmion-codebase`) usa su propio `GraphStore` pluggable con el
mismo trío: `filesystem` (por defecto, grafo persistido en un JSON en `config/`, sin BD),
`neo4j` (recomendado para uso pro; puede reutilizar la instancia de LightRAG) o `postgres`.

---

## Consistencia del híbrido

El perfil híbrido escribe el grafo en Neo4j y los vectores/KV/estado en Postgres: **dos
bases de datos sin transacción distribuida**. Para que **nunca queden desalineadas**,
`myrmion-graphrag` incluye un **supervisor de consistencia** (`consistency.py`):

- **Health-gate**: no se escribe salvo que Neo4j **y** Postgres **y** LightRAG respondan.
- **Saga con reintentos automáticos + compensación**: cada operación de documento es una
  saga de pasos idempotentes; si un paso agota reintentos, se compensan los previos.
- **Reconciliación**: detecta deriva (docs sin grafo/sin vectores, huérfanos) y la repara
  (reindexar / borrar huérfanos).

Tools MCP (solo aplican al híbrido): **`verificar_alineacion`** (dry-run) y
**`reconciliar(aplicar=True)`** (repara).

> Compromiso honesto: es **consistencia fuerte auto-reparable** (se detecta y repara toda
> deriva), no un candado 2PC instantáneo. Si necesitas una garantía transaccional dura sin
> reconciliación, usa el **Perfil C** (Postgres todo-en-uno: una sola transacción ACID).
> El inventario de código va en Neo4j (grafo puro, un solo store → sin deriva posible).

---

## Perfiles de modelo

Los backends profesionales suelen correr en hardware potente, donde interesa un Qwen mayor
para maximizar la extracción y la fiabilidad. En `config/lightrag.env` hay presets:

| Perfil | LLM | Contexto / paralelismo | Hardware |
|--------|-----|------------------------|----------|
| **local** (def.) | `qwen2.5:7b` | `NUM_CTX=8192`, `MAX_ASYNC=1` | CPU / 24 GB |
| **profesional** | `qwen2.5:32b` (o `:14b`/`:72b`, `qwen3:*`) | `NUM_CTX=32768`, `MAX_ASYNC=4` | GPU / mucha RAM |

**Regla crítica:** cambiar `LLM_MODEL` **no** obliga a reindexar; cambiar
`EMBEDDING_MODEL`/`EMBEDDING_DIM` **sí** (la dimensión del vector cambia). Descarga el
modelo con `ollama pull qwen2.5:32b`.

---

## Parametrizar según tu hardware

Ajusta `config/lightrag.env` según CPU/RAM/GPU. Referencia (Q4): `7b≈6GB`, `14b≈10GB`,
`32b≈20GB`, `72b≈48GB` de VRAM/RAM.

| Escenario | `LLM_MODEL` | `NUM_CTX` | `MAX_ASYNC` | `EMBEDDING_BATCH_NUM` | Timeouts | KV cache |
|-----------|-------------|-----------|-------------|-----------------------|----------|----------|
| CPU-only 16 GB | `qwen2.5:3b` | 8192 | 1 | 1 | altos | `q8_0` |
| CPU-only 24-32 GB | `qwen2.5:7b` | 8192 | 1 | 4 | altos | `q8_0` |
| GPU 8-12 GB VRAM | `qwen2.5:7b`/`14b` | 16384 | 2 | 8 | medios | `q8_0` |
| GPU 24 GB | `qwen2.5:32b` | 32768 | 4 | 16 | bajos | `f16` |
| GPU 48 GB+ | `qwen2.5:72b`/`qwen3:32b` | 32768+ | 6 | 32 | bajos | `f16` |

**Perillas:** `MAX_ASYNC` = llamadas LLM en paralelo (CPU=1; en GPU sube según VRAM).
`OLLAMA_LLM_NUM_CTX` = ventana para extracción (32k+ ideal, pero consume RAM/VRAM; 8k en
CPU para evitar swap). `OLLAMA_KV_CACHE_TYPE=q8_0` comprime la KV cache. Sube timeouts en
CPU. Ollama usa la GPU automáticamente si está disponible (`OLLAMA_NUM_PARALLEL`, capas
descargadas según VRAM). Regla de oro: sube modelo/`NUM_CTX`/`MAX_ASYNC` **solo si el
hardware lo aguanta sin swap**; en CPU, prioriza terminar el indexado antes que calidad
máxima.

---

## Herramientas MCP

### `myrmion-graphrag` (documentos)

| Herramienta | Qué hace |
|-------------|----------|
| `buscar_conocimiento(consulta, modo="mix", solo_contexto=True, top_k=40)` | Recupera contexto del grafo para que **tú** razones |
| `anadir_documento(texto, descripcion="")` | Indexa un texto al vuelo (asíncrono) |
| `sincronizar_documento(ruta, texto="")` | Actualiza un documento tras editarlo **sin duplicar** y **versionado** (skip si el hash no cambió; delete + insert/upload si cambió) |
| `sincronizar_documentos(carpeta="")` | Sincroniza una carpeta entera: added/modified/removed por **hash**, crea un snapshot |
| `historico_documento(ruta)` | Evolución versionada del documento (added/modified/removed por commit) |
| `estado_documentos()` | Nº de documentos rastreados y último snapshot |
| `estado_rag()` | Salud de LightRAG + backend de storage activo |
| `verificar_alineacion()` / `reconciliar(aplicar=False)` | Consistencia Neo4j⇄Postgres (perfil híbrido) |

Modos de búsqueda: `mix` (recomendado), `hybrid`, `local`, `global`, `naive`.

### `myrmion-codebase` (código)

| Herramienta | Qué hace |
|-------------|----------|
| `indexar_codebase(ruta="", incremental=False)` | Indexa/reindexa el codebase |
| `sincronizar_codigo(rutas)` | Sync incremental idempotente tras editar |
| `dependencias_de(simbolo, profundidad=1)` | De qué depende (callees) |
| `quien_llama_a(simbolo, profundidad=1)` | Quién lo llama (callers) |
| `a_que_afecta(simbolo, profundidad=5)` | **Blast radius**: qué se afecta si lo cambias |
| `inventario(filtro="")` | Símbolos con etiquetas reusable/mandatory/dead |
| `codigo_muerto()` | Funciones/clases sin callers ni export |
| `arquitectura()` | Lenguajes, módulos, hotspots, reutilizables, muertos |
| `cambios_desde(git_ref)` | Ficheros cambiados + blast radius de cada símbolo |
| `anotar_simbolo(simbolo, etiqueta, nota="")` | Anotación persistente (mandatory/reusable/keep/…) |
| `historico(simbolo)` | Evolución added/modified/removed por commit |
| `estado_indexado()` | Último snapshot y si el codebase cambió desde entonces |

Cada llamada expone la **confianza** (`exact`/`heuristic`/`unresolved`) de las aristas para
que valores tú la fiabilidad; nunca se adivina en ambigüedad.

---

## Lenguajes y parsers cubiertos

El servidor `myrmion-codebase` elige el parser por la **extensión** del fichero. El grafo es
el mismo para todos (nodos `Module/Class/Function/Method`, aristas `DEFINES/IMPORTS/INHERITS/
CALLS/IMPLEMENTS`); solo cambia el motor de parseo:

| Lenguaje | Extensiones | Parser | Notas |
|----------|-------------|--------|-------|
| **Python** | `.py` | `ast` (stdlib) | resolución semántica de scopes; cero dependencias |
| **JavaScript** | `.js .jsx .mjs .cjs` | tree-sitter | `tree-sitter-javascript` |
| **TypeScript / TSX** | `.ts .tsx` | tree-sitter | `tree-sitter-typescript` |
| **Java** | `.java` | tree-sitter | `tree-sitter-java` |
| **C#** | `.cs` | tree-sitter | `tree-sitter-c-sharp` |
| **VB.NET** | `.vb` | **tree-sitter** | grammar `vb` de `tree-sitter-language-pack`: `Class`/`Module`/`Structure`/`Interface`/`Enum`, `Sub`/`Function`, `Imports`, llamadas |
| **VB5/6 · VBScript** | `.bas .cls .frm .vbs` | propio (line-oriented) | `Sub`/`Function`/`Property Get\|Let\|Set`/`Class`, `Implements`, `Call` (sin gramática tree-sitter fiable) |
| **ASP clásico** | `.asp` | preprocesador → VBScript | extrae bloques `<% %>` y directivas `<!--#include-->` (→ `IMPORTS`) |

> La resolución de llamadas es **heurística** en todos los lenguajes (tree-sitter es
> sintáctico; no hay análisis de tipos): se expone `confidence` (`exact`/`heuristic`/
> `unresolved`) para que valores la fiabilidad. En VB.NET la herencia (`Inherits`/`Implements`)
> se omite por ser poco fiable en la gramática. Nuevos lenguajes tree-sitter se añaden
> registrando su gramática y extensión. El markup `.aspx` de ASP.NET queda para fase posterior.

---

## Mantenimiento automático del codebase_inventory

El inventario **durable** refleja **solo la rama `main`**; editar en ramas de feature no lo
muta (si la rama nunca se mergea, no deja símbolos fantasma). Tres capas:

1. **Instrucciones en `CLAUDE.md`**: Claude llama a `sincronizar_codigo` tras editar.
2. **Hook `PostToolUse`** (`.claude/settings.json` → `hooks/sync_on_edit.sh`): mantiene
   caliente el **overlay** de sesión tras cada Edit/Write (nunca el durable).
3. **git `pre-push` hook** (`hooks/pre-push`, activado por `setup.sh` vía
   `core.hooksPath`): al hacer push a `main`, reconcilia el inventario canónico con el diff
   y **aborta el push** si no queda consistente. Lo ejecuta git, no el modelo → **no se
   puede saltar**.

---

## Sincronización incremental sin duplicados

`sincronizar_codigo(["ruta"])` (y el CLI `python -m codebase_mcp.sync`) actualizan el grafo
tras editar, garantizando:

- **Sin duplicados**: `Node.id` estable (`kind:qualified_name`) + upsert idempotente.
- **Sin residuos**: borra todos los nodos/aristas del fichero antes de re-parsear (los
  símbolos renombrados/eliminados desaparecen).
- **Consistencia cruzada**: re-resuelve todas las llamadas, así ninguna arista de otro
  fichero queda colgando.
- **Barato**: no-op si el hash del fichero no cambió.

---

## Versionado de documentos

LightRAG guarda solo la versión **actual** de cada documento y deduplica por **nombre**
(archiva los duplicados en vez de actualizar): si el contenido cambia pero el nombre no, un
re-upload ingenuo **pierde el update**. Por encima de LightRAG hay un **ledger de documentos**
que reutiliza la misma maquinaria que el inventario de código (snapshots + histórico), con la
identidad = basename y el `body_hash` = **hash de contenido/bytes**:

- **Detección por hash, no por nombre**: `sincronizar_documento(ruta)` / `sincronizar_documentos(carpeta)`
  reindexan **solo** si el hash cambió (no-op si no), y hacen **delete + insert/upload** cuando
  cambió → nunca se pierde un update ni se duplica. Funciona con binarios (pdf/docx: se re-sube
  el fichero por multipart).
- **Histórico**: cada sync crea un **snapshot** (etiquetado con el commit git) y registra
  added/modified/removed → `historico_documento(ruta)` y `estado_documentos()`, igual que el
  codebase.
- **Batch seguro**: `python ingest.py "$INPUT_DIR" --sync` usa el ledger para saltar lo no
  cambiado y **actualizar** (borrar+subir) lo modificado, en vez de dejar que LightRAG archive
  el duplicado.

El ledger vive en `config/docs.json` (var `DOCS_LEDGER`), gitignored.

---

## Tests

```bash
pip install -r requirements-dev.txt      # pytest, pytest-cov, respx, tree-sitter, ...
python -m pytest                         # cobertura mínima exigida: 80%
```

87 tests, ~87% de cobertura. Todo corre **sin servicios externos** (HTTP mockeado con
`respx`, grafo en memoria, git real en `tmp_path`). Los tests que requieren Neo4j/Postgres
reales van marcados `@pytest.mark.integration` y se excluyen por defecto.

---

## Estructura del repo

```
.
├── mcp_server.py            # servidor MCP de documentos (LightRAGClient)
├── codebase_server.py       # servidor MCP de código
├── codebase_mcp/            # paquete: parsers, GraphStore, resolver, queries, inventory,
│                            #          gitutil, history, indexer, sync
├── backends.py              # perfiles de storage + healthcheck + modelos (testeable)
├── consistency.py           # saga + reconciliación del híbrido (testeable)
├── consistency_readers.py   # cableado a Neo4j/Postgres reales (integración)
├── ingest.py                # ingesta en lote de documentos
├── docker-compose.yml       # Neo4j / Postgres (perfiles)
├── hooks/                   # pre-push (gate del inventario) + sync_on_edit (PostToolUse)
├── tests/                   # suite pytest + fixtures/mini_codebase
├── pyproject.toml           # config de pytest/coverage
├── *.env.example / .mcp.json.example / *.sh.example   # PLANTILLAS públicas
└── CLAUDE.md / README.md / LICENSE

# Generado en local, NUNCA versionado (gitignored):
#   config/            TU config real (lightrag.env, codebase.env, mcp.json, codebase.json)
#   .env  .mcp.json    enlaces a config/
#   db-up.sh  migrate-backend.sh  venv/  rag_storage/
```

---

## Referencias / créditos

Este proyecto toma como base y se inspira en:

- [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) — motor GraphRAG (grafo + vectores + storage pluggable).
- [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) — concepto del servidor de inteligencia de codebase.
- [tree-sitter](https://tree-sitter.github.io/) + gramáticas `tree-sitter-javascript/typescript/java/c-sharp` y [tree-sitter-language-pack](https://github.com/kreuzberg-dev/tree-sitter-language-pack) (grammar `vb` para VB.NET) — parsing multi-lenguaje.
- [Ollama](https://ollama.com) y [Qwen](https://github.com/QwenLM) — modelos locales (LLM y embeddings).
- [Model Context Protocol](https://modelcontextprotocol.io) — el estándar que conecta las herramientas con Claude Code.
- [Neo4j](https://neo4j.com) y [PostgreSQL](https://www.postgresql.org) (pgvector + [Apache AGE](https://age.apache.org)) — backends profesionales.

---

## Licencia

MIT. Ver [LICENSE](LICENSE).
