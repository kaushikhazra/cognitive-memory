"""MCP server entrypoint — stdio JSON-RPC 2.0 with 14 memory tools."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .engine import MemoryEngine

# Create server instance
server = Server("cognitive-memory")

# Engine instance — initialized on startup
_engine: MemoryEngine | None = None


def _get_engine() -> MemoryEngine:
    global _engine
    if _engine is None:
        db_path = os.environ.get("COGNITIVE_MEMORY_DB", str(Path.home() / ".cognitive-memory" / "memory.db"))
        config_path = os.environ.get("COGNITIVE_MEMORY_CONFIG")
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = MemoryEngine(
            db_path=db_path,
            config_path=Path(config_path) if config_path else None,
        )
    return _engine


def _response(data: Any = None, elapsed_ms: float = 0, **meta_extra) -> list[TextContent]:
    """Build standard tool response."""
    result = {
        "success": True,
        "data": data,
        "meta": {"elapsed_ms": round(elapsed_ms, 2), **meta_extra},
    }
    return [TextContent(type="text", text=json.dumps(result, default=str))]


def _error(message: str) -> list[TextContent]:
    result = {"success": False, "error": message, "data": None, "meta": {}}
    return [TextContent(type="text", text=json.dumps(result, default=str))]


# === Tool Definitions ===

TOOLS = [
    Tool(
        name="memory_store",
        description="Store a new memory with automatic classification and importance scoring. Agent can override type and importance.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The memory content to store"},
                "type": {"type": "string", "enum": ["working", "episodic", "semantic", "procedural"], "description": "Memory type (optional, auto-classified if omitted)"},
                "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "Importance score (optional, auto-scored if omitted)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
                "source": {"type": "string", "description": "Source of the memory (e.g., 'conversation', 'manual')"},
                "conversation_id": {"type": "string", "description": "ID of the originating conversation"},
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="memory_recall",
        description="Multi-strategy retrieval: semantic + keyword + graph + temporal, fused with RRF, decay-weighted. Returns ranked memories with provenance.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "type_filter": {"type": "string", "enum": ["working", "episodic", "semantic", "procedural"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "time_range": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_get",
        description="Get a specific memory by ID with full metadata, relationships, version history, and on-the-fly retrievability. Read-only.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Memory ID"},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_update",
        description="Update a memory's content or metadata. Creates a version snapshot, re-embeds if content changed, reinforces stability.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "content": {"type": "string"},
                "type": {"type": "string", "enum": ["working", "episodic", "semantic", "procedural"]},
                "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_relate",
        description="Create a typed relationship between two memories. Default strength=1.0. Note: relates_to with strength < 1.0 may be replaced by auto-linking re-scans.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "rel_type": {"type": "string", "enum": ["causes", "follows", "contradicts", "supports", "relates_to", "supersedes", "part_of"]},
                "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
            },
            "required": ["source_id", "target_id", "rel_type"],
        },
    ),
    Tool(
        name="memory_related",
        description="Get related memories via graph traversal. Read-only, no side effects — does NOT trigger reinforcement or spreading activation.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1},
                "rel_types": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_unrelate",
        description="Remove a relationship between two memories.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "target_id": {"type": "string"},
                "rel_type": {"type": "string", "enum": ["causes", "follows", "contradicts", "supports", "relates_to", "supersedes", "part_of"]},
            },
            "required": ["source_id", "target_id", "rel_type"],
        },
    ),
    Tool(
        name="memory_list",
        description="Browse memories with filters and full-text search. Human-facing browse tool.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Full-text search query (FTS5)"},
                "type": {"type": "string", "enum": ["working", "episodic", "semantic", "procedural"]},
                "state": {"type": "string", "enum": ["active", "archived"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "time_range": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
                "importance_min": {"type": "number"},
                "importance_max": {"type": "number"},
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0},
            },
        },
    ),
    Tool(
        name="memory_archive",
        description="Archive memory/memories. Supports single ID, bulk IDs, or threshold-based (on-the-fly R).",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}},
                "below_retrievability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
    ),
    Tool(
        name="memory_restore",
        description="Restore archived memory/memories. Resets decay: last_accessed=now, stability boosted, R=1.0.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
    Tool(
        name="memory_delete",
        description="Permanently delete memory/memories. Cascades: relationships, versions, embeddings. Requires confirm=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    ),
    Tool(
        name="memory_stats",
        description="System statistics: counts by type/state, average decay by type, consolidation history, storage usage.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="memory_consolidate",
        description="Trigger consolidation pipeline: decay update, promotion, archival, clustering, merging. Supports dry_run.",
        inputSchema={
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False},
            },
        },
    ),
    Tool(
        name="memory_config",
        description="View or update configuration. No params = return all. Key only = read. Key + value = write.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {},
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return await asyncio.to_thread(_handle_tool, name, arguments)


def _handle_tool(name: str, arguments: dict) -> list[TextContent]:
    """Synchronous tool handler — runs in a thread to avoid blocking the event loop."""
    start = time.time()
    engine = _get_engine()

    try:
        if name == "memory_store":
            mem = engine.store_memory(
                content=arguments["content"],
                memory_type=arguments.get("type"),
                importance=arguments.get("importance"),
                tags=arguments.get("tags"),
                source=arguments.get("source"),
                conversation_id=arguments.get("conversation_id"),
            )
            elapsed = (time.time() - start) * 1000
            return _response(mem.model_dump(), elapsed)

        elif name == "memory_recall":
            tr = None
            if "time_range" in arguments and arguments["time_range"]:
                tr_raw = arguments["time_range"]
                tr = (
                    datetime.fromisoformat(tr_raw["start"]),
                    datetime.fromisoformat(tr_raw["end"]),
                )
            results = engine.recall(
                query=arguments["query"],
                type_filter=arguments.get("type_filter"),
                tags=arguments.get("tags"),
                time_range=tr,
                limit=arguments.get("limit"),
            )
            elapsed = (time.time() - start) * 1000
            return _response(
                {"memories": [r.model_dump() for r in results]},
                elapsed,
                memories_scanned=engine.embeddings.matrix_count,
            )

        elif name == "memory_get":
            result = engine.get_memory(arguments["id"])
            if result is None:
                return _error(f"Memory {arguments['id']} not found")
            elapsed = (time.time() - start) * 1000
            return _response(result.model_dump(), elapsed)

        elif name == "memory_update":
            mem = engine.update_memory(
                memory_id=arguments["id"],
                content=arguments.get("content"),
                memory_type=arguments.get("type"),
                importance=arguments.get("importance"),
                tags=arguments.get("tags"),
            )
            if mem is None:
                return _error(f"Memory {arguments['id']} not found")
            elapsed = (time.time() - start) * 1000
            return _response(mem.model_dump(), elapsed)

        elif name == "memory_relate":
            rel = engine.create_relationship(
                source_id=arguments["source_id"],
                target_id=arguments["target_id"],
                rel_type=arguments["rel_type"],
                strength=arguments.get("strength", 1.0),
            )
            elapsed = (time.time() - start) * 1000
            return _response(rel.model_dump(), elapsed)

        elif name == "memory_related":
            results = engine.get_related(
                memory_id=arguments["id"],
                depth=arguments.get("depth", 1),
                rel_types=arguments.get("rel_types"),
            )
            elapsed = (time.time() - start) * 1000
            return _response(results, elapsed)

        elif name == "memory_unrelate":
            success = engine.delete_relationship(
                arguments["source_id"], arguments["target_id"], arguments["rel_type"],
            )
            elapsed = (time.time() - start) * 1000
            return _response({"deleted": success}, elapsed)

        elif name == "memory_list":
            tr = None
            if "time_range" in arguments and arguments["time_range"]:
                tr_raw = arguments["time_range"]
                tr = (
                    datetime.fromisoformat(tr_raw["start"]),
                    datetime.fromisoformat(tr_raw["end"]),
                )
            memories = engine.storage.list_memories(
                search=arguments.get("search"),
                memory_type=arguments.get("type"),
                state=arguments.get("state"),
                tags=arguments.get("tags"),
                time_range=tr,
                importance_min=arguments.get("importance_min"),
                importance_max=arguments.get("importance_max"),
                limit=arguments.get("limit", 50),
                offset=arguments.get("offset", 0),
            )
            elapsed = (time.time() - start) * 1000
            return _response(
                {"memories": [m.model_dump() for m in memories]},
                elapsed,
            )

        elif name == "memory_archive":
            if "id" in arguments and arguments["id"]:
                success = engine.archive_memory(arguments["id"])
                elapsed = (time.time() - start) * 1000
                return _response({"archived": 1 if success else 0}, elapsed)
            elif "ids" in arguments and arguments["ids"]:
                count = engine.archive_bulk(arguments["ids"])
                elapsed = (time.time() - start) * 1000
                return _response({"archived": count}, elapsed)
            elif "below_retrievability" in arguments:
                count = engine.archive_below_retrievability(arguments["below_retrievability"])
                elapsed = (time.time() - start) * 1000
                return _response({"archived": count}, elapsed)
            return _error("Provide id, ids, or below_retrievability")

        elif name == "memory_restore":
            if "id" in arguments and arguments["id"]:
                mem = engine.restore_memory(arguments["id"])
                elapsed = (time.time() - start) * 1000
                return _response(mem.model_dump() if mem else None, elapsed)
            elif "ids" in arguments and arguments["ids"]:
                results = []
                for mid in arguments["ids"]:
                    mem = engine.restore_memory(mid)
                    if mem:
                        results.append(mem.id)
                elapsed = (time.time() - start) * 1000
                return _response({"restored": results}, elapsed)
            return _error("Provide id or ids")

        elif name == "memory_delete":
            if not arguments.get("confirm"):
                return _error("confirm must be true for permanent deletion")
            if "id" in arguments and arguments["id"]:
                success = engine.delete_memory(arguments["id"])
                elapsed = (time.time() - start) * 1000
                return _response({"deleted": 1 if success else 0}, elapsed)
            elif "ids" in arguments and arguments["ids"]:
                count = sum(1 for mid in arguments["ids"] if engine.delete_memory(mid))
                elapsed = (time.time() - start) * 1000
                return _response({"deleted": count}, elapsed)
            return _error("Provide id or ids")

        elif name == "memory_stats":
            stats = engine.get_stats()
            elapsed = (time.time() - start) * 1000
            return _response(stats, elapsed)

        elif name == "memory_consolidate":
            actions = engine.consolidate(dry_run=arguments.get("dry_run", False))
            elapsed = (time.time() - start) * 1000
            return _response({"actions": actions, "count": len(actions)}, elapsed)

        elif name == "memory_config":
            key = arguments.get("key")
            value = arguments.get("value")
            if key and value is not None:
                engine.set_config(key, value)
                elapsed = (time.time() - start) * 1000
                return _response({"key": key, "value": value, "action": "set"}, elapsed)
            elif key:
                result = engine.get_config(key)
                elapsed = (time.time() - start) * 1000
                return _response(result, elapsed)
            else:
                result = engine.get_config()
                elapsed = (time.time() - start) * 1000
                return _response(result, elapsed)

        else:
            return _error(f"Unknown tool: {name}")

    except Exception as e:
        return _error(str(e))


async def run() -> None:
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
