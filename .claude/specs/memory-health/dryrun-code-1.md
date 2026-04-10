# Code Dry-Run Report #1

**Scope**: `src/cognitive_memory/surreal_storage.py` (6 new methods), `src/cognitive_memory/engine.py` (`_build_totals`, `_build_decay_report`, `_build_gaps`, `get_health`), `src/cognitive_memory/server.py` (`memory_health`), `tests/test_memory_health.py`
**Design**: `.claude/specs/memory-health/design.md` (PASS after dryrun-design-2)
**Reviewed**: 2026-04-08
**Taskyn tracking**: skipped — no spec node found in search.

---

## Dryrun-Design-2 Fix Verification

| Fix | Status | Evidence |
|-----|--------|----------|
| C1 — `importance` in decay SELECT | ✅ | `surreal_storage.py:568` — `memory_type, importance, stability, last_accessed, tags` |
| C2 — type backfill in `_build_decay_report` | ✅ | `engine.py:103–111` — backfill loop over `_ALL_MEMORY_TYPES` |
| C3 — method name `get_health_consolidation_summary` | ✅ | `surreal_storage.py:693`, `engine.py:627` — no collision with `get_last_consolidation` at line 515 |
| C4 — None → never_run shape | ✅ | `engine.py:627–631` — explicit `if consolidation is None:` wrap |
| C5 — Counter step before sort | ✅ | `engine.py:151–157` — `Counter` → `counted` list → sorted top 20 |
| W1-new — D5 "Two round trips" → "One" | ✅ | Design updated; code matches one-round-trip pattern |
| W2-new — "Four new methods" → "Six" | ✅ | Design updated |

All five round-1 criticals and all five round-1 warnings correctly implemented.

---

## Bugs (will cause incorrect behavior)

