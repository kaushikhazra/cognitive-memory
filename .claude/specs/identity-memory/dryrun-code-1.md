# Code Dry-Run Report #1

**Reviewed**: 2026-04-06

## Bugs (would cause incorrect behavior at runtime)

### [B1] Merge pass can auto-archive identity memories — violates IM-3
- **File**: `src/cognitive_memory/consolidation.py:224-264`
- **What**: The `_cluster_and_merge` function has no identity exemption. If two memories exceed the merge threshold (0.90 cosine similarity) and one is identity-typed, the lower-scoring memory becomes the "secondary" and gets archived (line 364: `storage.update_memory_fields(secondary.id, state=MemoryState.ARCHIVED, ...)`). The scoring formula `importance * access_count` means a freshly-stored identity memory (access_count=0, score=0) would always lose to any previously-accessed memory, regardless of type.
- **Impact**: Violates IM-3 acceptance criterion: "Consolidation never auto-archives identity memories while they are active." A newly-stored identity memory similar to an existing semantic/episodic memory could be merged away on the next consolidation run. The content is preserved in the primary, but the identity typing and its decay protection are lost. Practical trigger requires >0.90 similarity between an identity memory and another memory — unlikely for well-factored facets, but possible for near-duplicate content.
- **Fix**: Add identity guard at the top of the merge block, before the primary/secondary decision:
  ```python
  if sim >= merge_threshold and not has_negation:
      # Never merge away identity memories — they're protected from auto-archive
      if mem.memory_type == MemoryType.IDENTITY and mem_b.memory_type != MemoryType.IDENTITY:
          primary, secondary = mem, mem_b
      elif mem_b.memory_type == MemoryType.IDENTITY and mem.memory_type != MemoryType.IDENTITY:
          primary, secondary = mem_b, mem
      else:
          # Standard scoring — highest importance * access_count wins
          score_a = mem.importance * mem.access_count
          score_b = mem_b.importance * mem_b.access_count
          if score_a >= score_b:
              primary, secondary = mem, mem_b
          else:
              primary, secondary = mem_b, mem
  ```
  Alternatively, skip the merge entirely when either memory is identity-typed (simpler, more conservative).

### [B2] `memory_who` with empty/whitespace person name returns random results
- **File**: `src/cognitive_memory/server.py:375-396`
- **What**: No input validation on the `person` parameter. If `person=""` or `person="   "`:
  - `person.strip().lower()` = `""`
  - `person_tag` = `"person:"` (malformed tag, matches nothing)
  - `effective_query` = `query or ""` (empty string if no query given)
  - Tier 1 and Tier 2 return empty (no memory has tag `"person:"`)
  - Tier 3 calls `engine.recall(query="")` — returns memories ranked by cosine similarity to an empty-string embedding, which is effectively random
- **Impact**: `memory_who(person="")` silently returns random, unrelated memories instead of an error. An agent passing a variable that happens to be empty gets misleading results.
- **Fix**: Add validation at the start of the function:
  ```python
  person_name = person.strip().lower()
  if not person_name:
      return _error("person parameter must be a non-empty name")
  ```

## Gaps (missing coverage against design/requirements)

### [G1] No test for `memory_who` 3-tier fallback behavior
- **Requirement**: DT-2, W2 from dryrun-design-1
- **What**: The `memory_who` implementation includes a 3-tier fallback (person-typed → any-type with person tag → unfiltered). No test exercises tiers 2 or 3. The MCP test (`test_mcp_client.py:256-263`) only tests the happy path where person-typed memories exist.
- **Test needed**: Store a memory as episodic with `person:kaushik` tag (no person-typed memories), call `memory_who("kaushik")`, verify it falls through to tier 2 and returns the episodic memory. Then test tier 3: store only an untagged episodic memory mentioning "kaushik", verify tier 3 returns it.

### [G2] No test for INT-1 (unified retrieval includes identity/person without type filter)
- **Requirement**: INT-1
- **What**: No test verifies that `memory_recall(query="who built me")` (no type filter) returns identity memories alongside semantic/episodic ones. The existing recall tests use type filters.
- **Test needed**: Store identity + semantic memories, recall without type filter, assert identity memories appear in results when semantically relevant.

### [G3] No test for identity manual archive still works
- **Requirement**: IM-3 acceptance criteria: "Manual archive is still possible (for identity evolution — retiring old facets)"
- **What**: `test_identity_archive_exemption` tests that auto-archive skips identity, but no test verifies that `memory_archive(id)` still works on an identity memory. The archive exemption is only in `_archive_pass`, so `engine.archive_memory()` should work, but there's no regression test.
- **Test needed**: Store identity memory, call `engine.archive_memory(id)`, verify state is ARCHIVED.

