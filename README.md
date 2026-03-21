# Cognitive Memory

A biologically-inspired cognitive memory system for AI agents, exposed as an [MCP](https://modelcontextprotocol.io/) server. Gives agents persistent memory with human-like properties: memories decay over time, strengthen with use, form relationships, and consolidate automatically.

## Features

- **Four memory types** with different decay rates — working (hours), episodic (days), semantic (weeks), procedural (months)
- **FSRS-inspired decay** — retrievability computed on-the-fly: `R(t) = e^(-t / 9S)`
- **Multi-strategy retrieval** — semantic search (HNSW cosine), BM25 keyword search, temporal recency, and graph traversal fused with Reciprocal Rank Fusion (RRF)
- **Spreading activation** — retrieving a memory strengthens its neighbors in the relationship graph
- **Automatic linking** — new memories are linked to similar existing ones via cosine similarity
- **Contradiction detection** — flags semantically similar memories with negation signals
- **Consolidation pipeline** — promotes working->episodic->semantic/procedural, archives forgotten memories, merges near-duplicates
- **Version history** — every update creates a snapshot for full audit trail
- **CLI tool** — browse, search, and manage memories from the terminal
- **Windows service** — runs as a background service via Task Scheduler (no admin required)

## Installation

Requires Python 3.11+.

```bash
pip install -e .
```

This installs the MCP server, CLI tool, and all dependencies including `sentence-transformers` (all-MiniLM-L6-v2, 384d) and `SurrealDB` (embedded).

## Quick Start

### 1. Start the server

```bash
cognitive-memory
```

This starts the Streamable HTTP MCP server on `http://127.0.0.1:8050/mcp`.

### 2. Connect from Claude Code

Add to your Claude Code MCP config (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "cognitive-memory": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:8050/mcp"]
    }
  }
}
```

### 3. Use the CLI

```bash
# Search memories
cognitive-memory-cli recall "python programming"

# Browse
cognitive-memory-cli list
cognitive-memory-cli list --type semantic --tags "project,design"

# Get full details
cognitive-memory-cli get <memory-id>

# Store a memory
cognitive-memory-cli store "Python's GIL was removed in 3.13" --type semantic --tags "python,news"

# Pipe from stdin
echo "meeting notes here" | cognitive-memory-cli store -

# System health
cognitive-memory-cli stats
cognitive-memory-cli consolidate --dry-run

# JSON output for scripting
cognitive-memory-cli --json list | jq '.data.memories[].content'
```

Run `cognitive-memory-cli --help` for all commands and flags.

## Windows Service

Run the server as a background service that auto-starts at logon:

```bash
cognitive-memory-service install    # Register with Task Scheduler
cognitive-memory-service start      # Start now
cognitive-memory-service status     # Check health
cognitive-memory-service stop       # Stop
cognitive-memory-service remove     # Uninstall
cognitive-memory-service debug      # Run in foreground (development)
```

No admin elevation or pywin32 required. Uses Task Scheduler with auto-restart on failure (3 attempts, 1 minute apart).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COGNITIVE_MEMORY_DB` | `~/.cognitive-memory/data` | SurrealDB data directory |
| `COGNITIVE_MEMORY_PORT` | `8050` | HTTP server port |
| `COGNITIVE_MEMORY_HOST` | `127.0.0.1` | HTTP server bind address |
| `COGNITIVE_MEMORY_CONFIG` | bundled `config.default.yaml` | Config YAML override path |
| `COGNITIVE_MEMORY_URL` | `http://127.0.0.1:8050/mcp` | CLI: server URL (overrides `--url`) |

## MCP Tools (14)

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
  server.py          Streamable HTTP MCP server (FastMCP + uvicorn)
  cli.py             CLI tool (click, connects via MCP client)
  service.py         Windows Task Scheduler service management
  engine.py          Central orchestrator
  surreal_storage.py SurrealDB embedded storage (HNSW vectors, BM25 FTS, graph edges)
  embeddings.py      Sentence-transformers embedding service
  retrieval.py       Two-phase RRF pipeline with spreading activation
  decay.py           FSRS-inspired decay engine (pure functions)
  consolidation.py   Promotion, archival, clustering, merging
  classification.py  Heuristic type classification + importance scoring
  config.py          YAML defaults + DB overrides
  models.py          Pydantic domain models
  protocols.py       Storage protocol (typing.Protocol)
  schema.surql       SurrealDB schema definition
```

## Configuration

All config uses dot-notation keys. View/set at runtime via `memory_config` tool or `cognitive-memory-cli config`.

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
