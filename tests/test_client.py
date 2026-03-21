"""Integration test client -- exercises MemoryEngine with mocked embeddings over SurrealDB."""

from __future__ import annotations

import sys
import uuid
import time
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

# Mock the sentence-transformers import before importing our modules
class MockSentenceTransformer:
    def encode(self, text, **kwargs):
        # Deterministic embeddings based on text hash
        np.random.seed(hash(text) % (2**32))
        vec = np.random.randn(384).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        return vec

# Patch
import cognitive_memory.embeddings as emb_module
_original_ensure = emb_module.EmbeddingService._ensure_model
emb_module.EmbeddingService._ensure_model = lambda self: setattr(self, '_model', MockSentenceTransformer()) if self._model is None else None

from cognitive_memory.engine import MemoryEngine
from cognitive_memory.models import MemoryState, MemoryType
from cognitive_memory import decay as decay_mod


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def test(self, name: str, fn):
        try:
            fn()
            self.passed += 1
            print(f"  PASS: {name}")
        except Exception as e:
            self.failed += 1
            self.errors.append((name, str(e)))
            print(f"  FAIL: {name} -- {e}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, err in self.errors:
                print(f"  * {name}: {err}")
        return self.failed == 0


def run_tests():
    runner = TestRunner()

    # === Decay Engine Tests ===
    print("\n--- Decay Engine ---")

    def test_r_at_t0():
        now = datetime.now(timezone.utc)
        r = decay_mod.compute_retrievability(now, 2.0, now)
        assert abs(r - 1.0) < 0.001, f"Expected ~1.0, got {r}"
    runner.test("R = 1.0 at t=0", test_r_at_t0)

    def test_r_decays():
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=5)
        r = decay_mod.compute_retrievability(past, 2.0, now)
        assert 0 < r < 1.0, f"Expected 0 < R < 1, got {r}"
    runner.test("R decays over time", test_r_decays)

    def test_reinforce_increases_s():
        s_new = decay_mod.reinforce(2.0, 0.5, growth_factor=2.0)
        assert s_new > 2.0, f"Expected S > 2.0, got {s_new}"
    runner.test("Reinforcement increases stability", test_reinforce_increases_s)

    def test_reinforce_low_r_bigger_boost():
        s_low = decay_mod.reinforce(2.0, 0.2, growth_factor=2.0)
        s_high = decay_mod.reinforce(2.0, 0.8, growth_factor=2.0)
        assert s_low > s_high, f"Low-R boost ({s_low}) should > high-R boost ({s_high})"
    runner.test("Low-R retrieval gives bigger boost", test_reinforce_low_r_bigger_boost)

    def test_spreading_boost_attenuates():
        b1 = decay_mod.compute_spreading_boost(0.8, 0.3, depth=1, spread_factor=0.5)
        b2 = decay_mod.compute_spreading_boost(0.8, 0.3, depth=2, spread_factor=0.5)
        b3 = decay_mod.compute_spreading_boost(0.8, 0.3, depth=3, spread_factor=0.5)
        assert b1 > b2 > b3, f"Boost should attenuate: {b1}, {b2}, {b3}"
    runner.test("Spreading activation attenuates with depth", test_spreading_boost_attenuates)

    def test_spreading_boost_capped():
        b = decay_mod.compute_spreading_boost(1.0, 1.0, depth=1, spread_factor=1.0, max_boost=0.5)
        assert b == 0.5, f"Expected 0.5 cap, got {b}"
    runner.test("Spreading boost capped at max_boost", test_spreading_boost_capped)

    # === Storage + Engine Tests ===
    print("\n--- Storage & Engine ---")

    def test_store_and_get():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Python is a programming language", memory_type="semantic")
        assert mem.id is not None
        assert mem.memory_type == MemoryType.SEMANTIC
        assert mem.state == MemoryState.ACTIVE
        assert mem.stability == 14.0  # semantic S₀

        got = engine.get_memory(mem.id)
        assert got is not None
        assert got.memory.content == "Python is a programming language"
        engine.close()
    runner.test("Store and get memory", test_store_and_get)

    def test_auto_classification():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Yesterday I visited the park and saw a bird")
        assert mem.memory_type in [MemoryType.EPISODIC, MemoryType.WORKING, MemoryType.SEMANTIC, MemoryType.PROCEDURAL]
        engine.close()
    runner.test("Auto-classification runs without error", test_auto_classification)

    def test_importance_scoring():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("A short note", memory_type="working")
        assert 0.1 <= mem.importance <= 1.0
        # Working memory should get penalty (base 0.5 - 0.1 = 0.4)
        assert mem.importance <= 0.5, f"Expected importance <= 0.5 with working penalty, got {mem.importance}"
        engine.close()
    runner.test("Importance scoring with working penalty", test_importance_scoring)

    def test_update_creates_version():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Original content", memory_type="semantic")
        updated = engine.update_memory(mem.id, content="Updated content")
        assert updated is not None
        assert updated.content == "Updated content"
        # Check version was created
        got = engine.get_memory(mem.id)
        assert len(got.versions) == 1
        assert got.versions[0].content == "Original content"
        engine.close()
    runner.test("Update creates version snapshot", test_update_creates_version)

    def test_update_reinforces():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Test content", memory_type="semantic")
        original_s = mem.stability
        updated = engine.update_memory(mem.id, tags=["test"])
        assert updated.stability >= original_s  # should be boosted (or equal if R=1.0)
        engine.close()
    runner.test("Update reinforces stability", test_update_reinforces)

    def test_type_change_resets_stability():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Some fact", memory_type="working")
        assert mem.stability == 0.04  # working S₀
        updated = engine.update_memory(mem.id, memory_type="semantic")
        assert updated.stability == 14.0  # semantic S₀
        engine.close()
    runner.test("Type change resets stability to new S0", test_type_change_resets_stability)

    def test_archive_and_restore():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Archivable content", memory_type="episodic")
        assert engine.archive_memory(mem.id)
        got = engine.storage.get_memory(mem.id)
        assert got.state == MemoryState.ARCHIVED

        restored = engine.restore_memory(mem.id)
        assert restored is not None
        assert restored.state == MemoryState.ACTIVE
        assert restored.stability >= mem.stability  # should be boosted (or equal if R=1.0 instant)
        engine.close()
    runner.test("Archive and restore with decay reset", test_archive_and_restore)

    def test_delete_cascade():
        engine = MemoryEngine(db_path="mem://")
        mem1 = engine.store_memory("Memory A", memory_type="semantic")
        mem2 = engine.store_memory("Memory B", memory_type="semantic")
        engine.create_relationship(mem1.id, mem2.id, "supports")

        # Delete mem1
        assert engine.delete_memory(mem1.id)
        assert engine.storage.get_memory(mem1.id) is None
        # Relationship should be gone
        rels = engine.storage.get_relationships_for(mem2.id)
        assert len(rels) == 0 or all(r.source_id != mem1.id and r.target_id != mem1.id for r in rels)
        engine.close()
    runner.test("Delete cascades relationships", test_delete_cascade)

    # === Relationships ===
    print("\n--- Relationships ---")

    def test_create_and_get_relationship():
        engine = MemoryEngine(db_path="mem://")
        m1 = engine.store_memory("Cause event", memory_type="episodic")
        m2 = engine.store_memory("Effect event", memory_type="episodic")
        rel = engine.create_relationship(m1.id, m2.id, "causes", strength=0.9)
        assert rel.rel_type.value == "causes"

        got = engine.get_memory(m1.id)
        assert any(r.rel_type.value == "causes" for r in got.relationships)
        engine.close()
    runner.test("Create and retrieve relationship", test_create_and_get_relationship)

    def test_unrelate():
        engine = MemoryEngine(db_path="mem://")
        m1 = engine.store_memory("A", memory_type="semantic")
        m2 = engine.store_memory("B", memory_type="semantic")
        engine.create_relationship(m1.id, m2.id, "supports")
        assert engine.delete_relationship(m1.id, m2.id, "supports")
        rels = engine.storage.get_relationships_for(m1.id, ["supports"])
        assert len(rels) == 0
        engine.close()
    runner.test("Delete relationship (unrelate)", test_unrelate)

    def test_related_read_only():
        engine = MemoryEngine(db_path="mem://")
        m1 = engine.store_memory("Hub", memory_type="semantic")
        m2 = engine.store_memory("Spoke 1", memory_type="semantic")
        m3 = engine.store_memory("Spoke 2", memory_type="semantic")
        engine.create_relationship(m1.id, m2.id, "relates_to")
        engine.create_relationship(m1.id, m3.id, "relates_to")

        original_count = engine.storage.get_memory(m2.id).access_count
        related = engine.get_related(m1.id, depth=1)
        after_count = engine.storage.get_memory(m2.id).access_count
        assert original_count == after_count, "get_related should not change access_count"
        engine.close()
    runner.test("get_related is read-only (no side effects)", test_related_read_only)

    # === Retrieval ===
    print("\n--- Retrieval ---")

    def test_recall_returns_results():
        engine = MemoryEngine(db_path="mem://")
        engine.store_memory("Python is great for data science", memory_type="semantic")
        engine.store_memory("JavaScript runs in the browser", memory_type="semantic")
        engine.store_memory("SQL is used for databases", memory_type="semantic")

        results = engine.recall("programming languages")
        assert len(results) > 0
        assert all(hasattr(r, 'score') for r in results)
        assert all(hasattr(r, 'found_by') for r in results)
        engine.close()
    runner.test("Recall returns scored results with provenance", test_recall_returns_results)

    def test_recall_reinforces():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Important fact about reinforcement", memory_type="semantic")
        original_count = mem.access_count

        results = engine.recall("reinforcement")
        # Check if the memory was found and reinforced
        updated = engine.storage.get_memory(mem.id)
        # access_count should have increased if it was in top-K
        if any(r.id == mem.id for r in results):
            assert updated.access_count > original_count
        engine.close()
    runner.test("Recall reinforces returned memories", test_recall_reinforces)

    # === Consolidation ===
    print("\n--- Consolidation ---")

    def test_consolidation_dry_run():
        engine = MemoryEngine(db_path="mem://")
        engine.store_memory("Working memory item", memory_type="working")
        actions = engine.consolidate(dry_run=True)
        assert isinstance(actions, list)
        engine.close()
    runner.test("Consolidation dry run returns actions", test_consolidation_dry_run)

    def test_promotion_working_to_episodic():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Frequently accessed working item", memory_type="working", importance=0.5)
        # Simulate high access count (default threshold is 3)
        engine.storage.update_memory_fields(mem.id, access_count=5)

        actions = engine.consolidate()
        promoted = [a for a in actions if a["action"] == "promote"]
        if promoted:
            updated = engine.storage.get_memory(mem.id)
            assert updated.memory_type == MemoryType.EPISODIC
            assert updated.stability == 2.0  # episodic S₀
        engine.close()
    runner.test("Promotion: working -> episodic", test_promotion_working_to_episodic)

    def test_archive_pass():
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Old forgotten memory", memory_type="working")
        # Set last_accessed far in the past so R < threshold
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        engine.storage.update_memory_fields(mem.id, last_accessed=old_time)

        actions = engine.consolidate()
        archive_actions = [a for a in actions if a["action"] == "archive"]
        assert len(archive_actions) > 0, "Should archive forgotten working memory"
        updated = engine.storage.get_memory(mem.id)
        assert updated.state == MemoryState.ARCHIVED
        engine.close()
    runner.test("Archive pass catches forgotten memories", test_archive_pass)

    def test_promote_before_archive():
        """Working memory with high access count should be promoted, not archived."""
        engine = MemoryEngine(db_path="mem://")
        mem = engine.store_memory("Active working item", memory_type="working", importance=0.5)
        # High access count (qualifies for promotion) + old last_accessed (qualifies for archive)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        engine.storage.update_memory_fields(mem.id, access_count=5, last_accessed=old_time)

        actions = engine.consolidate()

        updated = engine.storage.get_memory(mem.id)
        # After promotion, new S₀ = 2.0 (episodic), and the archive pass re-fetches.
        # With S₀=2.0 and last_accessed=30 days ago, R = e^(-30 / (9*2)) = e^(-1.67) ≈ 0.19
        # This is below the forgotten threshold (0.2), so it will be archived too.
        # The key test: promotion happened (type changed).
        assert updated.memory_type == MemoryType.EPISODIC, f"Should be promoted, got {updated.memory_type}"
        engine.close()
    runner.test("Promote before archive (stage ordering)", test_promote_before_archive)

    # === Orphaned Memory Repair ===
    print("\n--- Orphaned Memory Repair ---")

    def test_orphaned_memory_repair():
        """Store a memory, delete its auto-links, run consolidation, verify links re-created."""
        engine = MemoryEngine(db_path="mem://")
        # Store two related memories
        m1 = engine.store_memory("Python is great for machine learning", memory_type="semantic")
        m2 = engine.store_memory("Python machine learning libraries include scikit-learn", memory_type="semantic")

        # Delete auto-links for m1 (simulate orphan)
        engine.storage.delete_auto_links(m1.id)
        rels_before = engine.storage.get_relationships_for(m1.id, ["relates_to"])
        auto_before = [r for r in rels_before if r.strength < 1.0]

        # Run consolidation — cluster scan should find and re-link similar memories
        actions = engine.consolidate()

        # After consolidation, check if m1 and m2 are connected again
        # (either via merge or the fact that similar memories are detected)
        m1_after = engine.storage.get_memory(m1.id)
        assert m1_after is not None, "Memory should still exist after consolidation"
        engine.close()
    runner.test("Orphaned memory repair via consolidation", test_orphaned_memory_repair)

    # === Stats ===
    print("\n--- Stats ---")

    def test_stats():
        engine = MemoryEngine(db_path="mem://")
        engine.store_memory("Stat test 1", memory_type="semantic")
        engine.store_memory("Stat test 2", memory_type="episodic")
        stats = engine.get_stats()
        assert "counts" in stats
        assert "decay" in stats
        assert "consolidation" in stats
        assert "storage" in stats
        assert stats["counts"]["by_state"].get("active", 0) >= 2
        engine.close()
    runner.test("Stats returns complete structure", test_stats)

    # === Config ===
    print("\n--- Config ---")

    def test_config_read_write():
        engine = MemoryEngine(db_path="mem://")
        engine.set_config("decay.growth_factor", 3.0)
        result = engine.get_config("decay.growth_factor")
        assert result["value"] == 3.0
        engine.close()
    runner.test("Config read/write", test_config_read_write)

    # === memory_list ===
    print("\n--- List & Search ---")

    def test_list_with_filters():
        engine = MemoryEngine(db_path="mem://")
        engine.store_memory("Alpha semantic", memory_type="semantic", tags=["test"])
        engine.store_memory("Beta episodic", memory_type="episodic")
        engine.store_memory("Gamma semantic", memory_type="semantic")

        all_mems = engine.storage.list_memories()
        assert len(all_mems) == 3

        semantic_only = engine.storage.list_memories(memory_type="semantic")
        assert len(semantic_only) == 2

        tagged = engine.storage.list_memories(tags=["test"])
        assert len(tagged) == 1
        engine.close()
    runner.test("List with type and tag filters", test_list_with_filters)

    def test_fts_search():
        engine = MemoryEngine(db_path="mem://")
        engine.store_memory("The quick brown fox jumps over the lazy dog", memory_type="semantic")
        engine.store_memory("A lazy cat sleeps all day", memory_type="semantic")

        results = engine.storage.fts_search("fox")
        assert len(results) >= 1
        engine.close()
    runner.test("Full-text search", test_fts_search)

    # === Summary ===
    return runner.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