### [B1] Dead code and typo in `test_sparse_threshold_boundary_at_5_pct_not_sparse`
- **File**: `tests/test_memory_health.py:213–215`
- **Pass**: Pass 8 — Code Quality
- **What**: Line 213 assigns `totals = self._make_totals({"semantic": 90, "working=5": 0})`. The key `"working=5"` is not a valid memory type — `_make_totals` silently ignores it, producing `working=0`. Line 216 then overwrites `totals` entirely with the correct value. The first assignment is dead code. The docstring also references different numbers ("semantic=50, episodic=46, working=4") than what either assignment uses, compounding the confusion.
- **Impact**: Test passes correctly (line 216's value wins), but the dead assignment and stale comment make the test's intent opaque. A future reader may conclude the boundary check covers two scenarios when it covers only one.
- **Fix**:
  ```python
  def test_sparse_threshold_boundary_at_5_pct_not_sparse(self):
      """Type at exactly 5% is not sparse (pct < 5.0 is False at exactly 5%)."""
      # semantic=95, working=5, total=100 → working = 5.0% → NOT sparse
      totals = self._make_totals({"semantic": 95, "working": 5})
      result = _build_gaps(totals, [], 0)
      sparse_names = [e["type"] for e in result["sparse_types"]]
      assert "working" not in sparse_names
  ```

---

## Gaps (missing implementation)

### [G1] At-risk entry field schema is untested
- **File**: `tests/test_memory_health.py:101–108`
- **Pass**: Pass 4 — Input Validation / Coverage
- **What**: `test_at_risk_below_threshold_included` verifies `at_risk_count >= 1` and that an entry has `memory_type == "episodic"`. US-2.1 requires seven specific fields per entry: `id`, `content_preview`, `memory_type`, `retrievability` (4 d.p.), `last_accessed`, `stability`, `tags`. No test asserts all seven are present with correct types.
- **Design ref**: US-2.1 acceptance criteria — at-risk entry structure.

### [G2] Consolidation date-grouping logic has no meaningful test coverage
- **File**: `tests/test_memory_health.py:282–287`
- **Pass**: Pass 2 — Execution Path Trace
- **What**: `test_consolidation_never_run_on_empty_store` only covers the `rows == []` → `None` → `never_run=True` branch. The non-trivial grouping algorithm in `get_health_consolidation_summary` (date extraction, `most_recent_date` accumulation, per-action counting) is completely untested. There is no test that inserts consolidation log entries, calls `get_health()`, and verifies the resulting `last_run_at`, `never_run=False`, and `last_run_summary` counts.
- **Design ref**: US-5.1 acceptance criteria; design section 2.6 (grouping by UTC date).

### [G3] `test_orphan_no_relations_detected` does not assert orphan membership
- **File**: `tests/test_memory_health.py:304–314`
- **Pass**: Pass 4 — Input Validation / Coverage
- **What**: The test asserts only `isinstance(count, int) and count >= 0` — always True regardless of the feature working or broken. It does not assert that the newly stored memory (which has no manually created relations) appears in `no_relations`. The auto-linking from `store_memory` complicates this (the stored memory may get auto-linked if embeddings fire), but the test should at minimum assert `no_relations_count >= 1` or inspect `no_relations` entries after inserting an isolated memory with a unique enough string to avoid auto-linking.
- **Design ref**: US-3.2 acceptance criteria.

### [G4] `gaps.tag_coverage.untagged_count` matching `orphans.no_tags_count` is untested
- **File**: `tests/test_memory_health.py` (missing test)
- **Pass**: Pass 1 — Design Conformance
- **What**: US-4.2 explicitly states "`gaps.tag_coverage.untagged_count` — count of active memories with no tags (matches `orphans.no_tags_count`)". No test verifies these two values are equal in the same report. Since they originate from different storage calls (a dedicated count query in `get_orphan_untagged` vs the `untagged_count` parameter threaded into `_build_gaps`), a bug that disconnects them would go undetected.
- **Design ref**: US-4.2 acceptance criteria, first bullet.

---

## Warnings (potential issues)

### [W1] `get_tag_frequencies` uses `SELECT tags` instead of design's `SELECT VALUE tags`
- **File**: `src/cognitive_memory/surreal_storage.py:688`
- **Pass**: Pass 1 — Design Conformance
- **What**: Design section 2.5 specifies `SELECT VALUE tags FROM memory WHERE state = 'active'` which returns raw field values (`list[list[str]]` directly). The code uses `SELECT tags FROM memory WHERE state = 'active'` (no `VALUE` keyword), which returns row dicts (`[{"tags": [...]}, ...]`). The implementation correctly handles this via `r.get("tags") or []` on each row, producing the same final type. Functionally identical, but the deviation from the spec is silent.
- **Risk**: Low. If a future developer reads the design query and aligns to it without reading the implementation, they might rewrite this to use `SELECT VALUE tags` and then not unwrap from dicts — the opposite direction of the current deviation. Not dangerous today, but a source of confusion.

### [W2] `if buckets["ret"]:` guard in `_build_decay_report` is unreachable with no comment
- **File**: `src/cognitive_memory/engine.py:95`
- **Pass**: Pass 8 — Code Quality
- **What**: Every entry added to `by_type_buckets` gets at least one `ret.append(r)` in the same iteration. So `buckets["ret"]` is always non-empty for any key in `by_type_buckets`. The guard can never be False for any type that appears in the dict. Design dryrun-2 noted this as O2-new. The guard is still in the code with no comment explaining it's intentionally kept as a safety net.
- **Risk**: None at runtime. Misleads reviewers into thinking an empty-ret case is possible within `by_type_buckets`.

### [W3] `elif isinstance(count_raw, dict)` in `get_orphan_unconnected` misses status-dict format
- **File**: `src/cognitive_memory/surreal_storage.py:661–662`
- **Pass**: Pass 7 — Contract Violations
- **What**: The count extraction reads:
  ```python
  elif isinstance(count_raw, dict):
      true_count = count_raw.get("cnt", 0)
  ```
  If the SurrealDB SDK ever returns a status-wrapped dict — `{"status": "OK", "result": [{"cnt": N}]}` — this branch would look for `"cnt"` directly in the wrapper, find nothing, and silently return `true_count = 0`. The `_check_result` helper in this same file acknowledges that the SDK can return `{"status": "ERR", ...}` dicts, confirming the format is SDK-version-dependent.
- **Risk**: Current embedded SDK appears to return raw lists for multi-statement queries (evidenced by `vector_search_for_memory` working without status-dict handling). Low risk today, but if the SDK version changes the count would silently be zero while the list would still populate — producing a response where `no_relations_count = 0` but `no_relations` is non-empty.

### [W4] No logging in new storage methods — errors surface only as generic MCP errors
- **File**: `src/cognitive_memory/surreal_storage.py:557–733`
- **Pass**: Pass 3 — Error Path Trace
- **What**: All six new health query methods call `self._db.query(...)` with no `logger.debug` or `logger.warning` wrapping. If a query fails (e.g., edge table `describes` doesn't exist in an older schema, or a malformed date in the consolidation log causes `_parse_dt` to raise), the exception propagates to `memory_health()` where it is caught by `except Exception as e: return _error(str(e))`. The error message is returned to the caller but nothing is logged server-side.
- **Risk**: In production, a health check failure produces an opaque `_error(str(e))` response with no server log to diagnose which query failed or why.

---

## Style (code quality, conventions)

### [S1] `from collections import Counter` is an inline import inside `_build_gaps`
- **File**: `src/cognitive_memory/engine.py:127`
- **What**: `defaultdict` and `mean` are imported at module level (lines 6–9), but `Counter` is imported inside `_build_gaps`. This is inconsistent. Python caches module imports so there's no runtime cost, but the convention break is unnecessary. Move `from collections import Counter` to the module-level block alongside `from collections import defaultdict`.

---

## Summary

| Bugs | Gaps | Warnings | Style |
|------|------|----------|-------|
| 1 | 4 | 4 | 1 |

**Verdict**: PASS WITH WARNINGS

The production code is correct. All five dryrun-design-2 criticals (C1–C5) are properly implemented. The single bug (B1) is in the test file — dead code from a typo that doesn't affect the test's outcome. The four gaps are missing test cases for non-trivial paths (consolidation grouping, at-risk schema, orphan membership, count consistency). The four warnings are low-risk concerns about silent SDK-format changes (W3), missing server-side diagnostics (W4), and two code clarity issues (W2, W1).

**Recommended before merge**: Fix B1 (one-line test cleanup) and add G2 (consolidation grouping test) — the grouping logic is the most complex untested path. G1, G3, G4 are straightforward additions. W1–W4 can be addressed in a follow-up.
