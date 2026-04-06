# Design Dry-Run Report #1

**Reviewed**: 2026-04-06

## Critical Gaps (would cause bugs or incorrect behavior)

### [C1] REL_TABLES missing "describes" — KeyError on any describes relationship operation
- **Design section**: 7. Schema Changes / 1. Data Model (RelType)
- **Code reference**: `src/cognitive_memory/surreal_storage.py:25-33`
- **What**: The design adds `DESCRIBES = "describes"` to `RelType` and creates a `describes` relation table in `schema.surql`, but `surreal_storage.py` is omitted from "Files Changed" entirely. The `REL_TABLES` dict (line 25-33) maps RelType values to SurrealDB edge table names and currently only has 7 entries. Without `"describes": "describes"`, every code path that uses `REL_TABLES` breaks:
  - `insert_relationship()` (line 343): `REL_TABLES[rel.rel_type.value]` → **KeyError**
  - `delete_memory()` (line 185): iterates `REL_TABLES.values()` → won't cascade-delete `describes` edges (orphaned data)
  - `get_relationships_for()` (line 366): `REL_TABLES[rt]` → **KeyError** when filtering by "describes"
  - `get_outgoing_relationships()` (line 380): iterates `REL_TABLES.values()` → misses describes edges
  - `get_incoming_relationships()` (line 391): `REL_TABLES[rel_type]` → **KeyError**
  - `get_neighbors()` (line 405): iterates `REL_TABLES.values()` → misses describes edges (graph traversal incomplete)
- **Impact**: Creating a `describes` relationship via `memory_relate` crashes the server. Deleting a memory with describes edges leaves orphaned edges. Graph traversal silently ignores describes connections.
- **Fix**: Add `surreal_storage.py` to "Files Changed" with: add `"describes": "describes"` to `REL_TABLES` dict.

### [C2] engine.py importance_cfg omits identity/person bonus keys — config values are dead
- **Design section**: 3. Classification / Importance scoring
- **Code reference**: `src/cognitive_memory/engine.py:66-76`
- **What**: The design adds `identity_bonus` and `person_bonus` to `config.default.yaml` under `importance:`, and adds checks in `score_importance()` using `cfg.get("identity_bonus", 0.2)`. But `engine.py` builds the `importance_cfg` dict manually (lines 66-76) with only 8 specific keys: `base_score`, `named_entity_bonus`, `relational_bonus`, `length_bonus`, `length_threshold`, `working_penalty`, `min`, `max`. The keys `identity_bonus` and `person_bonus` are never included in this dict.

  The design says `engine.py` has "No changes" — but the config dict it passes to `score_importance()` will never contain these keys. The `cfg.get("identity_bonus", 0.2)` fallback default masks the bug (the bonus still applies), but:
  1. The config.default.yaml values are dead — changing `importance.identity_bonus` to 0.3 in config has no effect.
  2. Runtime config overrides via `memory_config` also have no effect on these bonuses.
- **Impact**: Identity/person importance bonuses work at hardcoded defaults but are not configurable. Violates the config-driven architecture.
- **Fix**: Add `engine.py` to "Files Changed". Add to `importance_cfg` dict:
  ```python
  "identity_bonus": self.config.get("importance.identity_bonus", 0.2),
  "person_bonus": self.config.get("importance.person_bonus", 0.15),
  ```

### [C3] Promotion pass elif ordering — EPISODIC→PERSON promotion is dead code
- **Design section**: 5. Consolidation Changes / Promotion pass
- **Code reference**: `src/cognitive_memory/consolidation.py:94-122`
- **What**: The current promotion logic uses an if/elif chain:
  ```python
  if mem.memory_type == MemoryType.WORKING:       # line 98
      ...
  elif mem.memory_type == MemoryType.EPISODIC:     # line 107
      # Episodic → Procedural or Semantic
      ...
  ```
  The design proposes adding person promotion as:
  ```python
  elif mem.memory_type in (MemoryType.EPISODIC, MemoryType.SEMANTIC):
      # person promotion
  ```
  But this elif comes *after* the existing `elif mem.memory_type == MemoryType.EPISODIC` branch. Python's elif chain short-circuits — EPISODIC memories are already caught by line 107 and never reach the person promotion check. Only SEMANTIC memories would reach it, so EPISODIC→PERSON promotion is dead code.
