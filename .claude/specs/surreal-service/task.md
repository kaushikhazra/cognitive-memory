# Tasks — SurrealDB + Windows Service

## Phase 1: Foundation

- [x] **Velasari** creates `feature/surreal-service` branch from `develop`
- [x] **Velasari** adds `surrealdb`, `pywin32`, `uvicorn`, and `starlette` to `pyproject.toml` dependencies
- [x] **Velasari** creates `schema.surql` with full SurrealDB schema definition in `src/cognitive_memory/` — tables: memory, 7 edge tables, memory_version, consolidation_log, preference
  _US-3: SurrealDB Storage_

## Phase 2: Storage Layer

- [x] **Velasari** creates `protocols.py` defining `StorageProtocol` (typing.Protocol) listing all required storage methods — the contract both old `Storage` and new `SurrealStorage` must satisfy
  _US-3: SurrealDB Storage_

- [x] **Velasari** creates `surreal_storage.py` implementing `StorageProtocol` using SurrealDB embedded SDK (`Surreal("surrealkv://...")`)
  - insert_memory, get_memory, update_memory_fields, delete_memory
  - list_memories with FTS via `@@ $query`
  - fts_search via SurrealDB `search::score()`
  - insert/get/delete relationships via `RELATE` and arrow syntax
  - get_neighbors via graph traversal queries
  - bulk_update_stability
  - config CRUD via `preference` table (key = record ID, value in `val` field)
  - consolidation log CRUD
  - vector operations: store embedding as array<float>, cosine search via `vector::similarity::cosine()`
  _US-3: SurrealDB Storage_

- [x] **Velasari** simplifies `embeddings.py` — removes numpy matrix management (load_matrix, add_to_matrix, remove_from_matrix, replace_in_matrix, cosine_search), keeps only embed() and embed_batch(). Removes to_bytes()/from_bytes() (SQLite-only, no longer needed). Adds warmup() for eager model loading.
  _US-3: SurrealDB Storage_

- [x] **Velasari** adapts `config.py` to read/write from SurrealDB `preference` table via `SurrealStorage`
  _US-3: SurrealDB Storage_

## Phase 3: Engine + Retrieval Adaptation

- [x] **Velasari** adapts `engine.py` to use `SurrealStorage` — remove transaction wrapping, remove numpy matrix calls, vector search delegates to storage
  _US-3: SurrealDB Storage_

- [x] **Velasari** rewrites `retrieval.py` to use SurrealQL queries for vector search, FTS, and graph traversal. Removes FTS5 negative-rank negation (SurrealDB BM25 returns positive scores). Keeps RRF fusion logic, spreading activation, and decay reranking in Python.
  _US-3: SurrealDB Storage_

- [x] **Velasari** adapts `consolidation.py` to use `SurrealStorage` API (logic unchanged, only storage calls change)
  _US-3: SurrealDB Storage_

## Phase 4: Server + Service

- [x] **Velasari** rewrites `server.py` using `FastMCP` with `streamable_http_app()` and `stateless_http=True`, served by uvicorn on port 52100 (configurable via `COGNITIVE_MEMORY_PORT`). Guards `_get_engine()` with `threading.Lock` for safe concurrent initialization.
  _US-4: Streamable HTTP Transport_

- [x] **Velasari** creates `service.py` — Windows Service wrapper using `pywin32` (`win32serviceutil.ServiceFramework`), SelectorEventLoop, non-blocking stop signal (sets `server.should_exit = True`, no blocking WaitForSingleObject in async context). Eager warmup: connects SurrealDB, applies schema, pre-loads embedding model before reporting SERVICE_RUNNING. File logging to `~/.cognitive-memory/service.log`.
  _US-2: Windows Service Lifecycle_

## Phase 5: Migration + Config

- [x] **Velasari** creates `scripts/migrate_to_surreal.py` — reads existing SQLite DB (read-only), writes to SurrealDB in order: preference config → memories (with embedding BLOB→list[float] conversion) → versions → relationships. Batches of 100 with progress logging. Verification: count comparison + 5-memory spot-check per table. Idempotency: aborts if target non-empty unless `--force`. Error handling: log failed record IDs, continue, exit code 1 if any failures.
  _US-3: SurrealDB Storage_

- [ ] **Velasari** updates Claude Code MCP config to use `mcp-remote` pointing to `http://127.0.0.1:52100/mcp`
  _US-4: Streamable HTTP Transport_

## Phase 6: Test + Verify

- [x] **Velasari** updates `tests/test_client.py` to work with SurrealStorage (in-memory mode via `mem://`). Adds test case for orphaned-memory repair: store a memory, skip auto-linking, run consolidation, verify links are created.
  _US-3: SurrealDB Storage_

- [x] **Velasari** runs all tests — 28/28 integration + 14 MCP end-to-end
  _US-1, US-2, US-3, US-4_

- [ ] **Kaushik** tests concurrent access from two Claude Code sessions
  _US-1: Concurrent Session Access_
