# Design Dry-Run Report #1

**Document**: `.claude/specs/surreal-service/design.md`
**Reviewed**: 2026-03-21

---

## Critical Gaps (must fix before implementation)

### [C1] Schema naming inconsistency: design says `config` table, schema/code uses `preference`
- **Pass**: 2 (Data Flow Trace), 3 (Interface Contract)
- **What**: The design's "SurrealDB Schema" section defines `DEFINE TABLE config SCHEMAFULL` with a `value` field. The actual `schema.surql` and `surreal_storage.py` implementation use `DEFINE TABLE preference SCHEMAFULL` with a `val` field. The methods in `SurrealStorage` (`get_config`, `set_config`, `get_all_config`) all query the `preference` table. Anyone implementing from the design document will create the wrong table and field names.
- **Risk**: Implementation from the design creates a `config` table with `value` field that nothing reads. Config overrides silently fail — all values fall through to YAML defaults with no error.
- **Fix**: Update the design's schema section to match the actual table name (`preference`) and field name (`val`). Or rename the implementation to match the design — pick one source of truth and make them agree.

### [C2] Concurrency model unspecified — thread safety of SurrealDB embedded SDK
- **Pass**: 6 (Concurrency & Ordering)
- **What**: The design specifies uvicorn serving HTTP to multiple concurrent clients (US-1, US-4), but doesn't address how concurrent requests are serialized at the SurrealDB level. FastMCP dispatches synchronous tool handlers (all 14 tools in `server.py` are sync functions) to a thread pool executor. Multiple threads will simultaneously call `SurrealStorage._db.query()`. The design doesn't state whether the SurrealDB Python SDK's `Surreal` instance is thread-safe for embedded mode, nor does it prescribe any locking or connection pooling strategy.
- **Risk**: If the SDK is not thread-safe: data corruption, crashes, or silent query failures under concurrent load — exactly the scenario US-1 exists to solve. If it IS thread-safe, the design should document this as an assumption.
- **Fix**: Add a "Concurrency" section to the design that: (1) documents the threading model (uvicorn → thread pool → sync tools → SurrealDB), (2) states the SDK thread-safety assumption with a reference, or (3) prescribes a serialization strategy (e.g., asyncio lock, threading.Lock, connection-per-thread).

### [C3] Architecture diagram shows SSE resumption, but implementation uses stateless HTTP
- **Pass**: 3 (Interface Contract Validation)
- **What**: The architecture diagram explicitly shows `GET /mcp (SSE resumption)` as a supported endpoint. However, `server.py` creates FastMCP with `stateless_http=True`, which disables MCP session tracking and the GET endpoint for SSE session reconnection. These are contradictory — stateless mode cannot support session resumption.
- **Risk**: Anyone building client-side reconnection logic based on the design's architecture diagram will find the GET endpoint non-functional. The design implies a capability the server doesn't provide.
- **Fix**: Either (a) remove "GET /mcp (SSE resumption)" from the architecture diagram since the server is stateless and tool-only (no subscriptions), or (b) change to `stateless_http=False` if SSE session resumption is actually needed. For a tool-only MCP server with no subscriptions, stateless is likely correct — update the diagram.

---

## Warnings (should fix, may cause issues)

### [W1] Engine singleton initialization has no concurrency guard
- **Pass**: 6 (Concurrency & Ordering)
- **What**: `_get_engine()` in `server.py` checks and sets the global `_engine` without any locking. Under concurrent first-requests (race window during cold start), multiple `MemoryEngine` instances could be created, each opening its own SurrealDB embedded connection to the same data directory.
- **Risk**: Dual SurrealDB connections to the same `surrealkv://` path could cause file locks or corruption. Even without corruption, one engine gets garbage-collected while the other is in use.
- **Suggestion**: Guard `_get_engine()` with a `threading.Lock`. Or initialize the engine eagerly at module load / app startup rather than lazily.

