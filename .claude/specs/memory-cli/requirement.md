# Requirement: Memory CLI

A command-line interface for the cognitive-memory system that lets users browse, search, manage, and configure memories directly from the terminal. Connects to the running MCP server over Streamable HTTP — never touches the database directly.

---

## Connection Model

The CLI connects to the cognitive-memory MCP server via Streamable HTTP using `mcp.client.streamable_http.streamablehttp_client` and `mcp.client.session.ClientSession`. The MCP server is the sole gateway to the data store. The CLI must never import or instantiate `MemoryEngine`, `Storage`, or any storage backend directly.

- **Default server URL**: `http://127.0.0.1:8050/mcp`
- **Override via env var**: `COGNITIVE_MEMORY_URL`
- **Entry point**: `cognitive-memory-cli = "cognitive_memory.cli:main"` in `pyproject.toml`

---

## Theme 1: Browsing Memories

### US-1.1: List memories with filters

As a **user**, I want to list memories with optional filters so that I can browse what the system has stored.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli list` lists memories (default limit 20)
- [ ] `--type` flag filters by memory type (`working`, `episodic`, `semantic`, `procedural`)
- [ ] `--tags` flag filters by one or more tags (comma-separated)
- [ ] `--state` flag filters by state (`active`, `archived`)
- [ ] `--search` flag performs full-text search within list
- [ ] `--limit` and `--offset` flags control pagination
- [ ] `--importance-min` and `--importance-max` flags filter by importance range
- [ ] Output displays columns in this order: ID (first 8 chars), type, importance, age, tags, truncated content (first 80 chars)
- [ ] ID is always the first column to support easy copy-paste into subsequent commands
- [ ] Output is formatted as a human-readable table by default
- [ ] `--json` flag outputs raw JSON for piping to other tools
- [ ] Empty results show a friendly "No memories found" message, not an error

### US-1.2: Get a specific memory

As a **user**, I want to retrieve a specific memory by ID so that I can see its full content, metadata, relationships, and version history.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli get <id>` displays the full memory
- [ ] Output includes: content, type, state, importance, stability, retrievability, access count, tags, source, conversation_id, created_at, updated_at, last_accessed
- [ ] Related memories (relationships) are listed with type, direction, and target ID
- [ ] Version history is displayed with timestamps and previous content
- [ ] `--json` flag outputs raw JSON
- [ ] Non-existent ID shows a clear error: "Memory <id> not found"

### US-1.3: View memory statistics

As a **user**, I want to see system-wide statistics so that I can understand the health and size of my memory store.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli stats` displays memory statistics
- [ ] Shows counts by type (working, episodic, semantic, procedural)
- [ ] Shows counts by state (active, archived)
- [ ] Shows average retrievability/decay info by type
- [ ] Shows consolidation history summary if available
- [ ] `--json` flag outputs raw JSON

### US-1.4: View related memories

As a **user**, I want to see memories related to a given memory so that I can explore the knowledge graph.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli related <id>` shows related memories
- [ ] `--depth` flag controls traversal depth (default 1)
- [ ] `--rel-types` flag filters by relationship types (comma-separated, e.g. `causes,supports`)
- [ ] Output shows relationship type, direction, strength, and target memory summary
- [ ] `--json` flag outputs raw JSON

---

## Theme 2: Searching Memories

### US-2.1: Recall memories by query

As a **user**, I want to perform a multi-strategy recall query so that I can find relevant memories using semantic search, keyword matching, and graph traversal.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli recall "query text"` performs multi-strategy retrieval
- [ ] `--type` flag filters results by memory type
- [ ] `--tags` flag filters results by tags (comma-separated)
- [ ] `--limit` flag controls max results (default 10)
- [ ] `--time-start` and `--time-end` flags filter by time range (ISO 8601 format)
- [ ] Results show: rank, score, content (truncated), type, tags, retrieval strategy (found_by), and ID
- [ ] Results are ordered by score (highest first)
- [ ] `--json` flag outputs raw JSON
- [ ] Empty results show a friendly message, not an error

---

## Theme 3: Managing Memories

### US-3.1: Store a new memory

As a **user**, I want to store a new memory from the command line so that I can capture knowledge without needing an AI agent.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli store "content text"` creates a new memory
- [ ] `--type` flag sets memory type (optional; system auto-classifies if omitted)
- [ ] `--tags` flag sets tags (comma-separated)
- [ ] `--importance` flag sets importance (0.0-1.0; system auto-scores if omitted)
- [ ] `--source` flag sets source metadata
- [ ] On success, displays the created memory's ID, type, and importance
- [ ] `--json` flag outputs the full created memory as JSON
- [ ] Content can also be piped via stdin (e.g., `echo "some text" | cognitive-memory-cli store -`)

### US-3.2: Update a memory

As a **user**, I want to update an existing memory's content or metadata so that I can correct or enrich stored knowledge.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli update <id>` updates a memory
- [ ] `--content` flag sets new content
- [ ] `--type` flag changes memory type
- [ ] `--importance` flag changes importance
- [ ] `--tags` flag replaces tags (comma-separated)
- [ ] At least one of the above flags must be provided; otherwise show usage help
- [ ] On success, displays confirmation with the updated fields
- [ ] `--json` flag outputs the full updated memory as JSON
- [ ] Non-existent ID shows a clear error