- **Impact**: Episodic memories with `person:` tags are never auto-promoted to person type. Only the SEMANTIC→PERSON path works. Violates requirement INT-2 ("Promotion from episodic/semantic to person or identity is possible").
- **Fix**: Restructure the promotion logic. Options:
  1. **Inside the existing EPISODIC branch**: Check for person promotion first (before procedural/semantic), since it has a more specific trigger (requires `person:` tag):
     ```python
     elif mem.memory_type == MemoryType.EPISODIC:
         person_tags = [t for t in mem.tags if t.startswith("person:")]
         if person_tags and mem.access_count >= to_person_access:
             new_type = MemoryType.PERSON
         elif pattern_match and mem.access_count >= e2p_access:
             new_type = MemoryType.PROCEDURAL
         elif mem.access_count >= e2s_access and r > e2s_r:
             new_type = MemoryType.SEMANTIC
     ```
  2. **Add a separate SEMANTIC branch** for SEMANTIC→PERSON only:
     ```python
     elif mem.memory_type == MemoryType.SEMANTIC:
         person_tags = [t for t in mem.tags if t.startswith("person:")]
         if person_tags and mem.access_count >= to_person_access:
             new_type = MemoryType.PERSON
     ```

  Both paths are needed. The design should specify the exact insertion point and structure.

## Warnings (implementation would work but suboptimally)

### [W1] Silent schema migration failure — ASSERT widening could fail undetected
- **Design section**: 7. Schema Changes / Schema migration strategy
- **Code reference**: `src/cognitive_memory/surreal_storage.py:91-102`
- **What**: `_ensure_schema()` swallows all exceptions with `except Exception: pass` (line 101-102). If the `DEFINE FIELD memory_type ... ASSERT $value IN [...]` statement fails to update (e.g., SurrealDB version incompatibility, syntax issue), the old ASSERT remains and the error is silently ignored. The next `INSERT` with `memory_type = 'identity'` would fail with an ASSERT violation at runtime — far from the actual cause.
- **Impact**: Schema migration failure is invisible. First symptom is a confusing runtime error on `memory_store(type="identity")`.
- **Fix**: The design should note this risk and recommend either: (a) adding a post-schema-apply verification query (e.g., insert a test record with `memory_type = 'identity'` in a transaction and roll back), or (b) logging schema apply errors instead of silently swallowing them. At minimum, the implementation task should include a manual verification step.

### [W2] memory_who cold-start — returns empty results until person memories are explicitly stored
- **Design section**: 6. New Tools / memory_who
- **Code reference**: Design section 6 + Decision D3
- **What**: `memory_who` filters with `type_filter="person"`. During early adoption, most knowledge about people exists as episodic or semantic memories (e.g., "Kaushik prefers explicit error handling" stored as semantic). `memory_who("kaushik")` returns nothing until the agent explicitly stores or promotes memories as `type="person"`. The promotion pipeline (episodic/semantic → person) requires `min_access_count: 3`, meaning at least 3 recalls before auto-promotion kicks in.
- **Impact**: For new deployments or newly-mentioned people, the convenience tool is useless. The agent falls back to `memory_recall(query="kaushik", tags=["person:kaushik"])` which also returns nothing (tags won't match episodic memories that weren't tagged). The real fallback is `memory_recall(query="kaushik")` without type/tag filters — which works but defeats the purpose of `memory_who`.
- **Fix**: Consider adding a fallback clause to `memory_who`: if the person-typed query returns zero results, re-query without `type_filter` (keeping only the `person:` tag filter, or even just using the person name as the query). This doesn't compromise the design (person memories still get priority), but handles the cold-start gracefully. Alternatively, document this clearly in the tool's docstring so the agent knows to fall back to `memory_recall` when `memory_who` returns empty.

### [W3] Test assertions hardcoded at 14 tools
- **Design section**: 6. New Tools / Tool count
- **Code reference**: `tests/test_mcp_client.py:86`
- **What**: The MCP integration test asserts `len(tools.tools) == 14`. Adding `memory_self` and `memory_who` brings the count to 16, which will fail this test.
- **Impact**: CI/test failure on first run after implementation. Not a design gap per se, but the design should note test updates needed.
- **Fix**: Note in implementation tasks that `test_mcp_client.py` assertion must be updated to 16, and that new tool-specific tests should be added for both `memory_self` and `memory_who`.

### [W4] Promotion pass config key not read — `to_person.min_access_count` never fetched
- **Design section**: 5. Consolidation Changes / Promotion pass
- **Code reference**: `src/cognitive_memory/consolidation.py:84-92`
- **What**: The promotion pass reads config values at the top of the function (lines 84-92) for existing promotion paths (`working_to_episodic`, `episodic_to_semantic`, etc.). The design proposes a new config key `consolidation.promotion.to_person.min_access_count` but doesn't show the config read line that loads it into a local variable. The design's code snippet references `e2p_person_access` which is never defined or read from config.
- **Impact**: The implementation would likely use a magic number or crash on undefined variable, depending on how literally the design is followed.
- **Fix**: Add to the design's consolidation section: at the top of `_promotion_pass`, read the new config:
  ```python
  to_person_access = config.get("consolidation.promotion.to_person.min_access_count", 3)
  ```

