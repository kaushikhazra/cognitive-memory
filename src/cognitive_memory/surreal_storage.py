"""SurrealDB storage layer — replaces SQLite with embedded SurrealDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from surrealdb import Surreal

from .models import (
    ConsolidationLogEntry,
    Memory,
    MemoryState,
    MemoryType,
    MemoryVersion,
    RelType,
    Relationship,
)

SCHEMA_PATH = Path(__file__).parent / "schema.surql"

# Valid SurrealDB edge table names (one per RelType)
REL_TABLES = {
    "causes": "causes",
    "follows": "follows",
    "contradicts": "contradicts",
    "supports": "supports",
    "relates_to": "relates_to",
    "supersedes": "supersedes",
    "part_of": "part_of",
}


def _rid(table: str, record_id: str) -> str:
    """Build a SurrealDB record ID string like 'memory:abc123'."""
    return f"{table}:{record_id}"


def _extract_id(surreal_id) -> str:
    """Extract the plain ID string from a SurrealDB RecordID or string.

    SurrealDB wraps complex IDs (e.g., UUIDs) in angle brackets: memory:⟨uuid⟩
    This function strips both the table prefix and angle brackets.
    """
    s = str(surreal_id)
    if ":" in s:
        s = s.split(":", 1)[1]
    # Strip SurrealDB angle brackets (U+27E8 / U+27E9) used for complex record IDs
    return s.strip("\u27e8\u27e9")


def _to_iso(dt: datetime) -> str:
    """Convert datetime to ISO string for SurrealDB."""
    return dt.isoformat()


class SurrealStorage:
    """SurrealDB embedded storage backend for cognitive memory system."""

    def __init__(self, db_path: str = "mem://"):
        self._db_path = db_path
        self._db = Surreal(db_path)
        self._db.connect()
        self._db.use("cognitive", "memory")
        self._ensure_schema()

    def _rows(self, result) -> list[dict]:
        """Normalize SurrealDB query result to a flat list of dicts."""
        if not result:
            return []
        if isinstance(result, list):
            if result and isinstance(result[0], dict):
                return result  # Already a flat list of dicts
            # Nested list (multi-statement query)
            flat = []
            for item in result:
                if isinstance(item, list):
                    flat.extend(item)
                elif isinstance(item, dict):
                    if "result" in item:
                        flat.extend(item["result"] if isinstance(item["result"], list) else [item["result"]])
                    else:
                        flat.append(item)
            return flat
        if isinstance(result, dict):
            return [result]
        return []

    def _ensure_schema(self) -> None:
        """Apply schema (DEFINE statements are idempotent)."""
        schema_sql = SCHEMA_PATH.read_text()
        for stmt in schema_sql.split(";"):
            # Strip comment lines from each statement block
            lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("--")]
            clean = "\n".join(lines).strip()
            if clean:
                try:
                    self._db.query(clean)
                except Exception:
                    pass  # DEFINE statements may warn on re-apply

    def close(self) -> None:
        pass  # Embedded SurrealDB cleans up on GC

    # --- Memory CRUD ---

    def insert_memory(self, memory: Memory, embedding: list[float] | None = None) -> None:
        self._db.query(
            """CREATE type::thing('memory', $id) SET
                content = $content,
                memory_type = $memory_type,
                state = $state,
                importance = $importance,
                stability = $stability,
                retrievability = $retrievability,
                access_count = $access_count,
                created_at = $created_at,
                updated_at = $updated_at,
                last_accessed = $last_accessed,
                source = $source,
                conversation_id = $conversation_id,
                tags = $tags,
                embedding = $embedding
            """,
            {
                "id": memory.id,
                "content": memory.content,
                "memory_type": memory.memory_type.value,
                "state": memory.state.value,
                "importance": memory.importance,
                "stability": memory.stability,
                "retrievability": memory.retrievability,
                "access_count": memory.access_count,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
                "last_accessed": memory.last_accessed,
                "source": memory.source,
                "conversation_id": memory.conversation_id,
                "tags": memory.tags,
                "embedding": embedding,
            },
        )

    def get_memory(self, memory_id: str) -> Memory | None:
        result = self._db.query(
            "SELECT * FROM type::thing('memory', $id)",
            {"id": memory_id},
        )
        rows = self._rows(result)
        if not rows:
            return None
        return self._row_to_memory(rows[0])

    def update_memory_fields(self, memory_id: str, **fields) -> None:
        if not fields:
            return
        set_parts = []
        params = {"id": memory_id}
        for key, value in fields.items():
            param_name = f"f_{key}"
            if key == "memory_type" and isinstance(value, MemoryType):
                value = value.value
            elif key == "state" and isinstance(value, MemoryState):
                value = value.value
            # datetime objects are passed directly to SurrealDB SDK
            set_parts.append(f"{key} = ${param_name}")
            params[param_name] = value
        set_clause = ", ".join(set_parts)
        self._db.query(
            f"UPDATE type::thing('memory', $id) SET {set_clause}",
            params,
        )

    def update_embedding(self, memory_id: str, embedding: list[float]) -> None:
        self._db.query(
            "UPDATE type::thing('memory', $id) SET embedding = $embedding",
            {"id": memory_id, "embedding": embedding},
        )

    def delete_memory(self, memory_id: str) -> None:
        rid = _rid("memory", memory_id)
        # Delete all edges (each relationship type)
        for table in REL_TABLES.values():
            self._db.query(
                f"DELETE {table} WHERE in = type::thing('memory', $id) OR out = type::thing('memory', $id)",
                {"id": memory_id},
            )
        # Delete versions
        self._db.query(
            "DELETE memory_version WHERE memory_id = type::thing('memory', $id)",
            {"id": memory_id},
        )
        # Delete memory
        self._db.query(
            "DELETE type::thing('memory', $id)",
            {"id": memory_id},
        )

    def list_memories(
        self,
        search: str | None = None,
        memory_type: str | None = None,
        state: str | None = None,
        tags: list[str] | None = None,
        time_range: tuple[datetime, datetime] | None = None,
        importance_min: float | None = None,
        importance_max: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        conditions = []
        params: dict[str, Any] = {}

        if search:
            conditions.append("content @@ $search")
            params["search"] = search

        if memory_type:
            conditions.append("memory_type = $mtype")
            params["mtype"] = memory_type

        if state:
            conditions.append("state = $state")
            params["state"] = state

        if tags:
            for i, tag in enumerate(tags):
                conditions.append(f"$tag_{i} IN tags")
                params[f"tag_{i}"] = tag

        if time_range:
            conditions.append("created_at >= $t_start AND created_at <= $t_end")
            params["t_start"] = _to_iso(time_range[0])
            params["t_end"] = _to_iso(time_range[1])

        if importance_min is not None:
            conditions.append("importance >= $imp_min")
            params["imp_min"] = importance_min

        if importance_max is not None:
            conditions.append("importance <= $imp_max")
            params["imp_max"] = importance_max

        where = " AND ".join(conditions) if conditions else "true"
        params["lim"] = limit
        params["off"] = offset

        result = self._db.query(
            f"SELECT * FROM memory WHERE {where} ORDER BY created_at DESC LIMIT $lim START $off",
            params,
        )
        rows = self._rows(result)
        return [self._row_to_memory(r) for r in rows]

    def get_all_active_memories(self) -> list[Memory]:
        result = self._db.query("SELECT * FROM memory WHERE state = 'active'")
        rows = self._rows(result)
        return [self._row_to_memory(r) for r in rows]

    def fts_search(self, query: str, state: str = "active", limit: int = 30) -> list[tuple[str, float]]:
        result = self._db.query(
            """SELECT id, search::score(1) AS score
               FROM memory
               WHERE content @1@ $query AND state = $state
               ORDER BY score DESC
               LIMIT $lim""",
            {"query": query, "state": state, "lim": limit},
        )
        rows = self._rows(result)
        return [(_extract_id(r["id"]), r["score"]) for r in rows]

    def vector_search(self, embedding: list[float], state: str = "active", top_k: int = 30) -> list[tuple[str, float]]:
        """Vector similarity search using SurrealDB HNSW index."""
        result = self._db.query(
            """SELECT id, vector::similarity::cosine(embedding, $vec) AS score
               FROM memory
               WHERE state = $state AND embedding != NONE
               ORDER BY score DESC
               LIMIT $top_k""",
            {"vec": embedding, "state": state, "top_k": top_k},
        )
        rows = self._rows(result)
        return [(_extract_id(r["id"]), r["score"]) for r in rows]

    def vector_search_for_memory(self, memory_id: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar memories to an existing memory by its stored embedding."""
        result = self._db.query(
            """LET $vec = (SELECT embedding FROM type::thing('memory', $id))[0].embedding;
               SELECT id, vector::similarity::cosine(embedding, $vec) AS score
               FROM memory
               WHERE state = 'active' AND embedding != NONE AND id != type::thing('memory', $id)
               ORDER BY score DESC
               LIMIT $top_k""",
            {"id": memory_id, "top_k": top_k},
        )
        # Result may be nested due to LET
        rows = result[-1] if result else []
        if isinstance(rows, dict):
            rows = [rows]
        return [(_extract_id(r["id"]), r["score"]) for r in rows if "score" in r]

    # --- Memory Versions ---

    def insert_version(self, version: MemoryVersion) -> None:
        self._db.query(
            """CREATE type::thing('memory_version', $id) SET
                memory_id = type::thing('memory', $mem_id),
                content = $content,
                metadata = $metadata,
                created_at = $created_at
            """,
            {
                "id": version.id,
                "mem_id": version.memory_id,
                "content": version.content,
                "metadata": version.metadata,
                "created_at": version.created_at,
            },
        )

    def get_versions(self, memory_id: str) -> list[MemoryVersion]:
        result = self._db.query(
            "SELECT * FROM memory_version WHERE memory_id = type::thing('memory', $id) ORDER BY created_at DESC",
            {"id": memory_id},
        )
        rows = self._rows(result)
        return [
            MemoryVersion(
                id=_extract_id(r["id"]),
                memory_id=memory_id,
                content=r["content"],
                metadata=r.get("metadata"),
                created_at=self._parse_dt(r["created_at"]),
            )
            for r in rows
        ]

    # --- Relationships ---

    def insert_relationship(self, rel: Relationship) -> None:
        table = REL_TABLES[rel.rel_type.value]
        self._db.query(
            f"""LET $from = type::thing('memory', $src);
                LET $to = type::thing('memory', $tgt);
                RELATE $from->{table}->$to
                SET strength = $strength, created_at = $created_at""",
            {
                "src": rel.source_id,
                "tgt": rel.target_id,
                "strength": rel.strength,
                "created_at": rel.created_at,
            },
        )

    def delete_relationship(self, source_id: str, target_id: str, rel_type: str) -> bool:
        table = REL_TABLES[rel_type]
        result = self._db.query(
            f"DELETE {table} WHERE in = type::thing('memory', $src) AND out = type::thing('memory', $tgt)",
            {"src": source_id, "tgt": target_id},
        )
        return True  # SurrealDB DELETE doesn't return rowcount easily

    def get_relationships_for(self, memory_id: str, rel_types: list[str] | None = None) -> list[Relationship]:
        tables = [REL_TABLES[rt] for rt in rel_types] if rel_types else list(REL_TABLES.values())
        all_rels = []
        for table in tables:
            result = self._db.query(
                f"SELECT * FROM {table} WHERE in = type::thing('memory', $id) OR out = type::thing('memory', $id)",
                {"id": memory_id},
            )
            rows = self._rows(result)
            for r in rows:
                all_rels.append(self._row_to_relationship(r, table))
        return all_rels

    def get_outgoing_relationships(self, memory_id: str) -> list[Relationship]:
        all_rels = []
        for table in REL_TABLES.values():
            result = self._db.query(
                f"SELECT * FROM {table} WHERE in = type::thing('memory', $id)",
                {"id": memory_id},
            )
            rows = self._rows(result)
            for r in rows:
                all_rels.append(self._row_to_relationship(r, table))
        return all_rels

    def get_incoming_relationships(self, memory_id: str, rel_type: str | None = None) -> list[Relationship]:
        tables = [REL_TABLES[rel_type]] if rel_type else list(REL_TABLES.values())
        all_rels = []
        for table in tables:
            result = self._db.query(
                f"SELECT * FROM {table} WHERE out = type::thing('memory', $id)",
                {"id": memory_id},
            )
            rows = self._rows(result)
            for r in rows:
                all_rels.append(self._row_to_relationship(r, table))
        return all_rels

    def get_neighbors(self, memory_id: str, active_only: bool = True) -> list[tuple[str, Relationship]]:
        results = []
        for table in REL_TABLES.values():
            for r in self._rows(self._db.query(
                f"SELECT *, out.state AS neighbor_state FROM {table} WHERE in = type::thing('memory', $id)",
                {"id": memory_id},
            )):
                if active_only and r.get("neighbor_state") != "active":
                    continue
                neighbor_id = _extract_id(r["out"])
                results.append((neighbor_id, self._row_to_relationship(r, table)))

            for r in self._rows(self._db.query(
                f"SELECT *, in.state AS neighbor_state FROM {table} WHERE out = type::thing('memory', $id)",
                {"id": memory_id},
            )):
                if active_only and r.get("neighbor_state") != "active":
                    continue
                neighbor_id = _extract_id(r["in"])
                results.append((neighbor_id, self._row_to_relationship(r, table)))
        return results

    def delete_auto_links(self, memory_id: str) -> None:
        self._db.query(
            "DELETE relates_to WHERE in = type::thing('memory', $id) AND strength < 1.0",
            {"id": memory_id},
        )

    def bulk_update_stability(self, updates: list[tuple[float, str]]) -> None:
        for new_stability, mem_id in updates:
            self._db.query(
                "UPDATE type::thing('memory', $id) SET stability = $s",
                {"id": mem_id, "s": new_stability},
            )

    def has_incoming_supersedes(self, memory_id: str) -> bool:
        result = self._db.query(
            """SELECT count() AS cnt FROM supersedes
               WHERE out = type::thing('memory', $id) AND in.state = 'active'
               GROUP ALL""",
            {"id": memory_id},
        )
        rows = self._rows(result)
        if rows and isinstance(rows, list) and len(rows) > 0:
            return rows[0].get("cnt", 0) > 0
        return False

    def get_contradictions_for(self, memory_id: str) -> list[tuple[str, str, float]]:
        result = self._db.query(
            """SELECT out AS other_id, out.content AS other_content, strength
               FROM contradicts WHERE in = type::thing('memory', $id) AND out.state = 'active'""",
            {"id": memory_id},
        )
        rows_out = self._rows(result)

        rows_in = self._rows(self._db.query(
            """SELECT in AS other_id, in.content AS other_content, strength
               FROM contradicts WHERE out = type::thing('memory', $id) AND in.state = 'active'""",
            {"id": memory_id},
        ))

        all_rows = rows_out + rows_in
        return [
            (_extract_id(r["other_id"]), str(r.get("other_content", ""))[:100], r["strength"])
            for r in all_rows
        ]

    # --- Consolidation Log ---

    def insert_consolidation_log(self, entry: ConsolidationLogEntry) -> None:
        self._db.query(
            """CREATE type::thing('consolidation_log', $id) SET
                action = $action,
                source_ids = $source_ids,
                target_id = $target_id,
                reason = $reason,
                created_at = $created_at
            """,
            {
                "id": entry.id,
                "action": entry.action,
                "source_ids": entry.source_ids,
                "target_id": entry.target_id,
                "reason": entry.reason,
                "created_at": entry.created_at,
            },
        )

    def get_last_consolidation(self) -> dict | None:
        result = self._db.query(
            "SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT 1"
        )
        rows = self._rows(result)
        if not rows:
            return None
        r = rows[0]
        return {
            "id": _extract_id(r["id"]),
            "action": r["action"],
            "source_ids": r["source_ids"],
            "target_id": r.get("target_id"),
            "reason": r["reason"],
            "created_at": str(r["created_at"]),
        }

    def get_consolidation_summary(self) -> dict:
        last = self.get_last_consolidation()
        if last is None:
            return {"last_run": None, "promoted": 0, "merged": 0, "archived": 0}

        last_run = last["created_at"]
        result = self._db.query(
            "SELECT action, count() AS cnt FROM consolidation_log WHERE created_at >= $since GROUP BY action",
            {"since": last_run},
        )
        rows = self._rows(result)
        summary = {"last_run": last_run, "promoted": 0, "merged": 0, "archived": 0}
        for row in rows:
            action = row.get("action")
            cnt = row.get("cnt", 0)
            if action == "promote":
                summary["promoted"] = cnt
            elif action == "merge":
                summary["merged"] = cnt
            elif action == "archive":
                summary["archived"] = cnt
        return summary

    # --- Config ---

    def get_config(self, key: str) -> Any | None:
        result = self._db.query(
            "SELECT val FROM preference WHERE id = type::thing('preference', $key)",
            {"key": key},
        )
        rows = self._rows(result)
        if not rows:
            return None
        return rows[0].get("val")

    def set_config(self, key: str, value: Any) -> None:
        now = datetime.now(timezone.utc)
        self._db.query(
            """UPSERT type::thing('preference', $key) SET
                val = $val,
                updated_at = $now
            """,
            {"key": key, "val": value, "now": now},
        )

    def get_all_config(self) -> dict[str, Any]:
        result = self._db.query("SELECT * FROM preference")
        rows = self._rows(result)
        return {_extract_id(r["id"]): r["val"] for r in rows}

    # --- Stats helpers ---

    def get_counts_by_type(self) -> dict[str, int]:
        result = self._db.query(
            "SELECT memory_type, count() AS cnt FROM memory GROUP BY memory_type"
        )
        rows = self._rows(result)
        return {r["memory_type"]: r["cnt"] for r in rows}

    def get_counts_by_state(self) -> dict[str, int]:
        result = self._db.query(
            "SELECT state, count() AS cnt FROM memory GROUP BY state"
        )
        rows = self._rows(result)
        return {r["state"]: r["cnt"] for r in rows}

    def get_total_memory_count(self) -> int:
        result = self._db.query("SELECT count() AS cnt FROM memory GROUP ALL")
        rows = self._rows(result)
        if rows and isinstance(rows, list) and len(rows) > 0:
            return rows[0].get("cnt", 0)
        return 0

    def get_db_size(self) -> int:
        if self._db_path.startswith("mem://"):
            return 0
        # For file-based, estimate from the data directory
        data_path = self._db_path.replace("surrealkv://", "").replace("file://", "")
        p = Path(data_path)
        if p.exists():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return 0

    # --- Internal helpers ---

    def _parse_dt(self, val) -> datetime:
        """Parse datetime from SurrealDB — may be datetime object or ISO string."""
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(str(val))

    def _row_to_memory(self, row: dict) -> Memory:
        return Memory(
            id=_extract_id(row["id"]),
            content=row["content"],
            memory_type=MemoryType(row["memory_type"]),
            state=MemoryState(row["state"]),
            importance=row["importance"],
            stability=row["stability"],
            retrievability=row["retrievability"],
            access_count=row["access_count"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
            last_accessed=self._parse_dt(row["last_accessed"]),
            source=row.get("source"),
            conversation_id=row.get("conversation_id"),
            tags=row.get("tags", []),
        )

    def _row_to_relationship(self, row: dict, table: str) -> Relationship:
        return Relationship(
            id=_extract_id(row["id"]),
            source_id=_extract_id(row["in"]),
            target_id=_extract_id(row["out"]),
            rel_type=RelType(table),
            strength=row.get("strength", 1.0),
            created_at=self._parse_dt(row["created_at"]),
        )
