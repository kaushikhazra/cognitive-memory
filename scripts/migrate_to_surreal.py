"""Migrate cognitive memory data from SQLite to SurrealDB.

Reads the existing SQLite database (read-only) and writes to SurrealDB
in order: config → memories → versions → relationships.

Usage:
    python scripts/migrate_to_surreal.py [--source PATH] [--target PATH] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure the source package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_memory.models import (
    ConsolidationLogEntry,
    Memory,
    MemoryState,
    MemoryType,
    MemoryVersion,
    RelType,
    Relationship,
)
from cognitive_memory.surreal_storage import SurrealStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate")

BATCH_SIZE = 100


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate cognitive memory from SQLite to SurrealDB")
    p.add_argument(
        "--source",
        default=str(Path.home() / ".cognitive-memory" / "memory.db"),
        help="Source SQLite database path (default: ~/.cognitive-memory/memory.db)",
    )
    p.add_argument(
        "--target",
        default=str(Path.home() / ".cognitive-memory" / "data"),
        help="Target SurrealDB data directory (default: ~/.cognitive-memory/data)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Wipe target DB if non-empty and re-migrate",
    )
    return p.parse_args()


def open_sqlite(path: str) -> sqlite3.Connection:
    """Open SQLite DB in read-only mode."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_surreal(target_path: str) -> SurrealStorage:
    """Open SurrealDB embedded storage."""
    if not target_path.startswith(("mem://", "surrealkv://", "file://")):
        Path(target_path).mkdir(parents=True, exist_ok=True)
        # SurrealDB URL parser requires forward slashes (Windows backslashes break it)
        target_path = f"surrealkv://{target_path.replace(os.sep, '/')}"
    return SurrealStorage(db_path=target_path)


def check_target_empty(surreal: SurrealStorage, force: bool) -> None:
    """Abort if target has data, unless --force."""
    count = surreal.get_total_memory_count()
    if count > 0:
        if not force:
            log.error(f"Target DB already has {count} memories. Use --force to wipe and re-migrate.")
            sys.exit(1)
        log.warning(f"Target has {count} memories. --force specified, wiping...")
        surreal._db.query("DELETE memory")
        surreal._db.query("DELETE memory_version")
        surreal._db.query("DELETE preference")
        surreal._db.query("DELETE consolidation_log")
        for table in ["causes", "follows", "contradicts", "supports", "relates_to", "supersedes", "part_of"]:
            surreal._db.query(f"DELETE {table}")
        log.info("Target wiped.")


def migrate_config(src: sqlite3.Connection, surreal: SurrealStorage) -> int:
    """Migrate config overrides from SQLite to SurrealDB preference table."""
    try:
        rows = src.execute("SELECT key, value FROM config").fetchall()
    except sqlite3.OperationalError:
        log.info("No config table in source DB, skipping.")
        return 0

    count = 0
    for row in rows:
        key = row["key"]
        try:
            value = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            value = row["value"]
        surreal.set_config(key, value)
        count += 1

    log.info(f"Migrated {count} config entries.")
    return count


