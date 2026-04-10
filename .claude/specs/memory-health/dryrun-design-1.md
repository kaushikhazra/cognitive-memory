# Design Dry-Run Report #1
**Document**: .claude/specs/memory-health/design.md
**Reviewed**: 2026-04-08

---

## Critical Gaps

### [C1] `importance` missing from `get_active_memories_for_decay()` query
- **Pass**: Interface Contracts
- **What**: Design section 2.2 specifies `SELECT id, content, memory_type, stability, last_accessed, tags FROM memory WHERE state = 'active'` — `importance` is not in the SELECT list. But `_build_decay_report` (section 3) immediately accesses `mem["importance"]` for every record: `by_type[mem["memory_type"]]["imp"].append(mem["importance"])`. This will raise a `KeyError` at runtime on every call.
- **Risk**: `memory_health` crashes for any non-empty store. The feature is broken on first use.
- **Fix**: Add `importance` to the SELECT in section 2.2. (task.md already has the correct query: `SELECT id, content, memory_type, importance, stability, last_accessed, tags ...` — sync design.md to match.)

---

### [C2] `_build_decay_report` never fills null averages for types with zero active memories
- **Pass**: Completeness / Edge Cases
- **What**: US-2.2 requires: *"Types with no active memories appear with null averages, not omitted."* The `_build_decay_report` logic only iterates `active_memories`; types absent from the DB never touch `by_type`. After the loop, only types that had at least one record appear in `by_type_summary`. There is no fill step that adds the remaining five (or six) types with `null` averages. An empty-type entry only appears via the `else` branch, but that branch is dead code — it only executes when `buckets["ret"]` is empty, which cannot happen for a type that was never inserted into `by_type` in the first place.
- **Risk**: Types with zero active memories are silently omitted from `decay.by_type`. Callers checking all six types get `KeyError` or incomplete data. US-2.2 acceptance criterion fails.
- **Fix**: After the loop, iterate over all six `MemoryType` values and backfill any type missing from `by_type_summary` with `{avg_importance: null, avg_stability: null, avg_retrievability: null, count: 0}`.

---

### [C3] `get_last_consolidation()` name collides with an existing `SurrealStorage` method
- **Pass**: Interface Contracts
- **What**: `SurrealStorage.get_last_consolidation()` already exists at `surreal_storage.py:515`. It returns a raw single-row dict with keys `{id, action, source_ids, target_id, reason, created_at}`. The design asks for a new `get_last_consolidation()` with entirely different semantics: fetch the last 100 rows, group into runs, return `{last_run_at, never_run, last_run_summary}`. Adding the new method under the same name silently breaks `get_consolidation_summary()` (lines 532–553), which calls `self.get_last_consolidation()` to get `last["created_at"]` for a timestamp filter. That code would receive a summary dict and crash on `last["created_at"]`.
- **Risk**: Overwriting the method breaks the existing `memory_consolidate` → `get_consolidation_summary()` path. Two methods with the same name in the same class is impossible — one will shadow the other.
- **Fix**: Rename the new health method to `get_health_consolidation_summary() -> dict`. Update all references in the design and tasks.

---

### [C4] `consolidation` section returns `None` instead of structured response when never run
- **Pass**: Edge Cases / Data Flow
- **What**: `engine.get_health()` does:
  ```python
  consolidation = self.storage.get_last_consolidation()
  return { ..., "consolidation": consolidation }
  ```
  When no consolidation has ever run, `get_last_consolidation()` returns `None`. The response becomes `"consolidation": null`. US-5.1 requires the response to always contain a structured object: `{never_run: true, last_run_at: null, last_run_summary: null}`. The engine passes the raw storage result directly without any wrapping logic.
