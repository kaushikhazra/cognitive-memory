# Design — SurrealDB + Windows Service

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Windows Service (cognitive-memory-service)      │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Uvicorn + Starlette ASGI               │   │
│  │  ┌──────────────────────────────────┐   │   │
│  │  │  FastMCP Streamable HTTP         │   │   │
│  │  │  POST /mcp  (JSON-RPC 2.0)      │   │   │
│  │  │  GET  /mcp  (SSE resumption)     │   │   │
│  │  └──────────┬───────────────────────┘   │   │
│  └─────────────┼───────────────────────────┘   │
│                │                                │
│  ┌─────────────▼───────────────────────────┐   │
│  │  MemoryEngine (orchestrator)            │   │
│  │  - store, recall, update, delete, etc.  │   │
│  └─────────────┬───────────────────────────┘   │
│                │                                │
│  ┌─────────────▼───────────────────────────┐   │
│  │  SurrealStorage (replaces Storage)      │   │
│  │  - SurrealDB embedded (surrealkv://)    │   │
│  │  - Graph edges via RELATE               │   │
│  │  - HNSW vector index (cosine)           │   │
│  │  - Native FTS                           │   │
│  └─────────────┬───────────────────────────┘   │
│                │                                │
│  ┌─────────────▼───────────────────────────┐   │
│  │  EmbeddingService                       │   │
│  │  - sentence-transformers (unchanged)    │   │
│  │  - No more numpy matrix management      │   │
│  │  - embed() only, search is DB-side      │   │
│  └─────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘

Claude Code sessions connect via:
  npx mcp-remote http://127.0.0.1:52100/mcp
```

## Port

`52100` — arbitrary high port, unlikely to collide. Configurable via env var `COGNITIVE_MEMORY_PORT`.

## SurrealDB Schema

```surql
-- Namespace and database
USE NS cognitive DB memory;

-- Memory records
DEFINE TABLE memory SCHEMAFULL;
DEFINE FIELD content       ON memory TYPE string;
DEFINE FIELD memory_type   ON memory TYPE string ASSERT $value IN ['working', 'episodic', 'semantic', 'procedural'];
DEFINE FIELD state         ON memory TYPE string DEFAULT 'active' ASSERT $value IN ['active', 'archived'];
DEFINE FIELD importance    ON memory TYPE float ASSERT $value >= 0.0 AND $value <= 1.0;
DEFINE FIELD stability     ON memory TYPE float;
DEFINE FIELD retrievability ON memory TYPE float;
DEFINE FIELD access_count  ON memory TYPE int DEFAULT 0;
DEFINE FIELD created_at    ON memory TYPE datetime;
DEFINE FIELD updated_at    ON memory TYPE datetime;
DEFINE FIELD last_accessed ON memory TYPE datetime;
DEFINE FIELD source        ON memory TYPE option<string>;
DEFINE FIELD conversation_id ON memory TYPE option<string>;
DEFINE FIELD tags          ON memory TYPE array<string> DEFAULT [];
DEFINE FIELD embedding     ON memory TYPE option<array<float>>;

-- Vector index (HNSW, cosine distance)
DEFINE INDEX idx_memory_embedding ON memory FIELDS embedding HNSW DIMENSION 384 DIST COSINE;

-- Full-text search index
DEFINE ANALYZER memory_analyzer TOKENIZERS blank, class FILTERS lowercase, snowball(english);
DEFINE INDEX idx_memory_fts ON memory FIELDS content SEARCH ANALYZER memory_analyzer BM25;

-- Standard indexes
DEFINE INDEX idx_memory_state ON memory FIELDS state;
DEFINE INDEX idx_memory_type ON memory FIELDS memory_type;
DEFINE INDEX idx_memory_state_type ON memory FIELDS state, memory_type;

-- Graph edge tables (one per relationship type)
DEFINE TABLE causes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON causes TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON causes TYPE datetime;

DEFINE TABLE follows SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON follows TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON follows TYPE datetime;

DEFINE TABLE contradicts SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON contradicts TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON contradicts TYPE datetime;

DEFINE TABLE supports SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON supports TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON supports TYPE datetime;

DEFINE TABLE relates_to SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON relates_to TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON relates_to TYPE datetime;

DEFINE TABLE supersedes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON supersedes TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON supersedes TYPE datetime;

DEFINE TABLE part_of SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON part_of TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON part_of TYPE datetime;

-- Memory versions
DEFINE TABLE memory_version SCHEMAFULL;
DEFINE FIELD memory_id  ON memory_version TYPE record<memory>;
DEFINE FIELD content     ON memory_version TYPE string;
DEFINE FIELD metadata    ON memory_version TYPE option<object>;
DEFINE FIELD created_at  ON memory_version TYPE datetime;
DEFINE INDEX idx_version_memory ON memory_version FIELDS memory_id;

-- Consolidation log
DEFINE TABLE consolidation_log SCHEMAFULL;
DEFINE FIELD action     ON consolidation_log TYPE string ASSERT $value IN ['promote', 'merge', 'archive', 'flag_contradiction'];
DEFINE FIELD source_ids ON consolidation_log TYPE array<string>;
DEFINE FIELD target_id  ON consolidation_log TYPE option<string>;
DEFINE FIELD reason     ON consolidation_log TYPE string;
DEFINE FIELD created_at ON consolidation_log TYPE datetime;

-- Config
DEFINE TABLE config SCHEMAFULL;
DEFINE FIELD value      ON config TYPE any;
DEFINE FIELD updated_at ON config TYPE datetime;
```

## Key SurrealQL Patterns

### Vector search (replaces numpy cosine_search)
```surql
SELECT id, content, vector::similarity::cosine(embedding, $query_vec) AS score
FROM memory
WHERE state = 'active' AND embedding != NONE
ORDER BY score DESC
LIMIT $top_k;
```

### Full-text search (replaces FTS5)
```surql
SELECT id, content, search::score(1) AS score
FROM memory
WHERE content @1@ $query AND state = 'active'
ORDER BY score DESC
LIMIT $top_k;
```

### Graph traversal (replaces get_neighbors + BFS)
```surql
-- 1-hop neighbors
SELECT <->(causes|follows|contradicts|supports|relates_to|supersedes|part_of)<->memory AS neighbors
FROM $memory_id;

-- 2-hop with relationship data
SELECT ->relates_to->memory.* AS related FROM $memory_id;
```

### Create relationship (replaces insert_relationship)
```surql
RELATE $source->relates_to->$target SET strength = $strength, created_at = $now;
```

## File Changes

| File | Action | Notes |
|------|--------|-------|
| `storage.py` | Replace | New `SurrealStorage` class using surrealdb SDK |
| `embeddings.py` | Simplify | Remove numpy matrix management, keep embed() only |
| `retrieval.py` | Rewrite | Use SurrealQL for vector+FTS+graph in fewer queries |
| `consolidation.py` | Adapt | Use SurrealStorage API, logic stays same |
| `engine.py` | Adapt | Use SurrealStorage, remove transaction wrapping |
| `server.py` | Rewrite | FastMCP + Streamable HTTP + uvicorn |
| `service.py` | **New** | Windows Service wrapper (pywin32) |
| `schema.surql` | **New** | SurrealDB schema definition |
| `migrations/` | Keep | SQLite migrations for backward compat |
| `migrate_to_surreal.py` | **New** | SQLite → SurrealDB migration script |
| `models.py` | Keep | Pydantic models unchanged |
| `decay.py` | Keep | Pure functions, no storage dependency |
| `classification.py` | Keep | Pure functions |
| `config.py` | Adapt | Read from SurrealDB config table |

## Windows Service Design

- **Service name**: `CognitiveMemory`
- **Display name**: `Cognitive Memory MCP Server`
- **Event loop**: `SelectorEventLoop` (not Proactor — avoids `set_wakeup_fd` crash)
- **Startup**: Load SurrealDB embedded → load embedding model → start uvicorn
- **Shutdown**: `server.should_exit = True` → close SurrealDB → exit
- **Logging**: File-based at `~/.cognitive-memory/service.log`
- **Config**: `~/.cognitive-memory/config.yaml` (same as before)
- **DB path**: `surrealkv://~/.cognitive-memory/data` (SurrealDB on-disk)

## Claude Code MCP Config

```json
{
  "mcpServers": {
    "cognitive-memory": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:52100/mcp"]
    }
  }
}
```

## Decisions

1. **Embedded SurrealDB, not separate server** — one process to manage, simpler ops, no network hop for DB access.
2. **One edge table per relationship type** — SurrealDB idiom. Cleaner than a single `relationship` table with type column. Arrow syntax reads naturally: `->supports->memory`.
3. **Port 52100** — high, memorable, unlikely to collide.
4. **Keep EmbeddingService for embed()** — SurrealDB stores vectors but doesn't generate them. sentence-transformers stays for embedding generation.
5. **mcp-remote bridge** — Claude Code doesn't natively support HTTP MCP yet. `npx mcp-remote` is the official bridge.
