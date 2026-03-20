# Tasks — SurrealDB + Windows Service

## Phase 1: Foundation

- [ ] **Velasari** creates `feature/surreal-service` branch from `develop`
- [ ] **Velasari** adds `surrealdb` and `pywin32` to `pyproject.toml` dependencies
- [ ] **Velasari** creates `schema.surql` with full SurrealDB schema definition in `src/cognitive_memory/`
  _US-3: SurrealDB Storage_

## Phase 2: Storage Layer

- [ ] **Velasari** creates `surreal_storage.py` implementing all methods from `Storage` interface using SurrealDB embedded SDK (`Surreal("surrealkv://...")`)
  - insert_memory, get_memory, update_memory_fields, delete_memory
  - list_memories with FTS via `@@ $query`
  - fts_search via SurrealDB `search::score()`
  - insert/get/delete relationships via `RELATE` and arrow syntax
  - get_neighbors via graph traversal queries
  - bulk_update_stability
  - config CRUD
  - consolidation log CRUD
  - vector operations: store embedding as array<float>, cosine search via `vector::similarity::cosine()`
  _US-3: SurrealDB Storage_

- [ ] **Velasari** simplifies `embeddings.py` — removes numpy matrix management (load_matrix, add_to_matrix, remove_from_matrix, replace_in_matrix, cosine_search), keeps only embed(), embed_batch(), to_bytes(), from_bytes()
  _US-3: SurrealDB Storage_

- [ ] **Velasari** adapts `config.py` to read/write from SurrealDB config table via `SurrealStorage`
  _US-3: SurrealDB Storage_

## Phase 3: Engine + Retrieval Adaptation

- [ ] **Velasari** adapts `engine.py` to use `SurrealStorage` — remove transaction wrapping, remove numpy matrix calls, vector search delegates to storage
  _US-3: SurrealDB Storage_

- [ ] **Velasari** rewrites `retrieval.py` to use SurrealQL queries for vector search, FTS, and graph traversal. Keeps RRF fusion logic, spreading activation, and decay reranking in Python.
  _US-3: SurrealDB Storage_

- [ ] **Velasari** adapts `consolidation.py` to use `SurrealStorage` API (logic unchanged, only storage calls change)
  _US-3: SurrealDB Storage_

## Phase 4: Server + Service

- [ ] **Velasari** rewrites `server.py` using `FastMCP` with `streamable_http_app()`, served by uvicorn on port 52100 (configurable via `COGNITIVE_MEMORY_PORT`)
  _US-4: Streamable HTTP Transport_

- [ ] **Velasari** creates `service.py` — Windows Service wrapper using `pywin32` (`win32serviceutil.ServiceFramework`), SelectorEventLoop, graceful shutdown, file logging to `~/.cognitive-memory/service.log`
  _US-2: Windows Service Lifecycle_

## Phase 5: Migration + Config

- [ ] **Velasari** creates `scripts/migrate_to_surreal.py` — reads existing SQLite DB, writes all memories + relationships + versions + config to SurrealDB
  _US-3: SurrealDB Storage_

- [ ] **Velasari** updates Claude Code MCP config to use `mcp-remote` pointing to `http://127.0.0.1:52100/mcp`
  _US-4: Streamable HTTP Transport_

## Phase 6: Test + Verify

- [ ] **Velasari** updates `tests/test_client.py` to work with SurrealStorage (in-memory mode)
  _US-3: SurrealDB Storage_

- [ ] **Velasari** runs all tests — 27/27 integration + MCP end-to-end
  _US-1, US-2, US-3, US-4_

- [ ] **Kaushik** tests concurrent access from two Claude Code sessions
  _US-1: Concurrent Session Access_