- **Risk**: Callers receive `"consolidation": null` and cannot safely access `consolidation.never_run`, `consolidation.last_run_at`, or `consolidation.last_run_summary`. US-5.1 acceptance criteria all fail on a fresh store.
- **Fix**: The engine (not storage) should own the shape. Add a guard in `get_health()`:
  ```python
  consolidation = self.storage.get_health_consolidation_summary()
  if consolidation is None:
      consolidation = {"never_run": True, "last_run_at": None, "last_run_summary": None}
  else:
      consolidation["never_run"] = False
  ```
  Or have the storage method always return the full structure (never `None`).

---

### [C5] `_build_gaps` uses `x["count"]` on data that has not been counted yet
- **Pass**: Data Flow / Interface Contracts
- **What**: Design section 2.5 says `get_tag_frequencies()` returns raw nested lists — `list[list[str]]` — with flattening and counting delegated to the engine. Decision D7 confirms: *"Tag data is fetched as arrays, flattened and counted in Python."* But `_build_gaps` does this immediately:
  ```python
  top_tags = sorted(tag_rows, key=lambda x: x["count"], reverse=True)[:20]
  total_unique = len(tag_rows)
  ```
  `tag_rows` is `list[list[str]]` at this point; `x["count"]` will raise `TypeError` because each `x` is a list, not a dict. The Counter step described in D7 is entirely absent from the `_build_gaps` code.
- **Risk**: `_build_gaps` crashes on every call. `gaps.tag_coverage` is never populated. US-4.2 fails completely.
- **Fix**: Either (a) have `get_tag_frequencies()` return pre-counted `list[{tag: str, count: int}]` dicts from the storage layer and update the task accordingly, or (b) insert the missing Counter step at the top of `_build_gaps`:
  ```python
  from collections import Counter
  counter = Counter(tag for tags in tag_rows for tag in tags)
  counted = [{"tag": t, "count": c} for t, c in counter.items()]
  total_unique = len(counter)
  top_tags = sorted(counted, key=lambda x: x["count"], reverse=True)[:20]
  ```
  The task description already says "flattening and counting done in engine layer" — option (b) aligns with that. Adopt option (b) and add the Counter code to the design.

---

## Warnings

### [W1] `run_id` does not exist in `consolidation_log` — heuristic will always be used
- **Pass**: Interface Contracts / Edge Cases
- **What**: Design section 2.6 says: *"The implementation must inspect the actual schema and choose [run_id or date-heuristic] accordingly."* But `schema.surql` definitively defines `consolidation_log` with no `run_id` field. There is nothing to inspect — the date heuristic is the only option. Additionally, `LIMIT 100` could silently truncate a consolidation run that produced more than 100 log entries (possible on large stores after long neglect).
- **Risk**: If the implementation adds a schema-inspection branch, it adds dead code. If a consolidation run exceeds 100 actions, `last_run_summary` undercounts.
- **Suggestion**: Remove the conditional schema-inspection note. Commit to same-UTC-date grouping. Change `LIMIT 100` to `LIMIT 500` or add a note on the assumption (consolidation runs produce < 100 actions on typical stores).

---

