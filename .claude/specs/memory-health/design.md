# Memory Health Report — Design

## Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Retrievability computed in Python, not queried from DB | The stored `retrievability` field goes stale between consolidation sweeps. Health report must reflect current state. Fetch `last_accessed` + `stability` for all active memories, call `decay.compute_retrievability()` in Python. Consistent with how retrieval.py already works. |
| D2 | At-risk threshold fixed at 0.3 | Matches the feature request. Sits between `classify_decay_state`'s "fading" (< 0.5) and "forgotten" (< 0.2) zones — catches memories with meaningful decay before they fall off entirely. No config knob — health report is diagnostic, not tunable at query time. |
| D3 | Sparse type threshold fixed at 5% of active total | Simple, self-explanatory, no magic. `identity` excluded because it is expected to have very few entries by design (one or two self-description memories). |
| D4 | `identity` excluded from at-risk | Initial stability for `identity` is 365 days. A memory accessed 1 year ago has R ≈ e^(-1/9) ≈ 0.895. Retrievability never meaningfully approaches 0.3 within realistic timescales. Including them would pollute the at-risk list with false positives. |
| D5 | Orphan relation check via union of all edge-table IDs | Checking each memory against each edge table individually is O(n × 8) queries. Union all `in` and `out` values from all 8 edge tables into a single set in one multi-statement query, then `NOT IN` filter. One round trip total — count and list fetched in the same three-statement execution. |
| D6 | Lists capped at 50, true counts always provided | Prevents the response from becoming enormous on large neglected stores. The caller always has the count and can decide whether to investigate further (e.g., via `memory_list`). |
| D7 | Top 20 tags for coverage | Enough to show the dominant topic clusters. Tag data is fetched as arrays, flattened and counted in Python — no SurrealDB array aggregation complexity. |
| D8 | Consolidation summary reads `consolidation_log` directly | The existing `consolidate()` engine method writes to this table. Health report reads the most recent 500 rows and groups by UTC date to reconstruct the last run's action counts. `run_id` does not exist in the schema — date-grouping is the only option. |
| D9 | Single new engine method `engine.get_health()` | Keeps server.py thin. The engine orchestrates: calls storage for raw data, calls `decay.compute_retrievability()` for fresh scores, assembles the report dict. Mirrors the existing engine.get_stats() pattern. |
| D10 | No new dependencies | Everything uses existing SurrealDB driver, `decay.py`, `models.py`. |

---

## 1. Architecture

```
server.py
  └─ memory_health()          # MCP tool — no params, returns _response(data, elapsed_ms)
       └─ engine.get_health()  # Orchestrator — calls storage, computes decay, assembles report

engine.py
  └─ get_health() -> dict     # New method

surreal_storage.py            # Six new SELECT-only methods:
  ├─ get_counts_by_type_and_state() -> dict
  ├─ get_active_memories_for_decay() -> list[dict]   # id, content_preview, type, importance, stability, last_accessed, tags
  ├─ get_orphan_untagged() -> tuple[list[dict], int]  # (capped list, true count)
  ├─ get_orphan_unconnected() -> tuple[list[dict], int]
  ├─ get_tag_frequencies() -> list[list[str]]        # raw nested tag arrays; engine flattens and counts
  └─ get_health_consolidation_summary() -> dict | None  # last run summary or None

decay.py                      # compute_retrievability() — already exists, used as-is
```

---

## 2. SurrealDB Queries

### 2.1 Counts by type and state

```surql
SELECT memory_type, state, count() AS cnt
FROM memory
GROUP BY memory_type, state
```

Returns rows like `{memory_type: "episodic", state: "active", cnt: 45}`. Python post-processes into:

```python
{
    "working":    {"active": 3, "archived": 1},
    "episodic":   {"active": 45, "archived": 12},
    "semantic":   {"active": 128, "archived": 4},
    "procedural": {"active": 12, "archived": 0},
    "identity":   {"active": 2, "archived": 0},
    "person":     {"active": 7, "archived": 0},
}
```

All six types always present, defaulting to 0 if absent from query results.

### 2.2 Active memories for decay computation

```surql
SELECT id, string::slice(content, 0, 120) AS content_preview, memory_type, importance, stability, last_accessed, tags
FROM memory
WHERE state = 'active'
```

No `embedding` column — avoids deserializing large binary blobs for a health check. Content is truncated to 120 chars in the query so the full string is never deserialised for all active memories (only at-risk entries expose the preview). Python then calls `compute_retrievability(last_accessed, stability, now)` for each record. This is the same approach used by `retrieval.py` during the decay-reranking phase.

### 2.3 Orphans — no tags

