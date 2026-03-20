"""MCP stdio test client — spawns the server and exercises all 14 tools."""

from __future__ import annotations

import asyncio
import json
import sys
import os
from pathlib import Path

# Set up environment for in-memory DB
os.environ["COGNITIVE_MEMORY_DB"] = ":memory:"

# We need to handle the case where mcp might not be installed
try:
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.session import ClientSession
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    print("MCP SDK not installed. Install with: pip install 'mcp>=1.0.0'")


async def run_mcp_tests():
    """Connect to the cognitive-memory server and exercise all tools."""
    # Spawn the mock server wrapper which patches sentence-transformers
    # with a deterministic mock before starting the real MCP server.
    mock_server = str(Path(__file__).parent / "_mock_server.py")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[mock_server],
        env={
            **os.environ,
            "COGNITIVE_MEMORY_DB": ":memory:",
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List tools
            tools = await session.list_tools()
            print(f"Available tools: {len(tools.tools)}")
            for t in tools.tools:
                print(f"  - {t.name}")

            assert len(tools.tools) == 14, f"Expected 14 tools, got {len(tools.tools)}"
            print(f"\nPASS: 14 tools registered")

            # memory_store
            result = await session.call_tool("memory_store", {
                "content": "Python is a versatile programming language",
                "type": "semantic",
                "tags": ["programming", "python"],
            })
            store_data = json.loads(result.content[0].text)
            assert store_data["success"], f"Store failed: {store_data}"
            memory_id = store_data["data"]["id"]
            print(f"PASS: memory_store — id={memory_id[:8]}...")

            # memory_get
            result = await session.call_tool("memory_get", {"id": memory_id})
            get_data = json.loads(result.content[0].text)
            assert get_data["success"]
            assert get_data["data"]["memory"]["content"] == "Python is a versatile programming language"
            print(f"PASS: memory_get — content matches")

            # memory_update
            result = await session.call_tool("memory_update", {
                "id": memory_id,
                "content": "Python is a versatile and popular programming language",
            })
            update_data = json.loads(result.content[0].text)
            assert update_data["success"]
            print(f"PASS: memory_update — content updated")

            # Verify version was created
            result = await session.call_tool("memory_get", {"id": memory_id})
            get_data = json.loads(result.content[0].text)
            versions = get_data["data"].get("versions", [])
            assert len(versions) >= 1, f"Expected version, got {len(versions)}"
            print(f"PASS: memory_get — version history present ({len(versions)} versions)")

            # Store more for recall testing
            result = await session.call_tool("memory_store", {
                "content": "JavaScript is the language of the web",
                "type": "semantic",
            })
            js_data = json.loads(result.content[0].text)
            js_id = js_data["data"]["id"]

            # memory_recall
            result = await session.call_tool("memory_recall", {
                "query": "programming language",
                "limit": 5,
            })
            recall_data = json.loads(result.content[0].text)
            assert recall_data["success"]
            memories = recall_data["data"]["memories"]
            assert len(memories) > 0, "Recall returned no results"
            assert all("score" in m for m in memories)
            assert all("found_by" in m for m in memories)
            print(f"PASS: memory_recall — {len(memories)} results with scores and provenance")

            # memory_relate
            result = await session.call_tool("memory_relate", {
                "source_id": memory_id,
                "target_id": js_id,
                "rel_type": "relates_to",
                "strength": 1.0,
            })
            relate_data = json.loads(result.content[0].text)
            assert relate_data["success"]
            print(f"PASS: memory_relate — relationship created")

            # memory_related (read-only)
            result = await session.call_tool("memory_related", {
                "id": memory_id,
                "depth": 1,
            })
            related_data = json.loads(result.content[0].text)
            assert related_data["success"]
            print(f"PASS: memory_related — {len(related_data['data'])} neighbors found")

            # memory_unrelate
            result = await session.call_tool("memory_unrelate", {
                "source_id": memory_id,
                "target_id": js_id,
                "rel_type": "relates_to",
            })
            unrelate_data = json.loads(result.content[0].text)
            assert unrelate_data["success"]
            print(f"PASS: memory_unrelate — relationship removed")

            # memory_list
            result = await session.call_tool("memory_list", {
                "type": "semantic",
                "limit": 10,
            })
            list_data = json.loads(result.content[0].text)
            assert list_data["success"]
            assert len(list_data["data"]["memories"]) >= 2
            print(f"PASS: memory_list — {len(list_data['data']['memories'])} memories listed")

            # memory_archive
            result = await session.call_tool("memory_archive", {"id": js_id})
            archive_data = json.loads(result.content[0].text)
            assert archive_data["success"]
            assert archive_data["data"]["archived"] == 1
            print(f"PASS: memory_archive — 1 memory archived")

            # memory_restore
            result = await session.call_tool("memory_restore", {"id": js_id})
            restore_data = json.loads(result.content[0].text)
            assert restore_data["success"]
            print(f"PASS: memory_restore — memory restored")

            # memory_stats
            result = await session.call_tool("memory_stats", {})
            stats_data = json.loads(result.content[0].text)
            assert stats_data["success"]
            assert "counts" in stats_data["data"]
            assert "decay" in stats_data["data"]
            print(f"PASS: memory_stats — complete stats returned")

            # memory_consolidate (dry run)
            result = await session.call_tool("memory_consolidate", {"dry_run": True})
            consol_data = json.loads(result.content[0].text)
            assert consol_data["success"]
            print(f"PASS: memory_consolidate — dry run returned {consol_data['data']['count']} actions")

            # memory_config
            result = await session.call_tool("memory_config", {
                "key": "decay.growth_factor",
                "value": 3.0,
            })
            config_data = json.loads(result.content[0].text)
            assert config_data["success"]
            print(f"PASS: memory_config — set growth_factor=3.0")

            # Read it back
            result = await session.call_tool("memory_config", {"key": "decay.growth_factor"})
            config_data = json.loads(result.content[0].text)
            assert config_data["data"]["value"] == 3.0
            print(f"PASS: memory_config — read back confirms 3.0")

            # memory_delete
            result = await session.call_tool("memory_delete", {"id": js_id, "confirm": True})
            delete_data = json.loads(result.content[0].text)
            assert delete_data["success"]
            assert delete_data["data"]["deleted"] == 1
            print(f"PASS: memory_delete — memory permanently deleted")

            # Verify deleted
            result = await session.call_tool("memory_get", {"id": js_id})
            get_data = json.loads(result.content[0].text)
            assert not get_data["success"]
            print(f"PASS: memory_get after delete — correctly returns error")

            print(f"\n{'='*60}")
            print(f"ALL MCP TOOL TESTS PASSED")


if __name__ == "__main__":
    if not HAS_MCP:
        sys.exit(1)
    asyncio.run(run_mcp_tests())