### US-3.3: Delete a memory

As a **user**, I want to permanently delete a memory so that I can remove incorrect or unwanted data.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli delete <id>` deletes a memory
- [ ] Prompts for confirmation before deleting: "Permanently delete memory <id>? [y/N]"
- [ ] `--yes` flag skips the confirmation prompt (for scripting)
- [ ] On success, displays "Memory <id> deleted"
- [ ] Non-existent ID shows a clear error
- [ ] Supports deleting multiple IDs: `cognitive-memory-cli delete <id1> <id2> ...`

### US-3.4: Archive and restore memories

As a **user**, I want to archive and restore memories so that I can manage memory lifecycle without permanent deletion.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli archive <id>` archives a memory
- [ ] `cognitive-memory-cli restore <id>` restores an archived memory
- [ ] Both support multiple IDs: `archive <id1> <id2> ...`
- [ ] `archive --below-retrievability <threshold>` archives all memories below a retrievability threshold
- [ ] On success, displays count of memories archived/restored
- [ ] `--json` flag outputs raw JSON

### US-3.5: Create and remove relationships

As a **user**, I want to create and remove relationships between memories so that I can build a knowledge graph.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli relate <source_id> <target_id> --type <rel_type>` creates a relationship
- [ ] `--type` is required and must be one of: `causes`, `follows`, `contradicts`, `supports`, `relates_to`, `supersedes`, `part_of`
- [ ] `--strength` flag sets relationship strength (default 1.0)
- [ ] `cognitive-memory-cli unrelate <source_id> <target_id> --type <rel_type>` removes a relationship
- [ ] On success, displays confirmation with relationship details
- [ ] `--json` flag outputs raw JSON

### US-3.6: Trigger consolidation

As a **user**, I want to trigger the consolidation pipeline so that I can maintain memory health (decay updates, promotions, archival, clustering, merging).

**Acceptance criteria:**
- [ ] `cognitive-memory-cli consolidate` runs the consolidation pipeline
- [ ] `--dry-run` flag shows what would happen without making changes
- [ ] Displays a summary of actions taken (or planned in dry-run mode) with counts
- [ ] `--json` flag outputs raw JSON

---

## Theme 4: Configuration

### US-4.1: View and set configuration

As a **user**, I want to view and modify the system's configuration so that I can tune decay rates, retrieval weights, and other parameters.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli config` displays all configuration
- [ ] `cognitive-memory-cli config <key>` displays a specific config value
- [ ] `cognitive-memory-cli config <key> <value>` sets a config value
- [ ] Config keys use dot-notation (e.g., `decay.growth_factor`, `retrieval.weights.semantic`)
- [ ] `--json` flag outputs raw JSON
- [ ] Displays human-readable output with key-value formatting by default

---

## Theme 5: Connection and UX

### US-5.1: Graceful server connection handling

As a **user**, I want the CLI to fail gracefully when the server is unreachable so that I get a clear error instead of a stack trace.

**Acceptance criteria:**
- [ ] If the server is not running, displays: "Cannot connect to cognitive-memory server at <url>. Is the server running?"
- [ ] Connection timeout is reasonable (5 seconds)
- [ ] Suggests how to start the server: "Start it with: cognitive-memory"
- [ ] Exit code is non-zero on connection failure

### US-5.2: Global flags

As a **user**, I want consistent global flags across all commands for output control and connection configuration.

**Acceptance criteria:**
- [ ] `--json` flag works on all commands — outputs raw JSON response from the MCP server
- [ ] `--url <url>` flag overrides the server URL for the current invocation
- [ ] `--help` shows usage for any command/subcommand
- [ ] `--version` shows the CLI version (matches package version from pyproject.toml)

### US-5.3: Help and discoverability

As a **user**, I want built-in help text so that I can learn the CLI without external documentation.

**Acceptance criteria:**
- [ ] `cognitive-memory-cli --help` shows all available commands with one-line descriptions
- [ ] Each subcommand has its own `--help` with argument/flag descriptions and examples
- [ ] Help text includes the default server URL and the env var override

---

## Non-Functional Requirements

- **Python version**: 3.11+
- **Dependencies**: Should use `click` or `argparse` for CLI parsing. Prefer `click` for its subcommand support and help generation. If `click` is chosen, add it to `pyproject.toml` dependencies.
- **Async**: The MCP client is async. The CLI entry point must bridge sync-to-async (e.g., `asyncio.run()`).
- **Output**: Human-readable tables/formatting by default. `--json` for machine-readable output. Use `rich` for table formatting if desired (optional dependency).
- **Error handling**: All MCP tool errors (from the `success: false` response pattern) must be surfaced as user-friendly messages, not raw JSON or stack traces.
- **Testing**: CLI should be testable by mocking the MCP client session. Integration tests can use the same server-spawn pattern as `test_mcp_client.py`.
