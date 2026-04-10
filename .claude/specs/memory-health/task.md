# Memory Health Report — Task Checklist

## Phase 1: Storage queries (`surreal_storage.py`)

- [x] **Velasari** adds `get_counts_by_type_and_state() -> dict` to `SurrealStorage` — executes `SELECT memory_type, state, count() AS cnt FROM memory GROUP BY memory_type, state` and returns a raw dict keyed by `(type, state)` tuples for the engine to reshape — _US-1.1_
- [x] **Velasari** adds `get_active_memories_for_decay() -> list[dict]` to `SurrealStorage` — executes `SELECT id, content, memory_type, importance, stability, last_accessed, tags FROM memory WHERE state = 'active'` (no `embedding` column) and returns a list of plain dicts — _US-2.1, US-2.2_
- [x] **Velasari** adds `get_orphan_untagged() -> tuple[list[dict], int]` to `SurrealStorage` — queries active memories where `tags IS NONE OR array::len(tags) = 0`, orders by `created_at ASC`, fetches 51 rows to detect truncation, runs a separate count query, returns `(capped_list[:50], true_count)` — _US-3.1_
- [x] **Velasari** adds `get_orphan_unconnected() -> tuple[list[dict], int]` to `SurrealStorage` — executes the two-step LET + NOT IN query that unions all `in`/`out` values across all 8 edge tables, then filters active memories not in that set; returns `(capped_list[:50], true_count)` — _US-3.2_
- [x] **Velasari** adds `get_tag_frequencies() -> list[list[str]]` to `SurrealStorage` — queries `SELECT tags FROM memory WHERE state = 'active'`, returns raw nested lists to caller (flattening and counting done in engine layer) — _US-4.2_
- [x] **Velasari** adds `get_health_consolidation_summary() -> dict | None` to `SurrealStorage` — queries `SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT 500`, groups rows by UTC date (same date = same run; `run_id` does not exist in schema), extracts most-recent date group's timestamp and action counts; returns `None` if table is empty — _US-5.1_

## Phase 2: Engine orchestration (`engine.py`)

- [x] **Velasari** adds module-level private helper `_build_totals(counts_raw: dict) -> dict` in `engine.py` — reshapes the `(type, state)` dict from storage into `{by_type: {type: {active, archived}}, by_state: {active, archived}, total}` with all 6 types always present — _US-1.1_
- [x] **Velasari** adds module-level private helper `_build_decay_report(active_memories: list[dict], now: datetime) -> dict` in `engine.py` — iterates active memories, calls `decay.compute_retrievability()` fresh for each, collects at-risk list (threshold 0.3, identity excluded), computes per-type averages, returns the `decay` section of the health report — _US-2.1, US-2.2_
- [x] **Velasari** adds module-level private helper `_build_gaps(totals: dict, tag_rows: list[list[str]], untagged_count: int) -> dict` in `engine.py` — identifies empty types, sparse types (< 5% of active, identity excluded), flattens tag arrays with `collections.Counter`, returns top-20 tags and unique tag count — _US-4.1, US-4.2_
- [x] **Velasari** adds `get_health() -> dict` method to `MemoryEngine` in `engine.py` — calls the six storage methods in sequence, passes results to the three helpers, assembles and returns the full health report dict with `generated_at` timestamp; wraps `None` from `get_health_consolidation_summary()` into `{never_run: True, last_run_at: None, last_run_summary: None}` — _US-1.1, US-2.1, US-2.2, US-3.1, US-3.2, US-4.1, US-4.2, US-5.1_

## Phase 3: MCP tool (`server.py`)

- [x] **Velasari** adds `memory_health()` tool to `server.py` — decorated with `@mcp.tool()`, zero parameters, calls `engine.get_health()`, wraps result in `_response(report, elapsed_ms)`, catches all exceptions with `_error(str(e))` — _US-6.1, NFR: read-only_

## Phase 4: Tests (`tests/test_memory_health.py`)

- [x] **Velasari** writes unit tests for `_build_totals` in `tests/test_memory_health.py` — covers: all types present when some are missing from input, correct active/archived split, correct grand total — _US-1.1_
- [x] **Velasari** writes unit tests for `_build_decay_report` in `tests/test_memory_health.py` — covers: at-risk filtering (threshold boundary), identity exclusion, list capping at 50, ascending sort by retrievability, per-type averages correct, types with no active members return null averages — _US-2.1, US-2.2_
- [x] **Velasari** writes unit tests for `_build_gaps` in `tests/test_memory_health.py` — covers: empty_types detection, sparse threshold (boundary cases at exactly 5%), identity excluded from sparse, top_tags capped at 20, total_unique_tags count — _US-4.1, US-4.2_
- [x] **Velasari** writes integration test in `tests/test_memory_health.py` using `SurrealStorage("mem://")` (in-memory SurrealDB, no external process) — stores a small set of memories including one with no tags, one with no relations, and one with very low retrievability, calls `engine.get_health()` directly, asserts each section of the response matches expected values — _all US_

_requirement.md refs: US-1.1, US-2.1, US-2.2, US-3.1, US-3.2, US-4.1, US-4.2, US-5.1, US-6.1_