### [W2] Migration script listed but not designed
- **Pass**: 1 (Completeness), 7 (Edge Cases)
- **What**: The File Changes table lists `migrate_to_surreal.py` as "New — SQLite → SurrealDB migration script", but the design provides no detail: batch size, error handling, verification step, rollback plan, handling of embeddings (BLOB → array<float> conversion), relationship ID remapping, or what happens if migration is interrupted mid-way.
- **Risk**: Migration script gets implemented as a minimal "read all, write all" loop with no verification. An interrupted migration leaves both databases in an inconsistent state with no recovery path. The only existing data (Kaushik's actual memories) could be lost.
- **Suggestion**: Add a "Migration" section covering: batch size, progress reporting, verification (count comparison, spot-check content hashes), idempotency (re-runnable without duplicates), and rollback (keep SQLite untouched, only write to SurrealDB).

### [W3] Auto-restart on crash not specified
- **Pass**: 1 (Completeness)
- **What**: US-2 acceptance criterion requires "Auto-restart on crash." The design specifies the Windows Service wrapper but doesn't document the Windows SCM recovery configuration (restart delay, max failure count, reset period). Without explicit configuration, Windows Services default to "Take No Action" on failure.
- **Risk**: Service crashes and stays down until manually restarted, violating US-2.
- **Suggestion**: Add to the Windows Service Design section: `sc failure CognitiveMemory reset= 86400 actions= restart/5000/restart/10000/restart/30000` (restart after 5s, 10s, 30s, reset counter daily). Or document that `handle_command_line()` should configure this during install.

### [W4] No formal Storage interface contract
- **Pass**: 3 (Interface Contract Validation)
- **What**: The design says `SurrealStorage (replaces Storage)` but neither the old `Storage` class nor `SurrealStorage` implements a formal ABC or Protocol. The contract is implicit — whatever methods `engine.py`, `retrieval.py`, and `consolidation.py` call. This means the "replacement" relationship isn't verifiable at import time.
- **Risk**: A missing or misnamed method surfaces only at runtime when that specific code path executes. During implementation, it's easy to miss methods like `has_incoming_supersedes()` or `vector_search_for_memory()` that are called only in edge-case consolidation paths.
- **Suggestion**: Define a `StorageProtocol` (typing.Protocol) or ABC listing all required methods. Both `Storage` and `SurrealStorage` implement it. This is optional but reduces implementation risk.

### [W5] Cold start latency unaddressed
- **Pass**: 7 (Edge Cases & Boundaries)
- **What**: First request triggers a cascade: engine creation → SurrealDB connection → schema application → embedding model lazy-load (downloads ~90MB `all-MiniLM-L6-v2` on first run). This could take 30-120 seconds. The design doesn't address this.
- **Risk**: First MCP tool call after service start times out. Claude Code's `mcp-remote` has a default timeout — if the first request takes too long, the client gives up and the user sees "MCP server not responding."
- **Suggestion**: Add eager initialization in the service startup path (before accepting HTTP connections): connect SurrealDB, apply schema, and pre-load the embedding model. Report SERVICE_RUNNING only after warm-up completes. This way the service start takes longer but requests never time out.

### [W6] Silent schema error swallowing in `_ensure_schema()`
- **Pass**: 5 (Failure Path Analysis)
- **What**: The design says "DEFINE statements are idempotent" and the implementation wraps every schema statement in `try/except: pass`. If a statement fails for a non-idempotency reason (syntax error, disk full, SurrealDB version mismatch), the error is silently swallowed. The database enters an inconsistent schema state with no indication.
- **Risk**: A missing table or index causes cryptic query failures later. Debugging becomes extremely difficult because the root cause (schema failure) was hidden at startup.
- **Suggestion**: Differentiate between expected re-application warnings and real failures. Log all schema application results. Consider a schema version check (like the current SQLite `PRAGMA user_version` approach) instead of blind re-application.

### [W7] Multi-step store operation lacks atomicity
- **Pass**: 6 (Concurrency & Ordering)
- **What**: `engine.store_memory()` performs: classify → score importance → embed → insert_memory → auto-link (embed + vector_search + insert_relationships) → check contradictions. This is a multi-step operation with no transaction boundary. The design explicitly says "remove transaction wrapping" from the engine adaptation.
- **Risk**: If the service crashes after insert_memory but before auto-link, the memory exists without its embedding-based relationships. Subsequent recall may return orphaned memories with no graph connections.
- **Suggestion**: Either document that orphaned memories are acceptable and will be fixed by the next consolidation run, or use SurrealDB transactions (`BEGIN TRANSACTION ... COMMIT`) for the critical insert_memory + store_embedding + auto_link sequence.

---

## Observations (worth discussing)

### [O1] Design describes future state, but codebase is already partially migrated
The design reads as a migration plan, but the codebase already has: `surreal_storage.py` (complete), `engine.py` importing `SurrealStorage`, `retrieval.py` referencing `SurrealStorage`, `server.py` using FastMCP + streamable HTTP, `service.py` with Windows Service wrapper, and `schema.surql`. Meanwhile, `embeddings.py` still contains the numpy matrix management code (lines 54-115) that the design says to remove, and the old SQLite `storage.py` still exists. All task.md items are unchecked (`[ ]`). The design should clarify whether it's documenting what was already done or prescribing what remains.

### [O2] FTS search score interpretation differs between design and code
The design's FTS query pattern returns `search::score(1) AS score` (positive, higher = better). The old retrieval.py code (line 71) has `keyword_results.append((mid, -rank if rank < 0 else rank))` which negates FTS5's negative rank convention. With SurrealDB's FTS returning positive BM25 scores, this negation logic should be removed — but the design doesn't call this out as a retrieval.py change.

### [O3] `embeddings.py` still exports `to_bytes()` and `from_bytes()` — unused in SurrealDB path
With SurrealDB storing embeddings as `array<float>`, the bytes serialization methods (`to_bytes`, `from_bytes`) are only needed for the SQLite path. The design says to "keep embed() only" but the task says "keeps only embed(), embed_batch(), to_bytes(), from_bytes()". These byte-conversion methods are dead code in the SurrealDB architecture.

### [O4] Graph traversal queries in design use arrow syntax but implementation iterates per-table
The design's "Key SurrealQL Patterns" section shows elegant multi-edge arrow syntax: `<->(causes|follows|...)<->memory`. The actual `get_neighbors()` implementation (surreal_storage.py:398-418) iterates over each relationship table individually with separate queries. This works but issues 14 queries instead of 1. Worth noting as a future optimization.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 3        | 7        | 4            |

**Verdict**: PASS WITH WARNINGS — The architecture is sound and the core decisions (embedded SurrealDB, one-edge-table-per-type, FastMCP + uvicorn, Windows Service) are well-reasoned. However, three issues must be resolved before implementation proceeds: the schema naming inconsistency (C1) will cause implementation errors, the unspecified concurrency model (C2) risks data corruption under the exact concurrent-access scenario the migration targets, and the SSE resumption contradiction (C3) misleads about server capabilities. The warnings around migration safety (W2), cold start (W5), and atomicity (W7) should be addressed to avoid operational pain.

**Note**: Taskyn tracking was skipped — no surreal-service spec node found in Taskyn.
