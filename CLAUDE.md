# CLAUDE.md

Contexto del proyecto **myrmion-graphRAG** para Claude Code.

## Qué es esto

Dos memorias 100% locales expuestas a Claude Code como **dos servidores MCP**:

- **`myrmion-graphrag`** — GraphRAG sobre los *documentos* del usuario (LightRAG + Ollama).
- **`myrmion-codebase`** — grafo de *código*: dependencias, impacto, inventario, histórico.

Todo corre en la máquina del usuario; ningún documento ni código sale al exterior.

## Herramientas del servidor `myrmion-graphrag` (documentos)

Cuando el usuario pregunte por algo que probablemente viva en sus documentos indexados
(notas, manuales, papers, decisiones) y no esté en el contexto, usa estas herramientas en
lugar de suponer:

- `buscar_conocimiento(consulta, modo="mix", solo_contexto=True, top_k=40)` — recupera el
  contexto crudo (entidades, relaciones, fragmentos) para que **tú** razones. Primera opción.
- `anadir_documento(texto, descripcion="")` — indexa un texto al vuelo (asíncrono).
- `sincronizar_documento(ruta, texto="")` — actualiza un documento tras editarlo **sin
  duplicar** (delete + insert). Úsalo tras editar un fichero de documentación indexado.
- `estado_rag()` — salud de LightRAG + backend de storage activo. Llámalo primero si algo falla.
- `verificar_alineacion()` / `reconciliar(aplicar=False)` — solo perfil híbrido: comprueba y
  repara la alineación Neo4j⇄Postgres.

Modos: `mix` (recomendado), `hybrid`, `local` (entidades), `global` (temas), `naive` (vectores).

## Herramientas del servidor `myrmion-codebase` (código)

Para preguntas sobre el código del usuario (impacto, dependencias, qué es reutilizable/muerto):

- `indexar_codebase(ruta="", incremental=False)` — indexa/reindexa.
- `dependencias_de(simbolo, profundidad=1)` — de qué depende.
- `quien_llama_a(simbolo, profundidad=1)` — quién lo llama.
- `a_que_afecta(simbolo, profundidad=5)` — **blast radius** si se cambia.
- `inventario(filtro="")`, `codigo_muerto()`, `arquitectura()` — inventario y visión global.
- `cambios_desde(git_ref)`, `historico(simbolo)`, `estado_indexado()`.
- `anotar_simbolo(simbolo, etiqueta, nota="")` — fija mandatory/reusable/keep/deprecated.
- `sincronizar_codigo(rutas, durable=False)` — sync incremental tras editar.

Cada resultado incluye la **confianza** de las aristas (`exact`/`heuristic`/`unresolved`):
pondérala; no asumas que una llamada `heuristic`/`unresolved` es fiable al 100%.

## Mantenimiento OBLIGATORIO del codebase_inventory

- **Antes** de un cambio de impacto, consulta `a_que_afecta` / `quien_llama_a` para conocer
  el blast radius.
- **Después** de editar código, llama a `sincronizar_codigo([rutas_editadas])` para
  mantener el inventario al día.
- El inventario **durable** refleja solo `main`. El hook `PostToolUse`
  (`hooks/sync_on_edit.sh`) mantiene el overlay de sesión; el **git `pre-push` hook**
  (`hooks/pre-push`) reconcilia el inventario canónico al hacer push a `main` y **aborta el
  push** si no queda consistente — ese paso NO se puede saltar.

## Puesta en marcha

```bash
ollama pull qwen2.5:7b nomic-embed-text
./setup.sh                              # venv, config/, 2 servidores MCP, hook
# edita config/lightrag.env y config/codebase.env; re-ejecuta ./setup.sh
lightrag-server                         # otra terminal (documentos)
python ingest.py "$INPUT_DIR" --api-key "$LIGHTRAG_API_KEY" --watch
```

Config personal en `config/` (gitignored); en la raíz solo enlaces `.env` y `.mcp.json`.
Verifica con `/mcp` que aparecen **`myrmion-graphrag`** y **`myrmion-codebase`**.

## Notas

- Backends de storage seleccionables por perfil (filesystem/neo4j/postgres/híbrido); ver
  README. `estado_rag` reporta el backend activo. Cambiar de backend exige re-indexar.
- El inventario de código NO usa SQLite: `memory` (JSON), `neo4j` o `postgres`.
- Tests: `pip install -r requirements-dev.txt && python -m pytest` (cobertura mínima 80%).
- No edites `rag_storage/` a mano; lo gestiona LightRAG.
