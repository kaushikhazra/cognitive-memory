"""MCP server — Streamable HTTP via FastMCP + uvicorn."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .engine import MemoryEngine

# Create FastMCP server with Streamable HTTP
mcp = FastMCP(
    "cognitive-memory",
    streamable_http_path="/mcp",
    json_response=False,
    stateless_http=True,
)

# Engine instance — initialized on first use, guarded by lock for concurrent init
_engine: MemoryEngine | None = None
_engine_lock = threading.Lock()


def _get_engine() -> MemoryEngine:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        db_path = os.environ.get("COGNITIVE_MEMORY_DB", str(Path.home() / ".cognitive-memory" / "data"))
        config_path = os.environ.get("COGNITIVE_MEMORY_CONFIG")
        # Build SurrealDB URL
        if not db_path.startswith(("mem://", "surrealkv://", "file://")):
            Path(db_path).mkdir(parents=True, exist_ok=True)
            # SurrealDB URL parser requires forward slashes (Windows backslashes break it)
            db_path = f"surrealkv://{db_path.replace(os.sep, '/')}"
        _engine = MemoryEngine(
            db_path=db_path,
            config_path=Path(config_path) if config_path else None,
        )
        return _engine


def _response(data: Any = None, elapsed_ms: float = 0, **meta_extra) -> str:
    """Build standard tool response as JSON string."""
    result = {
        "success": True,
        "data": data,
        "meta": {"elapsed_ms": round(elapsed_ms, 2), **meta_extra},
    }
    return json.dumps(result, default=str)


def _error(message: str) -> str:
    result = {"success": False, "error": message, "data": None, "meta": {}}
    return json.dumps(result, default=str)


# === Tool Definitions ===

@mcp.tool()
def memory_store(
    content: str,
    type: str | None = None,
    importance: float | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Store a new memory with automatic classification and importance scoring. Agent can override type and importance."""
    start = time.time()
    engine = _get_engine()
    try:
        mem = engine.store_memory(
            content=content, memory_type=type, importance=importance,
            tags=tags, source=source, conversation_id=conversation_id,
        )
        return _response(mem.model_dump(), (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_recall(
    query: str,
    type_filter: str | None = None,
    tags: list[str] | None = None,
    time_range: dict | None = None,
    limit: int | None = None,
) -> str:
    """Multi-strategy retrieval: semantic + keyword + graph + temporal, fused with RRF, decay-weighted. Returns ranked memories with provenance."""
    start = time.time()
    engine = _get_engine()
    try:
        tr = None
        if time_range:
            tr = (
                datetime.fromisoformat(time_range["start"]),
                datetime.fromisoformat(time_range["end"]),
            )
        results = engine.recall(
            query=query, type_filter=type_filter, tags=tags,
            time_range=tr, limit=limit,
        )
        return _response(
            {"memories": [r.model_dump() for r in results]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_get(id: str) -> str:
    """Get a specific memory by ID with full metadata, relationships, version history, and on-the-fly retrievability. Read-only."""
    start = time.time()
    engine = _get_engine()
    try:
        result = engine.get_memory(id)
        if result is None:
            return _error(f"Memory {id} not found")
        return _response(result.model_dump(), (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_update(
    id: str,
    content: str | None = None,
    type: str | None = None,
    importance: float | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update a memory's content or metadata. Creates a version snapshot, re-embeds if content changed, reinforces stability."""
    start = time.time()
    engine = _get_engine()
    try:
        mem = engine.update_memory(
            memory_id=id, content=content, memory_type=type,
            importance=importance, tags=tags,
        )
        if mem is None:
            return _error(f"Memory {id} not found")
        return _response(mem.model_dump(), (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_relate(
    source_id: str,
    target_id: str,
    rel_type: str,
    strength: float = 1.0,
) -> str:
    """Create a typed relationship between two memories. Default strength=1.0."""
    start = time.time()
    engine = _get_engine()
    try:
        rel = engine.create_relationship(source_id, target_id, rel_type, strength)
        return _response(rel.model_dump(), (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_related(
    id: str,
    depth: int = 1,
    rel_types: list[str] | None = None,
) -> str:
    """Get related memories via graph traversal. Read-only, no side effects."""
    start = time.time()
    engine = _get_engine()
    try:
        results = engine.get_related(id, depth=depth, rel_types=rel_types)
        return _response(results, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_unrelate(source_id: str, target_id: str, rel_type: str) -> str:
    """Remove a relationship between two memories."""
    start = time.time()
    engine = _get_engine()
    try:
        success = engine.delete_relationship(source_id, target_id, rel_type)
        return _response({"deleted": success}, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_list(
    search: str | None = None,
    type: str | None = None,
    state: str | None = None,
    tags: list[str] | None = None,
    time_range: dict | None = None,
    importance_min: float | None = None,
    importance_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Browse memories with filters and full-text search."""
    start = time.time()
    engine = _get_engine()
    try:
        tr = None
        if time_range:
            tr = (
                datetime.fromisoformat(time_range["start"]),
                datetime.fromisoformat(time_range["end"]),
            )
        memories = engine.storage.list_memories(
            search=search, memory_type=type, state=state, tags=tags,
            time_range=tr, importance_min=importance_min,
            importance_max=importance_max, limit=limit, offset=offset,
        )
        return _response(
            {"memories": [m.model_dump() for m in memories]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_archive(
    id: str | None = None,
    ids: list[str] | None = None,
    below_retrievability: float | None = None,
) -> str:
    """Archive memory/memories. Supports single ID, bulk IDs, or threshold-based."""
    start = time.time()
    engine = _get_engine()
    try:
        if id:
            success = engine.archive_memory(id)
            return _response({"archived": 1 if success else 0}, (time.time() - start) * 1000)
        elif ids:
            count = engine.archive_bulk(ids)
            return _response({"archived": count}, (time.time() - start) * 1000)
        elif below_retrievability is not None:
            count = engine.archive_below_retrievability(below_retrievability)
            return _response({"archived": count}, (time.time() - start) * 1000)
        return _error("Provide id, ids, or below_retrievability")
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_restore(
    id: str | None = None,
    ids: list[str] | None = None,
) -> str:
    """Restore archived memory/memories. Resets decay."""
    start = time.time()
    engine = _get_engine()
    try:
        if id:
            mem = engine.restore_memory(id)
            return _response(mem.model_dump() if mem else None, (time.time() - start) * 1000)
        elif ids:
            results = [mid for mid in ids if (m := engine.restore_memory(mid)) is not None]
            return _response({"restored": results}, (time.time() - start) * 1000)
        return _error("Provide id or ids")
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_delete(
    confirm: bool,
    id: str | None = None,
    ids: list[str] | None = None,
) -> str:
    """Permanently delete memory/memories. Cascades: relationships, versions, embeddings. Requires confirm=true."""
    start = time.time()
    engine = _get_engine()
    try:
        if not confirm:
            return _error("confirm must be true for permanent deletion")
        if id:
            success = engine.delete_memory(id)
            return _response({"deleted": 1 if success else 0}, (time.time() - start) * 1000)
        elif ids:
            count = sum(1 for mid in ids if engine.delete_memory(mid))
            return _response({"deleted": count}, (time.time() - start) * 1000)
        return _error("Provide id or ids")
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_stats() -> str:
    """System statistics: counts by type/state, average decay by type, consolidation history, storage usage."""
    start = time.time()
    engine = _get_engine()
    try:
        stats = engine.get_stats()
        return _response(stats, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_consolidate(dry_run: bool = False) -> str:
    """Trigger consolidation pipeline: decay update, promotion, archival, clustering, merging. Supports dry_run."""
    start = time.time()
    engine = _get_engine()
    try:
        actions = engine.consolidate(dry_run=dry_run)
        return _response({"actions": actions, "count": len(actions)}, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_self(
    query: str,
    tags: list[str] | None = None,
) -> str:
    """Recall identity memories — the agent's self-knowledge.

    Convenience wrapper over memory_recall with type_filter='identity'.
    Returns ranked identity memories matching the query.
    Supports optional tags filter for facet categories (e.g., 'origin', 'values', 'capability').
    """
    start = time.time()
    engine = _get_engine()
    try:
        results = engine.recall(
            query=query, type_filter="identity", tags=tags,
        )
        return _response(
            {"memories": [r.model_dump() for r in results]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_who(
    person: str,
    query: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Recall what the agent knows about a specific person.

    Matches person:{name} tags (case-insensitive). If no query is provided,
    uses the person's name as the query to return everything about them ranked
    by relevance.

    Fallback behavior: if person-typed query returns zero results, re-queries
    without type_filter but keeps the person tag filter. If still empty, queries
    with just the person name (no type or tag filter) to handle cold-start
    scenarios where knowledge exists as episodic/semantic memories.
    """
    person_name = person.strip().lower()
    if not person_name:
        return _error("person name is required")
    start = time.time()
    engine = _get_engine()
    try:
        # Build tag filter: person:{name} (lowercase)
        person_tag = f"person:{person_name}"
        combined_tags = [person_tag] + (tags or [])

        # If no query provided, use the person's name as the query
        effective_query = query or person_name

        # Primary: person-typed memories with person tag
        results = engine.recall(
            query=effective_query, type_filter="person", tags=combined_tags,
        )

        # W2 fallback: if no person-typed results, try without type filter
        if not results:
            results = engine.recall(
                query=effective_query, tags=combined_tags,
            )

        # W2 fallback: if still empty, try with just the person name as query
        if not results:
            results = engine.recall(
                query=effective_query,
            )

        return _response(
            {"memories": [r.model_dump() for r in results]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_health() -> str:
    """Return a diagnostic health report for the memory store.

    Includes: memory counts by type and state, at-risk decay list,
    orphan detection (untagged and unconnected), storage gaps, and
    consolidation history. Read-only — no side effects.
    """
    start = time.time()
    engine = _get_engine()
    try:
        report = engine.get_health()
        return _response(report, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def memory_config(
    key: str | None = None,
    value: Any = None,
) -> str:
    """View or update configuration. No params = return all. Key only = read. Key + value = write."""
    start = time.time()
    engine = _get_engine()
    try:
        if key and value is not None:
            engine.set_config(key, value)
            return _response({"key": key, "value": value, "action": "set"}, (time.time() - start) * 1000)
        elif key:
            result = engine.get_config(key)
            return _response(result, (time.time() - start) * 1000)
        else:
            result = engine.get_config()
            return _response(result, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))


# === Server Entry Points ===

def get_app():
    """Get the Starlette ASGI app for uvicorn."""
    return mcp.streamable_http_app()


def main() -> None:
    """CLI entrypoint — run the HTTP MCP server."""
    import logging
    import uvicorn

    # When running headless (pythonw.exe / Task Scheduler), redirect logs to file
    log_dir = Path.home() / ".cognitive-memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(log_dir / "service.log")

    if not sys.stdout or not sys.stdout.writable():
        # Running under pythonw.exe — no console available
        sys.stdout = open(log_file, "a")
        sys.stderr = sys.stdout

    port = int(os.environ.get("COGNITIVE_MEMORY_PORT", "8050"))
    host = os.environ.get("COGNITIVE_MEMORY_HOST", "127.0.0.1")

    # Pre-initialize the engine so startup errors are caught early
    _get_engine()

    uvicorn.run(get_app(), host=host, port=port, log_level="info", log_config={
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": log_file,
                "formatter": "default",
            },
        },
        "formatters": {
            "default": {
                "fmt": "%(asctime)s [%(levelname)s] %(message)s",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["file"],
        },
    })


if __name__ == "__main__":
    main()