```surql
SELECT id, string::slice(content, 0, 120) AS content_preview, memory_type, created_at
FROM memory
WHERE state = 'active'
  AND (tags IS NONE OR array::len(tags) = 0)
ORDER BY created_at ASC
LIMIT 51
```

Fetch 51 to distinguish "exactly 50" from "more than 50". True count comes from a separate `SELECT count() ... GROUP ALL` without the LIMIT.

### 2.4 Orphans — no relations

Three-statement multi-statement query in one SurrealDB round trip. The LET variable is scoped to the execution — a separate count query cannot reuse it, so count and list are fetched together:

```surql
LET $edge_ids = array::distinct(array::flatten([
    (SELECT VALUE in  FROM causes),
    (SELECT VALUE out FROM causes),
    (SELECT VALUE in  FROM follows),
    (SELECT VALUE out FROM follows),
    (SELECT VALUE in  FROM contradicts),
    (SELECT VALUE out FROM contradicts),
    (SELECT VALUE in  FROM supports),
    (SELECT VALUE out FROM supports),
    (SELECT VALUE in  FROM relates_to),
    (SELECT VALUE out FROM relates_to),
    (SELECT VALUE in  FROM supersedes),
    (SELECT VALUE out FROM supersedes),
    (SELECT VALUE in  FROM part_of),
    (SELECT VALUE out FROM part_of),
    (SELECT VALUE in  FROM describes),
    (SELECT VALUE out FROM describes)
]));

SELECT count() FROM memory WHERE state = 'active' AND id NOT IN $edge_ids GROUP ALL;

SELECT id, string::slice(content, 0, 120) AS content_preview, memory_type, tags, created_at
FROM memory
WHERE state = 'active'
  AND id NOT IN $edge_ids
ORDER BY created_at ASC
LIMIT 51;
```

SurrealDB returns a list-of-results (one per statement). Use `result[-2]` for the count row, `result[-1]` for the list. Do **not** use `_rows()` here — it flattens all statements and corrupts the result. This mirrors the existing `vector_search_for_memory` pattern in `surreal_storage.py` which also uses `result[-1]` directly for multi-statement queries.

### 2.5 Tag frequencies

```surql
SELECT VALUE tags FROM memory WHERE state = 'active'
```

Returns `list[list[str]]`. Python flattens, counts with `collections.Counter`, returns top 20 sorted descending plus `total_unique_tags`.

### 2.6 Last consolidation run

Method name: `get_health_consolidation_summary()` (distinct from the existing `get_last_consolidation()` at line 515 which returns a single raw row).

```surql
SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT 500
```

`consolidation_log` has no `run_id` column. Rows are grouped by their `created_at` UTC date — same date = same run. `LIMIT 500` is a safe upper bound; consolidation on typical stores produces well under 500 actions per run. Python takes the most-recent date's group and counts actions by type:

```python
{
    "last_run_at": "2026-04-07T14:22:00Z",
    "never_run": False,
    "last_run_summary": {
        "promote": 2,
        "archive": 3,
        "merge": 1,
        "flag_contradiction": 0
    }
}
```

Returns `None` when the table is empty (never run). The engine wraps `None` into a structured response — see section 3.

---

## 3. Engine Method — `get_health()`

```python
def get_health(self) -> dict:
    start = datetime.now(timezone.utc)
    now = start

    # 1. Counts
    counts_raw = self.storage.get_counts_by_type_and_state()
    totals = _build_totals(counts_raw)  # fills all 6 types, computes by_state, total

    # 2. Decay (fetch active memories, compute fresh retrievability)
    active_memories = self.storage.get_active_memories_for_decay()
    decay_report = _build_decay_report(active_memories, now)
    # decay_report contains: at_risk (list), at_risk_count, by_type

    # 3. Orphans
    untagged, untagged_count = self.storage.get_orphan_untagged()
    unconnected, unconnected_count = self.storage.get_orphan_unconnected()

    # 4. Storage gaps
    tag_rows = self.storage.get_tag_frequencies()
    gaps = _build_gaps(totals, tag_rows, untagged_count)
    # gaps contains: empty_types, sparse_types, tag_coverage

    # 5. Consolidation
    consolidation = self.storage.get_health_consolidation_summary()
    if consolidation is None:
        consolidation = {"never_run": True, "last_run_at": None, "last_run_summary": None}
    else:
        consolidation["never_run"] = False

    return {
        "generated_at": now.isoformat(),
        "totals": totals,
        "decay": decay_report,
        "orphans": {
            "no_tags": untagged,
            "no_tags_count": untagged_count,
            "no_relations": unconnected,
            "no_relations_count": unconnected_count,
        },
        "gaps": gaps,
        "consolidation": consolidation,
    }
```

