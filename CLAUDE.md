# Cognitive Memory — Project Instructions

## What This Is

A biologically-inspired cognitive memory system exposed as an MCP server. Gives AI agents persistent, decay-aware memory with multi-strategy retrieval, automatic linking, contradiction detection, and consolidation.

## Architecture

```
server.py         MCP entrypoint — stdio JSON-RPC 2.0, 14 tools
  engine.py       Orchestrator — ingestion, update, delete, retrieval, consolidation
    storage.py    SQLite backend — CRUD, FTS5, migrations, WAL mode
    embeddings.py In-memory numpy matrix + lazy-loaded sentence-transformers (all-MiniLM-L6-v2, 384d)
    retrieval.py  Two-phase pipeline: semantic+keyword+temporal RRF fusion → graph traversal → decay reranking → spreading activation
    decay.py      FSRS-inspired: R(t) = e^(-t / 9S), reinforcement, spreading boost. Pure functions.
    consolidation.py  Promotion, archival, clustering, merging with contradiction detection
    classification.py Heuristic type classification + importance scoring
    config.py     Hierarchical: YAML defaults → SQLite overrides, dot-notation keys
    models.py     Pydantic models for all domain objects
    migrations/   Numbered migration scripts (001_initial.py)
```

## Key Conventions

- **Memory types**: `working` (fast decay), `episodic` (moderate), `semantic` (slow), `procedural` (very slow)
- **States**: `active`, `archived`
- **Relationship types**: `causes`, `follows`, `contradicts`, `supports`, `relates_to`, `supersedes`, `part_of`
- **Config**: dot-notation keys (`decay.growth_factor`, `retrieval.weights.semantic`). Defaults in `config.default.yaml`, overrides in SQLite `config` table.
- **Embeddings**: stored as BLOB in SQLite, loaded into numpy matrix on startup for fast cosine search
- **FTS5**: `memory_fts` virtual table kept in sync with `memory.content` — insert/update/delete must maintain both

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the server
cognitive-memory
# or
python -m cognitive_memory.server
```

**Environment variables:**
- `COGNITIVE_MEMORY_DB` — SQLite database path (default: `~/.cognitive-memory/memory.db`)
- `COGNITIVE_MEMORY_CONFIG` — config YAML override path (default: bundled `config.default.yaml`)

## Known Issues

- **SQLite locking**: Single `sqlite3.connect()` with no connection pooling or timeout. Concurrent MCP calls can deadlock. This is the active bug being investigated.

## Rules

- Every storage write must maintain FTS5 sync (insert into `memory_fts` on create, delete+re-insert on content update, delete on memory delete)
- Migrations are numbered sequentially (`001_`, `002_`, ...) and run exactly once via `PRAGMA user_version`
- Decay is computed on-the-fly (`compute_retrievability`), not stored — except during consolidation sweeps
- Auto-created `relates_to` links have `strength < 1.0` (cosine similarity). Manual links have `strength = 1.0`. `delete_auto_links` relies on this invariant.
- The embedding model is lazy-loaded on first `embed()` call — cold start takes a few seconds
