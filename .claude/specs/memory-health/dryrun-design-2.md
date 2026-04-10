# Design Dry-Run Report #2
**Document**: .claude/specs/memory-health/design.md
**Reviewed**: 2026-04-08

---

## Resolution Check — Round 1 Findings

### [C1] `importance` missing from section 2.2 SELECT — ✅ RESOLVED
Section 2.2 now reads:
```surql
SELECT id, string::slice(content, 0, 120) AS content_preview, memory_type, importance, stability, last_accessed, tags
FROM memory WHERE state = 'active'
```
`importance` is present. `_build_decay_report` accesses `mem["importance"]` — will not KeyError.

---

### [C2] No null backfill for absent types in `_build_decay_report` — ✅ RESOLVED
`ALL_MEMORY_TYPES` constant is declared, and after the main summary loop a backfill iterates all six types and fills any absent entry with `{avg_importance: null, avg_stability: null, avg_retrievability: null, count: 0}`. US-2.2 satisfied.

---

### [C3] `get_last_consolidation()` name collision — ✅ RESOLVED
New method is named `get_health_consolidation_summary()` throughout: architecture section, section 2.6, engine code in section 3, section 7 (Files Changed), and task.md. The existing `get_last_consolidation()` at line 515 is untouched.

---

### [C4] `get_health()` passes raw `None` for never-run store — ✅ RESOLVED
Engine now wraps `None`:
```python
consolidation = self.storage.get_health_consolidation_summary()
if consolidation is None:
    consolidation = {"never_run": True, "last_run_at": None, "last_run_summary": None}
else:
    consolidation["never_run"] = False
```
Response shape is always structured. US-5.1 satisfied.

---

### [C5] `_build_gaps` accesses `x["count"]` on raw nested lists — ✅ RESOLVED
Counter step is now present before the sort:
```python
counter = Counter(tag for tags in tag_rows for tag in tags)
counted = [{"tag": t, "count": c} for t, c in counter.items()]
total_unique = len(counter)
top_tags = sorted(counted, key=lambda x: x["count"], reverse=True)[:20]
```
`tag_rows` is correctly treated as `list[list[str]]`. No TypeError.

---

### [W1] `run_id` conditional dead code — ✅ RESOLVED
Section 2.6 and D8 commit to date-grouping exclusively. No schema-inspection branch. `LIMIT 100` raised to `LIMIT 500`.

---

### [W2] `_rows()` corrupts multi-statement result for orphan unconnected — ✅ RESOLVED
Section 2.4 now explicitly states: use `result[-1]` for the list, do **not** use `_rows()`. References the `vector_search_for_memory` pattern as the existing precedent.

---

### [W3] Count query cannot reuse LET-scoped `$edge_ids` — ✅ RESOLVED
Section 2.4 now uses a three-statement single-execution query. `result[-2]` = count, `result[-1]` = list. One round trip, union computed once.

---

### [W4] Type annotation mismatch on `by_type` — ✅ RESOLVED
Annotation changed from `dict[str, list[float]]` to `dict[str, dict[str, list[float]]]`. Accurate.

---

### [W5] Full `content` fetched for all active memories — ✅ RESOLVED
Section 2.2 query now uses `string::slice(content, 0, 120) AS content_preview`. `_build_decay_report` uses `mem["content_preview"]` with a comment noting it is already truncated. No Python-side `[:120]` slice needed.

---

## New Issues Found

### [W1-new] D5 decision log still says "Two round trips total"
- **Pass**: Consistency
- **What**: D5 reads: *"Union all `in` and `out` values from all 8 edge tables into a single set in one multi-statement query, then `NOT IN` filter. Two round trips total."* The W3 fix collapsed count + list into one three-statement execution — it is now **one** round trip, not two.
- **Risk**: No runtime impact. Minor mislead for readers of the decisions log.
- **Fix**: Change D5's last sentence to: *"One round trip total — count and list fetched in the same three-statement execution."*

---

### [W2-new] Architecture comment says "Four new query methods" but lists six
- **Pass**: Consistency
- **What**: The architecture block opens with `# Four new query methods (all SELECT, no writes):` but the bulleted list contains six methods (`get_counts_by_type_and_state`, `get_active_memories_for_decay`, `get_orphan_untagged`, `get_orphan_unconnected`, `get_tag_frequencies`, `get_health_consolidation_summary`).
- **Risk**: No runtime impact. Stale comment creates confusion during implementation review.
- **Fix**: Change comment to `# Six new SELECT-only methods:`.

---

### [O1-new] Count extraction from `result[-2]` not spelled out
- **Pass**: Interface Contracts (implementation guidance)
- **What**: Section 2.4 states *"Use `result[-2]` for the count row"* but does not specify the extraction: `result[-2][0]["count"]`. The `SELECT count() … GROUP ALL` query returns `[{"count": N}]` (a list with one dict). An implementer who writes `result[-2]` and passes it as an integer will get a type error.
- **Risk**: Low — the pattern is consistent with how existing count queries are handled in `surreal_storage.py` — but naming it explicitly would prevent a wasted debugging round.
- **Suggestion**: Add one line: *"Extract as `result[-2][0]['count']` — the GROUP ALL query returns a single-row list."*

---

### [O2-new] `_build_decay_report` — `if buckets["ret"]:` guard is now redundant
- **Pass**: Completeness
- **What**: Every `by_type[mem_type]` entry is created by the defaultdict factory and immediately receives `ret.append(r)` in the same loop iteration. The `if buckets["ret"]:` guard can therefore never be False for a type that appears in `by_type`. The guard is harmless but misleads a reader into thinking an empty-ret case is possible within `by_type`.
- **Risk**: None at runtime. The backfill loop handles genuinely absent types (those that never appear in `by_type`).
- **Suggestion**: Remove the `if buckets["ret"]:` branch and make the summary assignment unconditional for the types in `by_type`. Alternatively, add a comment: `# guard is theoretically unreachable — every entry in by_type has ≥1 ret value` to explain the intent.

---

## Summary

| Category | Round 1 | Round 2 |
|----------|---------|---------|
| Criticals | 5 (all open) | 0 |
| Warnings | 5 (all open) | 2 (minor, no runtime impact) |
| Observations | 3 | 2 (minor guidance gaps) |

**Verdict**: PASS

All five round-1 criticals and all five round-1 warnings are resolved. The two new warnings (stale comment in D5, stale "Four" count in architecture block) are cosmetic — they do not affect correctness, data flow, or any acceptance criterion. The two observations are implementation guidance improvements, not blockers.

**Recommendation**: Fix W1-new and W2-new (both are one-line edits) before handing off to implementation, then proceed directly. O1-new and O2-new can be addressed inline during implementation without a design revision.
