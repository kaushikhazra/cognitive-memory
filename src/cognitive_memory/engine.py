"""Memory engine — orchestrates ingestion, update, restore, delete, and retrieval."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from . import decay as decay_mod
from . import retrieval as retrieval_mod
from . import consolidation as consolidation_mod
from .classification import classify, score_importance
from .config import Config
from .embeddings import EmbeddingService
from .models import (
    ContradictionInfo,
    Memory,
    MemoryGetResponse,
    MemoryState,
    MemoryType,
    MemoryVersion,
    RelType,
    Relationship,
    RelationshipInfo,
    RecallResult,
    StatsResponse,
    ToolResponse,
)
from .storage import Storage


class MemoryEngine:
    """Central orchestrator for the cognitive memory system."""

    def __init__(self, db_path: str = ":memory:", config_path: Path | None = None):
        self.storage = Storage(db_path)
        self.config = Config(storage=self.storage, config_path=config_path)
        self.embeddings = EmbeddingService()
        self._load_embedding_matrix()

    def _load_embedding_matrix(self) -> None:
        """Load all active embeddings into the in-memory numpy matrix."""
        active_embeddings = self.storage.get_active_embeddings()
        self.embeddings.load_matrix(active_embeddings)

    def close(self) -> None:
        self.storage.close()

    # === Ingestion ===

    def store_memory(
        self,
        content: str,
        memory_type: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        conversation_id: str | None = None,
    ) -> Memory:
        """Store a new memory with classification, embedding, auto-linking, and contradiction check."""
        now = datetime.now(timezone.utc)
        memory_id = str(uuid.uuid4())

        # Step 1: Classification
        if memory_type:
            mem_type = MemoryType(memory_type)
            confidence = 1.0
        else:
            mem_type, confidence = classify(content, source)

        # Step 2: Importance scoring
        importance_cfg = {
            "base_score": self.config.get("importance.base_score", 0.5),
            "named_entity_bonus": self.config.get("importance.named_entity_bonus", 0.1),
            "relational_bonus": self.config.get("importance.relational_bonus", 0.1),
            "length_bonus": self.config.get("importance.length_bonus", 0.1),
            "length_threshold": self.config.get("importance.length_threshold", 200),
            "working_penalty": self.config.get("importance.working_penalty", 0.1),
            "min": self.config.get("importance.min", 0.1),
            "max": self.config.get("importance.max", 1.0),
        }
        imp = score_importance(content, mem_type, importance, importance_cfg)

        # Step 3: Embedding
        embedding = self.embeddings.embed(content)
        embedding_bytes = self.embeddings.to_bytes(embedding)

        # Initial decay values
        s0 = decay_mod.get_initial_stability(mem_type.value)

        memory = Memory(
            id=memory_id,
            content=content,
            memory_type=mem_type,
            state=MemoryState.ACTIVE,
            importance=imp,
            stability=s0,
            retrievability=1.0,
            access_count=0,
            created_at=now,
            updated_at=now,
            last_accessed=now,
            source=source,
            conversation_id=conversation_id,
            tags=tags or [],
        )

        # Step 6: Store
        self.storage.insert_memory(memory, embedding_bytes)
        self.embeddings.add_to_matrix(memory_id, embedding)

        # Step 4: Auto-linking
        self._auto_link(memory_id, embedding, now)

        # Step 5: Contradiction check
        self._contradiction_check(memory_id, embedding, content, now)

        return memory

    def _auto_link(self, memory_id: str, embedding: np.ndarray, now: datetime) -> None:
        """Find similar active memories and create relates_to links."""
        threshold = self.config.get("auto_linking.similarity_threshold", 0.75)
        max_links = self.config.get("auto_linking.max_links", 5)

        results = self.embeddings.cosine_search(embedding, top_k=max_links + 1)
        linked = 0
        for mid, score in results:
            if mid == memory_id:
                continue
            if score < threshold:
                continue
            if linked >= max_links:
                break

            rel = Relationship(
                id=str(uuid.uuid4()),
                source_id=memory_id,
                target_id=mid,
                rel_type=RelType.RELATES_TO,
                strength=score,  # cosine score as strength (< 1.0 = auto-created)
                created_at=now,
            )
            self.storage.insert_relationship(rel)
            linked += 1

    def _contradiction_check(self, memory_id: str, embedding: np.ndarray, content: str, now: datetime) -> None:
        """Check for contradictions with existing memories."""
        threshold = self.config.get("contradiction.similarity_threshold", 0.80)
        negation_signals = self.config.get("contradiction.negation_signals", [
            "not", "never", "no longer", "changed", "wrong", "actually",
        ])

        results = self.embeddings.cosine_search(embedding, top_k=10)
        for mid, score in results:
            if mid == memory_id:
                continue
            if score < threshold:
                continue

            other = self.storage.get_memory(mid)
            if other is None:
                continue

            combined = (content + " " + other.content).lower()
            if any(signal in combined for signal in negation_signals):
                rel = Relationship(
                    id=str(uuid.uuid4()),
                    source_id=memory_id,
                    target_id=mid,
                    rel_type=RelType.CONTRADICTS,
                    strength=score,
                    created_at=now,
                )
                self.storage.insert_relationship(rel)

    # === Update ===

    def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        memory_type: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
    ) -> Memory | None:
        """Update a memory with versioning, re-embedding, reinforcement."""
        mem = self.storage.get_memory(memory_id)
        if mem is None:
            return None

        now = datetime.now(timezone.utc)
        content_changed = content is not None and content != mem.content
        type_changed = memory_type is not None and memory_type != mem.memory_type.value

        # Step 1: Version snapshot
        version = MemoryVersion(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            content=mem.content,
            metadata={
                "changed": [],
                **({"old_content": mem.content[:200]} if content_changed else {}),
                **({"old_type": mem.memory_type.value} if type_changed else {}),
            },
            created_at=now,
        )
        if content_changed:
            version.metadata["changed"].append("content")
        if type_changed:
            version.metadata["changed"].append("type")
        if importance is not None:
            version.metadata["changed"].append("importance")
        if tags is not None:
            version.metadata["changed"].append("tags")
        self.storage.insert_version(version)

        # Step 2: Apply changes
        fields = {}
        if content is not None:
            fields["content"] = content
        if memory_type is not None:
            fields["memory_type"] = MemoryType(memory_type)
        if importance is not None:
            fields["importance"] = max(0.1, min(1.0, importance))
        if tags is not None:
            fields["tags"] = tags

        # Step 3: Re-embed if content changed
        if content_changed:
            new_embedding = self.embeddings.embed(content)
            embedding_bytes = self.embeddings.to_bytes(new_embedding)
            self.storage.update_embedding(memory_id, embedding_bytes)
            self.embeddings.replace_in_matrix(memory_id, new_embedding)

        # Step 4: Reinforce (or reset stability on type change)
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
        if type_changed:
            fields["stability"] = decay_mod.get_initial_stability(memory_type)
        else:
            growth_factor = self.config.get("decay.growth_factor", 2.0)
            fields["stability"] = decay_mod.reinforce(mem.stability, r, growth_factor)

        # Step 5: Timestamps
        fields["updated_at"] = now
        fields["last_accessed"] = now

        self.storage.update_memory_fields(memory_id, **fields)

        # Step 6: Re-scan auto-links if content changed
        if content_changed:
            self.storage.delete_auto_links(memory_id)
            new_embedding = self.embeddings.embed(content)
            self._auto_link(memory_id, new_embedding, now)

        return self.storage.get_memory(memory_id)

    # === Restore ===

    def restore_memory(self, memory_id: str) -> Memory | None:
        """Restore an archived memory with decay reset."""
        mem = self.storage.get_memory(memory_id)
        if mem is None or mem.state != MemoryState.ARCHIVED:
            return None

        now = datetime.now(timezone.utc)
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
        growth_factor = self.config.get("decay.growth_factor", 2.0)
        new_stability = decay_mod.reinforce(mem.stability, r, growth_factor)

        self.storage.update_memory_fields(
            memory_id,
            state=MemoryState.ACTIVE,
            last_accessed=now,
            stability=new_stability,
            updated_at=now,
        )

        # Re-add to numpy matrix
        active_embeddings = self.storage.get_active_embeddings()
        if memory_id in active_embeddings:
            self.embeddings.add_to_matrix(memory_id, active_embeddings[memory_id])

        return self.storage.get_memory(memory_id)

    # === Delete ===

    def delete_memory(self, memory_id: str) -> bool:
        """Permanently delete a memory with full cascade."""
        mem = self.storage.get_memory(memory_id)
        if mem is None:
            return False

        self.embeddings.remove_from_matrix(memory_id)
        self.storage.delete_memory(memory_id)
        return True

    # === Retrieval ===

    def recall(
        self,
        query: str,
        type_filter: str | None = None,
        tags: list[str] | None = None,
        time_range: tuple[datetime, datetime] | None = None,
        limit: int | None = None,
    ) -> list[RecallResult]:
        """Multi-strategy retrieval."""
        return retrieval_mod.recall(
            query, self.storage, self.embeddings, self.config,
            type_filter=type_filter, tags=tags, time_range=time_range, limit=limit,
        )

    # === Get (read-only) ===

    def get_memory(self, memory_id: str) -> MemoryGetResponse | None:
        """Get full inspection view — memory + relationships + versions. Read-only."""
        mem = self.storage.get_memory(memory_id)
        if mem is None:
            return None

        now = datetime.now(timezone.utc)
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
        mem.retrievability = r  # on-the-fly

        # Relationships
        rels = self.storage.get_relationships_for(mem.id)
        rel_infos = []
        for rel in rels:
            if rel.source_id == mem.id:
                rel_infos.append(RelationshipInfo(
                    memory_id=rel.target_id, rel_type=rel.rel_type,
                    strength=rel.strength, direction="outgoing",
                ))
            else:
                rel_infos.append(RelationshipInfo(
                    memory_id=rel.source_id, rel_type=rel.rel_type,
                    strength=rel.strength, direction="incoming",
                ))

        # Versions
        versions = self.storage.get_versions(mem.id)

        return MemoryGetResponse(memory=mem, relationships=rel_infos, versions=versions)

    # === Relationships ===

    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        strength: float = 1.0,
    ) -> Relationship:
        now = datetime.now(timezone.utc)
        rel = Relationship(
            id=str(uuid.uuid4()),
            source_id=source_id,
            target_id=target_id,
            rel_type=RelType(rel_type),
            strength=strength,
            created_at=now,
        )
        self.storage.insert_relationship(rel)
        return rel

    def delete_relationship(self, source_id: str, target_id: str, rel_type: str) -> bool:
        return self.storage.delete_relationship(source_id, target_id, rel_type)

    def get_related(
        self,
        memory_id: str,
        depth: int = 1,
        rel_types: list[str] | None = None,
    ) -> list[dict]:
        """Read-only graph traversal. No side effects."""
        visited: set[str] = {memory_id}
        results: list[dict] = []
        frontier = [memory_id]

        for d in range(depth):
            next_frontier = []
            for mid in frontier:
                neighbors = self.storage.get_neighbors(mid, active_only=True)
                for neighbor_id, rel in neighbors:
                    if neighbor_id in visited:
                        continue
                    if rel_types and rel.rel_type.value not in rel_types:
                        continue
                    visited.add(neighbor_id)
                    mem = self.storage.get_memory(neighbor_id)
                    if mem is None:
                        continue
                    now = datetime.now(timezone.utc)
                    r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
                    results.append({
                        "memory": mem.model_dump(),
                        "relationship": rel.model_dump(),
                        "depth": d + 1,
                        "retrievability": r,
                    })
                    next_frontier.append(neighbor_id)
            frontier = next_frontier

        return results

    # === Archive ===

    def archive_memory(self, memory_id: str) -> bool:
        mem = self.storage.get_memory(memory_id)
        if mem is None or mem.state == MemoryState.ARCHIVED:
            return False
        now = datetime.now(timezone.utc)
        self.storage.update_memory_fields(memory_id, state=MemoryState.ARCHIVED, updated_at=now)
        self.embeddings.remove_from_matrix(memory_id)
        return True

    def archive_bulk(self, memory_ids: list[str]) -> int:
        count = 0
        for mid in memory_ids:
            if self.archive_memory(mid):
                count += 1
        return count

    def archive_below_retrievability(self, threshold: float) -> int:
        """Archive memories with on-the-fly R below threshold."""
        now = datetime.now(timezone.utc)
        active = self.storage.get_all_active_memories()
        count = 0
        for mem in active:
            r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
            if r < threshold:
                self.archive_memory(mem.id)
                count += 1
        return count

    # === Consolidation ===

    def consolidate(self, dry_run: bool = False) -> list[dict]:
        return consolidation_mod.consolidate(
            self.storage, self.embeddings, self.config, dry_run=dry_run,
        )

    # === Stats ===

    def get_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        counts_by_type = self.storage.get_counts_by_type()
        counts_by_state = self.storage.get_counts_by_state()

        # Compute on-the-fly R for decay stats
        active = self.storage.get_all_active_memories()
        r_by_type: dict[str, list[float]] = {}
        fading_count = 0
        forgotten_count = 0
        healthy_threshold = self.config.get("decay.thresholds.healthy", 0.5)
        fading_threshold = self.config.get("decay.thresholds.fading", 0.2)

        for mem in active:
            r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
            t = mem.memory_type.value
            r_by_type.setdefault(t, []).append(r)
            if r < fading_threshold:
                forgotten_count += 1
            elif r < healthy_threshold:
                fading_count += 1

        avg_r = {t: sum(rs) / len(rs) if rs else 0.0 for t, rs in r_by_type.items()}

        consolidation_summary = self.storage.get_consolidation_summary()

        return {
            "counts": {
                "by_type": counts_by_type,
                "by_state": counts_by_state,
            },
            "decay": {
                "avg_retrievability_by_type": avg_r,
                "fading_count": fading_count,
                "forgotten_count": forgotten_count,
            },
            "consolidation": consolidation_summary,
            "storage": {
                "db_size_bytes": self.storage.get_db_size(),
                "memory_count": self.storage.get_total_memory_count(),
                "embedding_matrix_mb": self.embeddings.get_matrix_size_mb(),
            },
        }

    # === Config ===

    def get_config(self, key: str | None = None) -> dict:
        if key:
            return {"key": key, "value": self.config.get(key)}
        return self.config.get_all()

    def set_config(self, key: str, value) -> None:
        self.config.set(key, value)