def migrate_memories(src: sqlite3.Connection, surreal: SurrealStorage) -> tuple[int, int]:
    """Migrate memory records with embedding conversion. Returns (migrated, failed)."""
    rows = src.execute("SELECT * FROM memory").fetchall()
    total = len(rows)
    migrated = 0
    failed = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        for row in batch:
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
                memory = Memory(
                    id=row["id"],
                    content=row["content"],
                    memory_type=MemoryType(row["memory_type"]),
                    state=MemoryState(row["state"]),
                    importance=row["importance"],
                    stability=row["stability"],
                    retrievability=row["retrievability"],
                    access_count=row["access_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    last_accessed=datetime.fromisoformat(row["last_accessed"]),
                    source=row["source"],
                    conversation_id=row["conversation_id"],
                    tags=tags,
                )

                # Convert embedding BLOB → list[float]
                embedding_list = None
                if row["embedding"]:
                    embedding_array = np.frombuffer(row["embedding"], dtype=np.float32).copy()
                    embedding_list = embedding_array.astype(float).tolist()

                surreal.insert_memory(memory, embedding_list)
                migrated += 1
            except Exception as e:
                log.error(f"Failed to migrate memory {row['id']}: {e}")
                failed += 1

        log.info(f"Migrating memories: {min(i + BATCH_SIZE, total)}/{total}")

    log.info(f"Memories: {migrated} migrated, {failed} failed out of {total}.")
    return migrated, failed


def migrate_versions(src: sqlite3.Connection, surreal: SurrealStorage) -> tuple[int, int]:
    """Migrate memory version snapshots. Returns (migrated, failed)."""
    try:
        rows = src.execute("SELECT * FROM memory_version").fetchall()
    except sqlite3.OperationalError:
        log.info("No memory_version table in source DB, skipping.")
        return 0, 0

    total = len(rows)
    migrated = 0
    failed = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        for row in batch:
            try:
                metadata = json.loads(row["metadata"]) if row["metadata"] else None
                version = MemoryVersion(
                    id=row["id"],
                    memory_id=row["memory_id"],
                    content=row["content"],
                    metadata=metadata,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                surreal.insert_version(version)
                migrated += 1
            except Exception as e:
                log.error(f"Failed to migrate version {row['id']}: {e}")
                failed += 1

        log.info(f"Migrating versions: {min(i + BATCH_SIZE, total)}/{total}")

    log.info(f"Versions: {migrated} migrated, {failed} failed out of {total}.")
    return migrated, failed


def migrate_relationships(src: sqlite3.Connection, surreal: SurrealStorage) -> tuple[int, int]:
    """Migrate relationship records. Returns (migrated, failed)."""
    try:
        rows = src.execute("SELECT * FROM relationship").fetchall()
    except sqlite3.OperationalError:
        log.info("No relationship table in source DB, skipping.")
        return 0, 0

    total = len(rows)
    migrated = 0
    failed = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        for row in batch:
            try:
                rel = Relationship(
                    id=row["id"],
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    rel_type=RelType(row["rel_type"]),
                    strength=row["strength"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                surreal.insert_relationship(rel)
                migrated += 1
            except Exception as e:
                log.error(f"Failed to migrate relationship {row['id']}: {e}")
                failed += 1

        log.info(f"Migrating relationships: {min(i + BATCH_SIZE, total)}/{total}")

    log.info(f"Relationships: {migrated} migrated, {failed} failed out of {total}.")
    return migrated, failed


def verify(src: sqlite3.Connection, surreal: SurrealStorage) -> bool:
    """Verify migration: count comparison + spot-check."""
    ok = True

    # Count comparison
    src_count = src.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
    tgt_count = surreal.get_total_memory_count()
    if src_count != tgt_count:
        log.warning(f"Memory count mismatch: source={src_count}, target={tgt_count}")
        ok = False
    else:
        log.info(f"Memory count verified: {tgt_count}")

    # Spot-check 5 random memories
    src_ids = [r[0] for r in src.execute("SELECT id FROM memory").fetchall()]
    sample_size = min(5, len(src_ids))
    if sample_size > 0:
        sample_ids = random.sample(src_ids, sample_size)
        for mid in sample_ids:
            src_row = src.execute("SELECT content, memory_type, state FROM memory WHERE id = ?", (mid,)).fetchone()
            tgt_mem = surreal.get_memory(mid)
            if tgt_mem is None:
                log.warning(f"Spot-check FAIL: memory {mid} not found in target")
                ok = False
            elif tgt_mem.content != src_row["content"]:
                log.warning(f"Spot-check FAIL: memory {mid} content mismatch")
                ok = False
            else:
                log.info(f"Spot-check OK: {mid[:8]}...")

    return ok


def main():
    args = parse_args()
    log.info(f"Source: {args.source}")
    log.info(f"Target: {args.target}")

    if not Path(args.source).exists():
        log.error(f"Source database not found: {args.source}")
        sys.exit(1)

    src = open_sqlite(args.source)
    surreal = open_surreal(args.target)
    check_target_empty(surreal, args.force)

    total_failed = 0

    # Migrate in order: config → memories → versions → relationships
    migrate_config(src, surreal)

    _, mem_failed = migrate_memories(src, surreal)
    total_failed += mem_failed

    _, ver_failed = migrate_versions(src, surreal)
    total_failed += ver_failed

    _, rel_failed = migrate_relationships(src, surreal)
    total_failed += rel_failed

    # Verification
    log.info("Running verification...")
    verified = verify(src, surreal)

    src.close()
    surreal.close()

    if total_failed > 0:
        log.error(f"Migration completed with {total_failed} failures.")
        sys.exit(1)
    elif not verified:
        log.warning("Migration completed but verification had warnings.")
        sys.exit(1)
    else:
        log.info("Migration completed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