### [G4] No test for `memory_who` with no query parameter
- **Requirement**: DT-2 acceptance criteria, Design Decision D7
- **What**: `memory_who(person="kaushik")` with no query should use `"kaushik"` as the effective query. The MCP test always provides a query. This default behavior (Design D7) is untested.
- **Test needed**: Call `memory_who(person="kaushik")` without query parameter, verify results are returned.

### [G5] No test for auto-classification of identity/person content
- **Requirement**: Design section 3 (classification heuristics)
- **What**: `_IDENTITY_PATTERNS` and `_PERSON_PATTERNS` were added, and the `classify()` scores dict includes both new types, but no test verifies that content like "I am Velasari" auto-classifies as identity, or that content with "he prefers" auto-classifies as person. All tests explicitly pass `memory_type`.
- **Test needed**: Call `classify("I am Velasari, I was built by Kaushik")` and verify identity is returned. Call `classify("he prefers explicit error handling")` and verify person or episodic is returned (person signals may not be strong enough to beat episodic for short content — that's fine, but the test documents the behavior).

## Warnings (code works but quality/robustness concern)

### [W1] `memory_who` third fallback tier drops all filters — may return unrelated results
- **File**: `src/cognitive_memory/server.py:393-396`
- **What**: The third fallback calls `engine.recall(query=effective_query)` with no type filter and no tag filter. For `memory_who("kaushik")`, this returns any memory semantically similar to the word "kaushik" — potentially including programming tips, project notes, etc. that have no connection to Kaushik as a person.
- **Concern**: The fallback is documented in the docstring, but an agent might not read docstrings. Results from tier 3 are indistinguishable from tier 1 results in the response format — there's no indicator that the fallback fired.
- **Suggestion**: Include a `"fallback_tier"` field in the response meta so the agent knows which tier produced results: `_response({"memories": ...}, elapsed, fallback_tier=tier)`. Alternatively, cap tier 3 results to a lower limit (e.g., 3) to reduce noise.

### [W2] `memory_who` makes up to 3 recall calls — 3x latency on cold start
- **File**: `src/cognitive_memory/server.py:381-396`
- **What**: Each `engine.recall()` call computes an embedding, runs semantic search, keyword search, temporal search, graph traversal, RRF fusion, and decay reranking. The fallback path makes 3 complete calls with the same query text but different filters. The embedding is recomputed each time (no caching).
- **Concern**: For the cold-start scenario (no person memories yet), the tool takes 3x normal latency. With the embedding model in memory, each call is fast (10-50ms), so total is 30-150ms — acceptable for now. But worth noting for future optimization (cache the embedding across calls within the same tool invocation).

### [W3] Person tag case normalization remains convention-only
- **File**: `src/cognitive_memory/engine.py:101` (tags passed through without normalization)
- **What**: Design Decision D8 requires person tags to be stored lowercase. `memory_who` lowercases its input for matching. But `memory_store` and `engine.store_memory` pass tags through unmodified. If the agent stores `tags=["person:Kaushik"]`, `memory_who("kaushik")` won't find it because tag matching is case-sensitive in SurrealDB.
- **Concern**: A single mixed-case tag creates a memory invisible to `memory_who`. This was acknowledged as O2 in the design dryrun, and the design chose "convention over enforcement." The risk is real but accepted.
- **Suggestion**: Consider normalizing tags matching `person:*` to lowercase in `engine.store_memory()` as a hardening measure. Simple regex: `tags = [t.lower() if t.startswith("person:") else t for t in tags]`.

### [W4] `decay.initial_stability.*` config values remain non-functional (pre-existing)
- **File**: `src/cognitive_memory/decay.py:26-38`, `config.default.yaml:3-9`
- **What**: `get_initial_stability()` accepts an optional `config_map` parameter, but no caller passes it. The values in `config.default.yaml` under `decay.initial_stability` are never read by the running system — only the hardcoded `defaults` dict in `decay.py` is used. This is a pre-existing issue (noted as O1 in dryrun-design-1), not introduced by this feature. The hardcoded defaults match the YAML, so identity (365.0) and person (90.0) work correctly.
- **Concern**: Misleading for operators who try to tune stability via config. Changing `decay.initial_stability.identity` to 730.0 in config has no effect.

### [W5] `test_mcp_client.py` module docstring still references "14 tools"
- **File**: `tests/test_mcp_client.py:1`
- **What**: Docstring says `"""MCP HTTP test client — spawns the server and exercises all 14 tools via Streamable HTTP."""` The tool count assertion was correctly updated to 16 (line 86), but the docstring was missed.
- **Concern**: Cosmetic only, no functional impact. Misleading for readers.

## Dryrun-Design Fix Verification

| Fix | Status | Notes |
|-----|--------|-------|
| C1: `REL_TABLES` missing "describes" | **FIXED** | `surreal_storage.py:36` — `"describes": "describes"` added to `REL_TABLES` dict. All 8 relationship types now present. |
| C2: `engine.py` `importance_cfg` missing identity/person bonuses | **FIXED** | `engine.py:73-74` — `identity_bonus` and `person_bonus` read from config with correct dot-notation keys (`importance.identity_bonus`, `importance.person_bonus`). Config values are now functional. |
| C3: Promotion pass elif ordering (EPISODIC->PERSON dead code) | **FIXED** | `consolidation.py:108-133` — EPISODIC branch (line 108) checks person promotion FIRST (line 109-113), then procedural (line 115-120), then semantic (line 122-126). SEMANTIC branch (line 128-133) has its own person promotion check. Both paths work. |
| W1: Silent schema migration failure | **FIXED** | `surreal_storage.py:105-106` — `except Exception as e: logger.warning(...)` replaces silent `pass`. Errors are now logged with the failing statement (truncated to 80 chars) and exception message. |
| W3: Test assertion hardcoded at 14 tools | **FIXED** | `test_mcp_client.py:86` — `assert len(tools.tools) == 16`. New tool tests for `memory_self` and `memory_who` added (lines 227-263). |
| W4: `to_person.min_access_count` config key not read | **FIXED** | `consolidation.py:93` — `to_person_access = config.get("consolidation.promotion.to_person.min_access_count", 3)` read at top of `_promotion_pass`. Used in both EPISODIC (line 111) and SEMANTIC (line 131) branches. |
| O3: `requires_person_tag` dead config | **FIXED** | Omitted from `config.default.yaml` as instructed (task.md line 39). No dead config key. |

## Requirement Coverage

| Story | Covered by code? | Covered by test? |
|-------|-----------------|-----------------|
| IM-1: Store identity facets | Yes — `MemoryType.IDENTITY` in models.py, `memory_store(type="identity")` works | Yes — `test_store_identity_memory` |
| IM-2: Recall self-knowledge selectively | Yes — `memory_self` tool, `memory_recall(type_filter="identity")` | Yes — `test_recall_identity_filter`, MCP `memory_self` test |
| IM-3: Identity resists decay | Partial — S0=365 ✅, archive exemption ✅, but merge pass can bypass (B1) | Partial — `test_identity_archive_exemption` covers archive; no merge test, no manual-archive test (G3) |
| IM-4: Update identity as it evolves | Yes — `memory_update` works polymorphically, versioning preserved | Yes — `test_identity_type_change_stability` |
| PM-1: Store person knowledge | Yes — `MemoryType.PERSON`, person tags convention | Yes — `test_store_person_memory` |
| PM-2: Recall person knowledge | Yes — `memory_who` tool, `memory_recall(type_filter="person")` | Yes — `test_recall_person_filter`, MCP `memory_who` test |
| PM-3: Person decay slowly | Yes — S0=90, person_archive_threshold=0.05 | Yes — `test_person_archive_threshold` |
| PM-4: Relate person memories | Yes — `DESCRIBES` RelType, `describes` edge table | Yes — `test_describes_relationship` |
| DT-1: memory_self | Yes — convenience wrapper with correct delegation | Yes — MCP test (lines 237-243) |
| DT-2: memory_who | Yes — with 3-tier fallback | Partial — happy path only (G1, G4) |
| INT-1: Unified retrieval | Yes — pipeline is polymorphic, no type-specific code | No explicit test (G2) |
| INT-2: Consolidation handles new types | Yes — archive exemption, person threshold, both promotion paths | Yes — `test_identity_archive_exemption`, `test_person_archive_threshold`, `test_promotion_episodic_to_person`, `test_promotion_semantic_to_person`, `test_no_promotion_without_person_tag` |

## Summary

| Bugs | Gaps | Warnings |
|------|------|----------|
| 2 | 5 | 5 |

**Verdict**: FAIL

Two bugs require fixes before this can ship:

1. **B1** (merge archives identity) — violates IM-3 acceptance criteria. The fix is 5-10 lines in `_cluster_and_merge`: either force identity memories to always be the merge primary, or skip merges involving identity memories entirely. Edge-case trigger, but the requirement is explicit.

2. **B2** (empty person name) — input validation gap. Returns random results for `memory_who("")` instead of an error. Fix is 3 lines of validation.

All 3 critical dryrun-design fixes (C1, C2, C3) and all 4 warnings (W1, W3, W4, O3) are properly addressed. The implementation is clean and closely follows the design. The gaps (G1-G5) are test coverage holes, not code defects — they should be added but don't block shipping after B1 and B2 are fixed.