### [W2] `_rows()` incorrectly flattens `LET + SELECT` multi-statement results for orphan unconnected query
- **Pass**: Data Flow
- **What**: `get_orphan_unconnected()` will execute a two-statement query (`LET $edge_ids = ...; SELECT ... WHERE id NOT IN $edge_ids`). SurrealDB returns multi-statement results as a list-of-results, one per statement. `_rows()` (lines 73–93 of `surreal_storage.py`) flattens **all** nested results into one list. The LET statement returns an empty/None result, but the subsequent SELECT result is what we want. `_rows()` will mix them, producing a corrupted result. The existing `vector_search_for_memory()` avoids this by using `result[-1]` directly (line 320) — the design must specify the same pattern here.
- **Risk**: The orphan unconnected list contains garbage data or is empty when it shouldn't be. US-3.2 fails silently.
- **Suggestion**: Specify that `get_orphan_unconnected()` uses `result[-1]` (the last statement's result) rather than `self._rows(result)`, mirroring the existing `vector_search_for_memory` pattern.

---

### [W3] Orphan unconnected count query must re-execute the full edge-table union
- **Pass**: Data Flow / Performance
- **What**: Design section 2.4 says the count comes from "a parallel `SELECT count()` query using the same `$edge_ids` set." But `$edge_ids` is a LET-scoped variable — it exists only within the same multi-statement query execution. A separate count query cannot reference it. The count query must re-execute the entire 16-subquery union from scratch.
- **Risk**: Two full union scans instead of one doubles query cost. At large edge counts this could push the 3-second budget.
- **Suggestion**: Combine both the count and the paginated list into a single multi-statement execution: `LET $edge_ids = ...; SELECT count() FROM memory WHERE state = 'active' AND id NOT IN $edge_ids GROUP ALL; SELECT id, ... WHERE id NOT IN $edge_ids ORDER BY created_at ASC LIMIT 51`. Use `result[-2]` for count, `result[-1]` for list. One round trip, union computed once.

---

### [W4] Type annotation mismatch in `_build_decay_report`
- **Pass**: Completeness
- **What**: `by_type: dict[str, list[float]] = defaultdict(lambda: {"imp": [], "stab": [], "ret": []})` — the annotation says `dict[str, list[float]]` but the lambda returns a `dict[str, list]`, not a `list[float]`. Type checkers (mypy, pyright) will flag every access to `by_type[x]["imp"]` as an error.
- **Risk**: No runtime failure, but the annotation actively misleads. If type checking is run in CI, this will fail.
- **Suggestion**: Change annotation to `dict[str, dict[str, list[float]]]`.

---

### [W5] `get_active_memories_for_decay()` fetches `content` for all active memories
- **Pass**: Performance
- **What**: The query fetches `content` (potentially hundreds of characters per memory) for all active records. On a 10,000-memory store this is 1–3 MB of string data, most of which is never used (only at-risk memories use `content` for the preview). Content truncation to 120 chars happens in Python after the full strings are already deserialized.
- **Risk**: Memory pressure and unnecessary serialization overhead. May contribute to breaching the 3-second budget on large stores.
- **Suggestion**: Consider `string::slice(content, 0, 120) AS content_preview` in the query, or accept the cost now and revisit (the design already flags this as a known trade-off). Document the decision explicitly so it is not accidentally re-examined during implementation.

---

## Observations

### [O1] Retrievability formula should be stated in the design
The design says retrieval is "consistent with how `retrieval.py` already works" but never states the formula. `decay.py` implements `R(t) = exp(-elapsed_days / (9 × S))` where elapsed_days = `(now - last_accessed).total_seconds() / 86400`. The design doc would benefit from one line stating this formula explicitly, so reviewers can verify the at-risk threshold (0.3) and identity exclusion (D4) without reading the source.

---

### [O2] Existing `get_consolidation_summary()` has a latent grouping bug
The existing `get_consolidation_summary()` in `surreal_storage.py` (lines 532–553) filters consolidation_log with `WHERE created_at >= $since` where `$since` is the exact `created_at` of the single most-recent entry. This effectively returns only that one entry (and any others with the identical timestamp). Health design's 100-row + date-grouping approach is more robust. The existing method is not called by the health feature, but the health implementation should not make things worse.

---

### [O3] Integration test wording: "live SurrealDB test instance"
task.md Phase 4 says "using a live SurrealDB test instance." The existing `surreal_storage.py` constructor accepts `mem://` for in-memory SurrealDB (no separate process). Clarify that the integration test uses `SurrealStorage("mem://")`, not an external process, to keep tests self-contained and fast.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 5        | 5        | 3            |

**Verdict**: FAIL

Five critical gaps must be resolved before implementation begins:
- **C1** and **C5** are silent runtime crashes (KeyError / TypeError) that will fire on the first call to `memory_health`.
- **C2** leaves US-2.2's null-fill requirement unimplemented.
- **C3** is a name collision that breaks an existing production path.
- **C4** means the never-run edge case produces a structurally wrong response, violating all of US-5.1.

Resolve all five, then promote to implementation.
