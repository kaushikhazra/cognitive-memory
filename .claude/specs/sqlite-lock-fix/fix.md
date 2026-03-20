# SQLite Lock Fix

## What's Broken

MCP tool calls hang/get stuck. Root cause: SQLite write lock contention from:
1. No connection timeout (blocks indefinitely on lock)
2. Commit-per-SQL-statement — a single `store_memory` does 1+N+M commits, each acquiring/releasing write lock
3. No transaction boundaries — engine can't batch operations atomically
4. Synchronous SQLite blocking async event loop in `call_tool`

## What Changes

### storage.py
- Add `timeout=30` to `sqlite3.connect()`
- Remove all individual `self._conn.commit()` from CRUD methods
- Add `commit()` and `rollback()` public methods
- Add `transaction()` context manager for atomic operation groups
- Keep `_run_migrations()` commits (they're one-time and need their own transaction)

### engine.py
- Wrap each public method in `self.storage.transaction()` context manager
- One commit per engine operation instead of N commits per operation

### server.py
- Wrap synchronous engine calls in `asyncio.to_thread()` to avoid blocking the event loop

## How to Verify

1. `pytest` — existing tests pass
2. Manual: run two Claude Code sessions, both using cognitive-memory, store/recall concurrently — no hangs
3. Check that a failed mid-operation rolls back cleanly (no partial state)