## Observations (minor, worth noting)

### [O1] decay.initial_stability config values are cosmetic — config_map parameter never wired
- **Design section**: 2. Decay Configuration
- **Code reference**: `src/cognitive_memory/decay.py:26` / `src/cognitive_memory/engine.py:83`
- **What**: `get_initial_stability(memory_type, config_map=None)` accepts an optional `config_map` but it's never passed by any caller (`engine.py:83`, `engine.py:228`, `consolidation.py:135` all call with just the type string). The `config.default.yaml` values under `decay.initial_stability` are never read by the running system — only the hardcoded `defaults` dict in `decay.py` is used. This is a pre-existing issue, not introduced by this design. The design correctly updates both locations, so the new types work, but the YAML config remains non-functional for all types.
- **Impact**: None for this feature (hardcoded defaults match YAML), but misleading for operators who try to tune decay via config.

### [O2] Person tag lowercase enforcement is convention-only — no runtime validation
- **Design section**: 9. Person Tagging Convention
- **What**: The design requires `person:` tags to be lowercase (Decision D8). The `memory_who` tool lowercases its input before matching. But `memory_store` does no tag validation — if the agent stores `tags=["person:Kaushik"]`, `memory_who("kaushik")` won't find it because tag matching is case-sensitive (SurrealDB `$tag IN tags` is exact match). The design acknowledges "convention over enforcement" but there's no guardrail.
- **Impact**: A single mixed-case tag creates a memory invisible to `memory_who`. The agent must be disciplined, but agents make mistakes.
- **Fix idea**: Consider normalizing tags containing "person:" to lowercase in `engine.store_memory()` or noting this as a future hardening task.

### [O3] `consolidation.promotion.to_person.requires_person_tag` config key is unused
- **Design section**: 8. Config Changes Summary
- **What**: The config proposes `requires_person_tag: true` but the design's code always checks for person tags as a required condition. This boolean config key is never checked — the behavior is always "require person tag". It's dead config.
- **Impact**: None functional. Minor clutter.

### [O4] `describes` relationship has no special query support
- **Design section**: 1. Data Model / RelType
- **What**: The `describes` relationship is added but has no special retrieval or traversal support beyond what `memory_related` already provides generically. There's no tool for "find all memories that describe person X" or "find the anchor memory this facet describes." This is fine for MVP but worth noting for future iterations.

### [O5] No guidance on identity memory granularity
- **Design section**: Requirement IM-1
- **What**: The requirement says "each identity memory represents one facet" but there's no enforcement or validation. An agent could store a monolithic identity dump as a single identity memory, defeating the purpose. This is inherently hard to enforce technically, but the tool docstrings or CLAUDE.md guidance could emphasize granularity.

## Requirement Coverage

| Story | Covered? | Design section |
|-------|----------|----------------|
| IM-1: Store identity facets | Yes | 1. Data Model (MemoryType.IDENTITY) |
| IM-2: Recall self-knowledge | Yes | 4. Retrieval (polymorphic) + 6. New Tools (memory_self) |
| IM-3: Identity resists decay | Yes | 2. Decay (S0=365) + 5. Consolidation (archive exemption) |
| IM-4: Update identity | Yes | Existing memory_update works polymorphically |
| PM-1: Store person knowledge | Yes | 1. Data Model (MemoryType.PERSON) + 9. Tagging Convention |
| PM-2: Recall person knowledge | Yes | 4. Retrieval (polymorphic) + 6. New Tools (memory_who) |
| PM-3: Person decay slowly | Yes | 2. Decay (S0=90) + 5. Consolidation (person_archive_threshold) |
| PM-4: Relate person memories | Partial | 1. Data Model (DESCRIBES RelType) — but C1 blocks runtime use |
| DT-1: memory_self | Yes | 6. New Tools |
| DT-2: memory_who | Yes | 6. New Tools (with W2 cold-start caveat) |
| INT-1: Unified retrieval | Yes | 4. Retrieval (no changes needed) |
| INT-2: Consolidation handles new types | Partial | 5. Consolidation — but C3 makes EPISODIC→PERSON dead code |

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 3 | 4 | 5 |

**Verdict**: FAIL

Three critical gaps must be resolved before implementation:
1. **C1** (REL_TABLES) would cause runtime crashes on any `describes` relationship operation.
2. **C2** (engine.py importance_cfg) makes the new config keys non-functional — less severe but violates the config-driven principle the design depends on.
3. **C3** (promotion elif ordering) makes EPISODIC→PERSON promotion dead code, partially breaking requirement INT-2.

All three are straightforward fixes. C1 requires adding `surreal_storage.py` to "Files Changed". C2 requires adding `engine.py` to "Files Changed". C3 requires restructuring the promotion code snippet in the design to show exact insertion points within the existing if/elif chain.
