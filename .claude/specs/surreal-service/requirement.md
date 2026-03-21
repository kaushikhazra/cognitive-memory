# Cognitive Memory — SurrealDB + Windows Service

## User Stories

### US-1: Concurrent Session Access
As Kaushik running multiple Claude Code sessions,
I want all sessions to share one cognitive-memory server,
so that memory calls never hang due to DB lock contention.

**Acceptance Criteria:**
- Single persistent server process handles all MCP requests
- Two+ Claude Code sessions can store/recall concurrently without hangs
- Server survives session disconnects (persistent daemon)

### US-2: Windows Service Lifecycle
As Kaushik,
I want cognitive-memory to run as a Windows Service,
so that it starts automatically on boot and restarts on failure.

**Acceptance Criteria:**
- Install/start/stop/remove via CLI commands
- `debug` mode runs in foreground for development
- Auto-restart on crash
- Logs to a file (not just stdout)
- Graceful shutdown: flushes pending writes, closes DB

### US-3: SurrealDB Storage
As a developer,
I want the storage layer to use SurrealDB,
so that graph traversal, vector search, and FTS are native DB operations.

**Acceptance Criteria:**
- SurrealDB embedded mode (no separate server process)
- All 14 MCP tools work identically (same inputs, same outputs)
- Vector similarity search via SurrealDB HNSW index (replaces numpy matrix)
- Full-text search via SurrealDB native FTS (replaces SQLite FTS5)
- Graph relationships stored as SurrealDB graph edges (RELATE)
- Graph traversal via SurrealQL arrow syntax (`->`, `<-`)
- Migration script to move existing SQLite data to SurrealDB

### US-4: Streamable HTTP Transport
As a Claude Code user,
I want to connect to cognitive-memory via HTTP,
so that the MCP server doesn't need to be spawned per-session.

**Acceptance Criteria:**
- MCP server exposed via Streamable HTTP (not stdio)
- Claude Code connects via `mcp-remote` bridge
- Multiple concurrent clients supported
- Client connect/disconnect does not affect stored memories (all state lives in SurrealDB, not in MCP sessions)