### `_build_decay_report(active_memories, now)` — Python logic

```python
def _build_decay_report(active_memories: list[dict], now: datetime) -> dict:
    AT_RISK_THRESHOLD = 0.3
    IDENTITY_TYPE = "identity"

    ALL_MEMORY_TYPES = ["working", "episodic", "semantic", "procedural", "identity", "person"]

    at_risk_all = []
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"imp": [], "stab": [], "ret": []})

    for mem in active_memories:
        r = compute_retrievability(mem["last_accessed"], mem["stability"], now)
        by_type[mem["memory_type"]]["imp"].append(mem["importance"])
        by_type[mem["memory_type"]]["stab"].append(mem["stability"])
        by_type[mem["memory_type"]]["ret"].append(r)

        if r < AT_RISK_THRESHOLD and mem["memory_type"] != IDENTITY_TYPE:
            at_risk_all.append({
                "id": mem["id"],
                "content_preview": mem["content_preview"],  # already truncated to 120 chars by DB query
                "memory_type": mem["memory_type"],
                "retrievability": round(r, 4),
                "last_accessed": mem["last_accessed"].isoformat(),
                "stability": mem["stability"],
                "tags": mem["tags"],
            })

    at_risk_all.sort(key=lambda x: x["retrievability"])

    by_type_summary = {}
    for mem_type, buckets in by_type.items():
        if buckets["ret"]:
            by_type_summary[mem_type] = {
                "avg_importance":    round(mean(buckets["imp"]), 4),
                "avg_stability":     round(mean(buckets["stab"]), 4),
                "avg_retrievability": round(mean(buckets["ret"]), 4),
                "count": len(buckets["ret"]),
            }
        # no else branch needed — types with zero entries are backfilled below

    # Backfill types absent from active_memories with null averages (US-2.2)
    for mem_type in ALL_MEMORY_TYPES:
        if mem_type not in by_type_summary:
            by_type_summary[mem_type] = {
                "avg_importance": None, "avg_stability": None,
                "avg_retrievability": None, "count": 0,
            }

    return {
        "at_risk": at_risk_all[:50],
        "at_risk_count": len(at_risk_all),
        "by_type": by_type_summary,
    }
```

### `_build_gaps(totals, tag_rows, untagged_count)` — Python logic

```python
SPARSE_THRESHOLD_PCT = 5.0
EXCLUDED_FROM_SPARSE = {"identity"}

total_active = totals["by_state"]["active"]
empty_types = [t for t, v in totals["by_type"].items() if v["active"] == 0]

sparse_types = []
for mem_type, counts in totals["by_type"].items():
    if mem_type in EXCLUDED_FROM_SPARSE:
        continue
    active = counts["active"]
    if active == 0:
        continue  # already in empty_types
    pct = (active / total_active * 100) if total_active > 0 else 0.0
    if pct < SPARSE_THRESHOLD_PCT:
        sparse_types.append({
            "type": mem_type,
            "active_count": active,
            "pct_of_active": round(pct, 1),
        })

# tag_rows is list[list[str]] from storage — flatten and count in Python (D7)
from collections import Counter
counter = Counter(tag for tags in tag_rows for tag in tags)
counted = [{"tag": t, "count": c} for t, c in counter.items()]
total_unique = len(counter)
top_tags = sorted(counted, key=lambda x: x["count"], reverse=True)[:20]

return {
    "empty_types": empty_types,
    "sparse_types": sparse_types,
    "tag_coverage": {
        "untagged_count": untagged_count,
        "top_tags": top_tags,
        "total_unique_tags": total_unique,
    },
}
```

---

## 4. MCP Tool — `memory_health` in `server.py`

```python
@mcp.tool()
def memory_health() -> str:
    """Return a diagnostic health report for the memory store.

    Includes: memory counts by type and state, at-risk decay list,
    orphan detection (untagged and unconnected), storage gaps, and
    consolidation history. Read-only — no side effects.
    """
    start = time.time()
    engine = _get_engine()
    try:
        report = engine.get_health()
        return _response(report, (time.time() - start) * 1000)
    except Exception as e:
        return _error(str(e))
```

No parameters. No optional filters. Health report is always the full picture.

---

## 5. Response Schema

