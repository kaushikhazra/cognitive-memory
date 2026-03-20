# Cognitive Memory

A biologically-inspired cognitive memory system for AI agents, exposed as an [MCP](https://modelcontextprotocol.io/) server. Gives agents persistent memory with human-like properties: memories decay over time, strengthen with use, form relationships, and consolidate automatically.

## Features

- **Four memory types** with different decay rates — working (hours), episodic (days), semantic (weeks), procedural (months)
- **FSRS-inspired decay** — retrievability computed on-the-fly: `R(t) = e^(-t / 9S)`
- **Multi-strategy retrieval** — semantic search, BM25 keyword search, temporal recency, and graph traversal fused with Reciprocal Rank Fusion (RRF)
- **Spreading activation** — retrieving a memory strengthens its neighbors in the relationship graph
- **Automatic linking** — new memories are linked to similar existing ones via cosine similarity
- **Contradiction detection** — flags semantically similar memories with negation signals
- **Consolidation pipeline** — promotes working→episodic→semantic/procedural, archives forgotten memories, merges near-duplicates
- **Version history** — every update creates a snapshot for full audit trail

## Installation

Requires Python 3.11+.

```bash
pip install -e .
```

This installs `sentence-transformers` (all-MiniLM-L6-v2, 384 dimensions) for embeddings.

## Usage

### As an MCP server

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "cognitive-memory": {
      "command": "cognitive-memory",
      "env": {
        "COGNITIVE_MEMORY_DB": "~/.cognitive-memory/memory.db"
      }
    }
  }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COGNITIVE_MEMORY_DB` | `~/.cognitive-memory/memory.db` | SQLite database path |
| `COGNITIVE_MEMORY_CONFIG` | bundled `config.default.yaml` | Config YAML override path |

## MCP Tools

| Tool | Description |
|------|-------------|
| `memory_store` | Store a new memory with auto-classification and importance scoring |
| `memory_recall` | Multi-strategy retrieval with RRF fusion and decay reranking |
| `memory_get` | Get a specific memory with relationships and version history |
| `memory_update` | Update content/metadata with versioning and re-embedding |
| `memory_relate` | Create typed relationships between memories |
| `memory_related` | Graph traversal to find connected memories |
| `memory_unrelate` | Remove a relationship |
| `memory_list` | Browse/filter memories with full-text search |
| `memory_archive` | Archive by ID, bulk IDs, or retrievability threshold |
| `memory_restore` | Restore archived memories with decay reset |
| `memory_delete` | Permanent deletion with cascade (requires `confirm: true`) |
| `memory_stats` | System statistics: counts, decay health, storage usage |
| `memory_consolidate` | Run consolidation pipeline (supports `dry_run`) |
| `memory_config` | View or update configuration |

## Architecture

```
cognitive_memory/
  server.py          MCP stdio server — 14 tools
  engine.py          Central orchestrator
  storage.py         SQLite with WAL, FTS5, migrations
  embeddings.py      Sentence-transformers + in-memory numpy matrix
  retrieval.py       Two-phase RRF pipeline with spreading activation
  decay.py           FSRS-inspired decay engine (pure functions)
  consolidation.py   Promotion, archival, clustering, merging
  classification.py  Heuristic type classification + importance scoring
  config.py          YAML defaults + SQLite overrides
  models.py          Pydantic domain models
  migrations/        Numbered migration scripts
```

## Configuration

All config is in `config.default.yaml` with dot-notation keys. Override at runtime via `memory_config` tool or `COGNITIVE_MEMORY_CONFIG` env var.

Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `decay.initial_stability.working` | 0.04 | Working memory S0 (~1 hour) |
| `decay.initial_stability.episodic` | 2.0 | Episodic memory S0 (~2 days) |
| `decay.initial_stability.semantic` | 14.0 | Semantic memory S0 (~2 weeks) |
| `decay.initial_stability.procedural` | 60.0 | Procedural memory S0 (~2 months) |
| `decay.growth_factor` | 2.0 | Reinforcement strength on access |
| `retrieval.weights.semantic` | 1.0 | Semantic search weight in RRF |
| `retrieval.weights.keyword` | 0.7 | BM25 keyword search weight |
| `retrieval.weights.graph` | 0.5 | Graph traversal weight |
| `auto_linking.similarity_threshold` | 0.75 | Min cosine similarity for auto-links |
| `consolidation.merge_threshold` | 0.90 | Min similarity to merge memories |

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
