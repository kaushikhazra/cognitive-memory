"""Multi-strategy retrieval pipeline — two-phase with RRF fusion and decay reranking."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import decay as decay_mod
from .models import ContradictionInfo, RecallResult

if TYPE_CHECKING:
    from .config import Config
    from .embeddings import EmbeddingService
    from .surreal_storage import SurrealStorage as Storage


def recall(
    query: str,
    storage: "Storage",
    embeddings: "EmbeddingService",
    config: "Config",
    type_filter: str | None = None,
    tags: list[str] | None = None,
    time_range: tuple[datetime, datetime] | None = None,
    limit: int | None = None,
) -> list[RecallResult]:
    """Execute multi-strategy retrieval pipeline. Returns ranked results."""
    now = datetime.now(timezone.utc)
    limit = limit or config.get("retrieval.default_limit", 10)
    multiplier = config.get("retrieval.phase1_candidate_multiplier", 3)
    cap = config.get("retrieval.phase1_candidate_cap", 30)
    phase1_n = min(limit * multiplier, cap)

    # === Phase 1: parallel strategies (semantic + keyword + temporal) ===

    # Semantic search
    semantic_results: list[tuple[str, float]] = []
    query_vec = embeddings.embed(query)
    query_list = query_vec.astype(float).tolist()
    raw_semantic = storage.vector_search(query_list, top_k=phase1_n)
    # Apply filters
    for mid, score in raw_semantic:
        mem = storage.get_memory(mid)
        if mem is None or mem.state.value != "active":
            continue
        if type_filter and mem.memory_type.value != type_filter:
            continue
        if tags and not all(t in mem.tags for t in tags):
            continue
        if time_range and not (time_range[0] <= mem.created_at <= time_range[1]):
            continue
        semantic_results.append((mid, score))

    # Keyword search (FTS5 BM25)
    keyword_results: list[tuple[str, float]] = []
    try:
        fts_results = storage.fts_search(query, state="active", limit=phase1_n)
        for mid, rank in fts_results:
            mem = storage.get_memory(mid)
            if mem is None:
                continue
            if type_filter and mem.memory_type.value != type_filter:
                continue
            if tags and not all(t in mem.tags for t in tags):
                continue
            if time_range and not (time_range[0] <= mem.created_at <= time_range[1]):
                continue
            # FTS5 rank is negative (lower = better), convert to positive score
            keyword_results.append((mid, -rank if rank < 0 else rank))
    except Exception:
        pass  # FTS5 match can fail on malformed queries

    # Temporal search (recency-weighted)
    temporal_results: list[tuple[str, float]] = []
    active_memories = storage.get_all_active_memories()
    for mem in active_memories:
        if type_filter and mem.memory_type.value != type_filter:
            continue
        if tags and not all(t in mem.tags for t in tags):
            continue
        if time_range and not (time_range[0] <= mem.created_at <= time_range[1]):
            continue
        # Recency score: more recent = higher score
        elapsed_days = max(0, (now - mem.last_accessed).total_seconds()) / 86400.0
        recency_score = math.exp(-elapsed_days / 30.0)  # 30-day half-life for recency
        temporal_results.append((mem.id, recency_score))
    temporal_results.sort(key=lambda x: x[1], reverse=True)
    temporal_results = temporal_results[:phase1_n]

    # === Phase 1 RRF Fusion ===
    k = config.get("retrieval.rrf_k", 60)
    w_semantic = config.get("retrieval.weights.semantic", 1.0)
    w_keyword = config.get("retrieval.weights.keyword", 0.7)
    w_temporal = config.get("retrieval.weights.temporal", 0.3)

    phase1_scores: dict[str, float] = defaultdict(float)
    phase1_found_by: dict[str, set] = defaultdict(set)

    for rank, (mid, _) in enumerate(semantic_results):
        phase1_scores[mid] += w_semantic / (k + rank + 1)
        phase1_found_by[mid].add("semantic")

    for rank, (mid, _) in enumerate(keyword_results):
        phase1_scores[mid] += w_keyword / (k + rank + 1)
        phase1_found_by[mid].add("keyword")

    for rank, (mid, _) in enumerate(temporal_results):
        phase1_scores[mid] += w_temporal / (k + rank + 1)
        phase1_found_by[mid].add("temporal")

    # Top-N from Phase 1
    phase1_ranked = sorted(phase1_scores.items(), key=lambda x: x[1], reverse=True)[:phase1_n]

    # === Phase 2: Graph traversal from top-5 seeds ===
    seed_count = config.get("retrieval.phase2_seed_count", 5)
    seeds = [mid for mid, _ in phase1_ranked[:seed_count]]
    graph_results: dict[str, float] = {}
    visited: set[str] = set(seeds)

    for seed_id in seeds:
        # BFS 1-hop from each seed
        neighbors = storage.get_neighbors(seed_id, active_only=True)
        for neighbor_id, rel in neighbors:
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            # Apply same filters
            mem = storage.get_memory(neighbor_id)
            if mem is None or mem.state.value != "active":
                continue
            if type_filter and mem.memory_type.value != type_filter:
                continue
            if tags and not all(t in mem.tags for t in tags):
                continue
            if time_range and not (time_range[0] <= mem.created_at <= time_range[1]):
                continue
            # Score based on relationship strength
            score = rel.strength
            if neighbor_id in graph_results:
                graph_results[neighbor_id] = max(graph_results[neighbor_id], score)
            else:
                graph_results[neighbor_id] = score

    # === Final RRF Fusion (Phase 1 + Graph) ===
    w_graph = config.get("retrieval.weights.graph", 0.5)
    final_scores: dict[str, float] = defaultdict(float)
    final_found_by: dict[str, set] = defaultdict(set)

    # Phase 1 keeps its combined score
    for mid, score in phase1_ranked:
        final_scores[mid] += score  # Weight 1.0 (preserves Phase 1 ranking)
        final_found_by[mid] = phase1_found_by.get(mid, set()).copy()

    # Graph discoveries
    graph_ranked = sorted(graph_results.items(), key=lambda x: x[1], reverse=True)
    for rank, (mid, _) in enumerate(graph_ranked):
        final_scores[mid] += w_graph / (k + rank + 1)
        final_found_by[mid].add("graph")

    # === Decay-Weighted Reranking ===
    decay_influence = config.get("decay.decay_influence", 0.5)
    decay_scored: list[tuple[str, float]] = []

    for mid, rrf_score in final_scores.items():
        mem = storage.get_memory(mid)
        if mem is None:
            continue
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
        score = rrf_score * (r ** decay_influence)
        decay_scored.append((mid, score))

    # === Supersede Penalty ===
    supersede_penalty = config.get("retrieval.supersede_penalty", 0.3)
    penalized: list[tuple[str, float]] = []
    for mid, score in decay_scored:
        if storage.has_incoming_supersedes(mid):
            score *= supersede_penalty
        penalized.append((mid, score))

    # === Top-K Selection ===
    penalized.sort(key=lambda x: x[1], reverse=True)
    top_k = penalized[:limit]

    # === Reinforce Write-Back + Spreading Activation (single transaction) ===
    growth_factor = config.get("decay.growth_factor", 2.0)
    activation_strength = config.get("spreading_activation.activation_strength", 0.3)
    spread_factor = config.get("spreading_activation.spread_factor", 0.5)
    max_depth = config.get("spreading_activation.max_depth", 3)
    max_boost = config.get("spreading_activation.max_boost", 0.5)

    stability_updates: dict[str, float] = {}  # neighbor_id -> max boost seen

    for mid, _ in top_k:
        _spread_from(
            mid, storage, activation_strength, spread_factor,
            max_depth, max_boost, stability_updates, depth=0,
            visited=set(m for m, _ in top_k),
        )

    for mid, _ in top_k:
        mem = storage.get_memory(mid)
        if mem is None:
            continue
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
        new_stability = decay_mod.reinforce(mem.stability, r, growth_factor)
        storage.update_memory_fields(
            mid,
            stability=new_stability,
            last_accessed=now,
            access_count=mem.access_count + 1,
        )

    # Apply spreading activation stability boosts
    if stability_updates:
        bulk = []
        for neighbor_id, boost in stability_updates.items():
            mem = storage.get_memory(neighbor_id)
            if mem and mem.state.value == "active":
                new_s = decay_mod.apply_spreading_boost(mem.stability, boost)
                bulk.append((new_s, neighbor_id))
        if bulk:
            storage.bulk_update_stability(bulk)

    # === Build Results ===
    results: list[RecallResult] = []
    for mid, score in top_k:
        mem = storage.get_memory(mid)
        if mem is None:
            continue
        r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)

        # Contradictions
        raw_contradictions = storage.get_contradictions_for(mid)
        contradictions = [
            ContradictionInfo(memory_id=cid, content_preview=preview, strength=strength)
            for cid, preview, strength in raw_contradictions
        ]

        results.append(RecallResult(
            id=mem.id,
            content=mem.content,
            memory_type=mem.memory_type,
            importance=mem.importance,
            retrievability=r,
            score=score,
            found_by=sorted(final_found_by.get(mid, set())),
            tags=mem.tags,
            created_at=mem.created_at,
            last_accessed=mem.last_accessed,
            contradictions=contradictions,
        ))

    return results


def _spread_from(
    memory_id: str,
    storage: "Storage",
    activation_strength: float,
    spread_factor: float,
    max_depth: int,
    max_boost: float,
    updates: dict[str, float],
    depth: int,
    visited: set[str],
) -> None:
    """Recursive spreading activation from a memory."""
    if depth >= max_depth:
        return

    neighbors = storage.get_neighbors(memory_id, active_only=True)
    for neighbor_id, rel in neighbors:
        if neighbor_id in visited:
            continue
        visited.add(neighbor_id)

        boost = decay_mod.compute_spreading_boost(
            rel.strength, activation_strength, depth + 1, spread_factor, max_boost,
        )
        if boost <= 0:
            continue

        # Keep max boost per neighbor
        if neighbor_id in updates:
            updates[neighbor_id] = max(updates[neighbor_id], boost)
        else:
            updates[neighbor_id] = boost

        # Continue spreading
        _spread_from(
            neighbor_id, storage, activation_strength, spread_factor,
            max_depth, max_boost, updates, depth + 1, visited,
        )