```json
{
  "success": true,
  "data": {
    "generated_at": "2026-04-08T10:00:00.000000+00:00",
    "totals": {
      "by_type": {
        "working":    {"active": 3,   "archived": 1},
        "episodic":   {"active": 45,  "archived": 12},
        "semantic":   {"active": 128, "archived": 4},
        "procedural": {"active": 12,  "archived": 0},
        "identity":   {"active": 2,   "archived": 0},
        "person":     {"active": 7,   "archived": 0}
      },
      "by_state": {"active": 197, "archived": 17},
      "total": 214
    },
    "decay": {
      "at_risk_count": 3,
      "at_risk": [
        {
          "id": "abc123",
          "content_preview": "Meeting notes from Q1 planning...",
          "memory_type": "episodic",
          "retrievability": 0.1124,
          "last_accessed": "2026-02-01T09:00:00+00:00",
          "stability": 2.0,
          "tags": ["meeting", "q1"]
        }
      ],
      "by_type": {
        "working":    {"avg_importance": 0.5500, "avg_stability": 0.0400, "avg_retrievability": 0.2100, "count": 3},
        "episodic":   {"avg_importance": 0.6800, "avg_stability": 3.1200, "avg_retrievability": 0.7800, "count": 45},
        "semantic":   {"avg_importance": 0.7900, "avg_stability": 18.500, "avg_retrievability": 0.9200, "count": 128},
        "procedural": {"avg_importance": 0.8200, "avg_stability": 72.000, "avg_retrievability": 0.9800, "count": 12},
        "identity":   {"avg_importance": 0.9500, "avg_stability": 420.0, "avg_retrievability": 0.9990, "count": 2},
        "person":     {"avg_importance": 0.7100, "avg_stability": 95.000, "avg_retrievability": 0.9600, "count": 7}
      }
    },
    "orphans": {
      "no_tags_count": 5,
      "no_tags": [
        {"id": "def456", "content_preview": "Random thought captured...", "memory_type": "working", "created_at": "2026-01-15T08:00:00+00:00"}
      ],
      "no_relations_count": 22,
      "no_relations": [
        {"id": "ghi789", "content_preview": "Python decorator pattern...", "memory_type": "semantic", "tags": ["python"], "created_at": "2026-03-01T12:00:00+00:00"}
      ]
    },
    "gaps": {
      "empty_types": ["working"],
      "sparse_types": [
        {"type": "procedural", "active_count": 2, "pct_of_active": 1.3}
      ],
      "tag_coverage": {
        "untagged_count": 5,
        "total_unique_tags": 87,
        "top_tags": [
          {"tag": "python", "count": 45},
          {"tag": "ai", "count": 38}
        ]
      }
    },
    "consolidation": {
      "never_run": false,
      "last_run_at": "2026-04-07T14:22:00+00:00",
      "last_run_summary": {
        "promote": 2,
        "archive": 3,
        "merge": 1,
        "flag_contradiction": 0
      }
    }
  },
  "meta": {"elapsed_ms": 412.7}
}
```

---

## 6. Performance Considerations

| Operation | Concern | Mitigation |
|---|---|---|
| Fetch all active memories for decay | O(n) memory at 10k rows, ~1MB without embeddings | SELECT excludes `embedding` column. Acceptable for a diagnostic tool. |
| Union all 8 edge tables for orphan detection | Large edge sets | Single multi-statement query. SurrealDB handles this server-side. |
| Tag frequency computation | Flatten n × avg_tags arrays | `collections.Counter` on flattened list. Sub-millisecond at 10k rows. |
| Retrievability per memory | n float computations | Pure Python arithmetic — ~1ms per 1000 entries. |

Target: full report under 3 seconds at 10,000 active memories. If this becomes a bottleneck, `get_active_memories_for_decay` can be split into two queries: one for decay data (stability, last_accessed), one for content/tags used in the at-risk list. Premature at spec time.

---

## 7. Files Changed

| File | Change |
|------|--------|
| `src/cognitive_memory/engine.py` | Add `get_health() -> dict` method plus three private helpers: `_build_totals`, `_build_decay_report`, `_build_gaps` |
| `src/cognitive_memory/surreal_storage.py` | Add six new SELECT-only methods: `get_counts_by_type_and_state`, `get_active_memories_for_decay`, `get_orphan_untagged`, `get_orphan_unconnected`, `get_tag_frequencies`, `get_health_consolidation_summary` |
| `src/cognitive_memory/server.py` | Add `memory_health()` MCP tool (zero parameters) |
| `tests/test_memory_health.py` | New — unit tests for all three helper functions and MCP tool response shape |

---

## Future Work (Out of Scope)

- **Threshold parameters**: Expose `at_risk_threshold` and `sparse_pct` as optional tool parameters once usage patterns are understood
- **Historical trending**: Compare current health against previous runs (requires storing health snapshots in consolidation_log or a new table)
- **CLI integration**: `cognitive-memory-cli health` command that renders the report in a human-readable format with colour-coded decay tiers
