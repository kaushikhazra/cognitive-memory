# Requirement: Memory Health Report

A new MCP tool `memory_health` that returns a structured diagnostic snapshot of the memory store — decay status, orphan detection, storage gaps, and consolidation history. Pure read-only. No side effects.

---

## Connection Model

`memory_health` follows the same server-side pattern as all existing MCP tools: registered in `server.py`, delegated to `engine.get_health()`, which calls targeted query methods on `SurrealStorage`. No writes, no reinforcement, no spreading activation. The tool is a passive observer.

---

## Theme 1: Totals and State Overview

### US-1.1: Counts by type and state

As a **user**, I want to see total memory counts broken down by type and state so that I can understand the overall composition of the memory store.

**Acceptance criteria:**
- [ ] Response includes `totals.by_type` — a dict mapping each memory type (`working`, `episodic`, `semantic`, `procedural`, `identity`, `person`) to `{active: N, archived: N}`
- [ ] Response includes `totals.by_state` — `{active: N, archived: N}` across all types
- [ ] Response includes `totals.total` — grand total across all types and states
- [ ] Types with zero memories appear in the response with `{active: 0, archived: 0}`, not omitted
- [ ] All counts are exact (not estimated)

---

## Theme 2: Decay Health

### US-2.1: At-risk memories

As a **user**, I want to know which active memories are at risk of being forgotten so that I can decide whether to consolidate or manually reinforce them.

**Acceptance criteria:**
- [ ] Response includes `decay.at_risk` — list of active memories whose freshly computed retrievability is below the at-risk threshold (0.3)
- [ ] Each at-risk entry includes: `id`, `content_preview` (first 120 chars), `memory_type`, `retrievability` (computed fresh, 4 decimal places), `last_accessed`, `stability`, `tags`
- [ ] List is ordered by retrievability ascending (most at-risk first)
- [ ] List is capped at 50 entries; `decay.at_risk_count` reflects the true total regardless of cap
- [ ] Identity-type memories are excluded from at-risk (they have near-infinite stability by design)
- [ ] Archived memories are excluded from at-risk (already handled by lifecycle)

### US-2.2: Decay metrics per type

As a **user**, I want to see average importance, stability, and retrievability per memory type so that I can spot which type categories are degrading.

**Acceptance criteria:**
- [ ] Response includes `decay.by_type` — a dict mapping each type to `{avg_importance, avg_stability, avg_retrievability, count}` computed over active memories
- [ ] Retrievability is computed fresh for every active memory in the aggregation (not read from the stale stored field)
- [ ] Types with no active memories appear with null averages, not omitted
- [ ] All averages rounded to 4 decimal places

---

## Theme 3: Orphan Detection

### US-3.1: Untagged memories

As a **user**, I want to see which active memories have no tags so that I can identify knowledge that is hard to retrieve by tag-based filtering.

**Acceptance criteria:**
- [ ] Response includes `orphans.no_tags` — list of active memories where `tags` is empty or null
- [ ] Each entry includes: `id`, `content_preview` (first 120 chars), `memory_type`, `created_at`
- [ ] `orphans.no_tags_count` reflects the true total; list is capped at 50
- [ ] Ordered by `created_at` ascending (oldest untagged first)

### US-3.2: Unconnected memories

As a **user**, I want to see which active memories have no relationships to other memories so that I can identify isolated knowledge nodes that benefit from linking.

**Acceptance criteria:**
- [ ] Response includes `orphans.no_relations` — list of active memories that appear in none of the edge tables (`causes`, `follows`, `contradicts`, `supports`, `relates_to`, `supersedes`, `part_of`, `describes`) as either source or target
- [ ] Each entry includes: `id`, `content_preview` (first 120 chars), `memory_type`, `tags`, `created_at`
- [ ] `orphans.no_relations_count` reflects the true total; list is capped at 50
- [ ] Ordered by `created_at` ascending (oldest isolated first)

---

## Theme 4: Storage Gap Analysis

### US-4.1: Empty and sparse types

As a **user**, I want to know which memory types are empty or underrepresented so that I can identify gaps in my knowledge structure.

**Acceptance criteria:**
- [ ] Response includes `gaps.empty_types` — list of type names with zero active memories
- [ ] Response includes `gaps.sparse_types` — list of `{type, active_count, pct_of_active}` for types whose active count is non-zero but below 5% of total active memories
- [ ] Percentage is rounded to 1 decimal place (e.g., `2.3`)
- [ ] `identity` type is excluded from sparse detection (expected to have very few entries)
- [ ] If all types are adequately populated, `gaps.sparse_types` is an empty list

### US-4.2: Tag coverage

As a **user**, I want to see tag distribution across active memories so that I can understand which topics are well-covered and spot coverage blind spots.

**Acceptance criteria:**
- [ ] Response includes `gaps.tag_coverage.untagged_count` — count of active memories with no tags (matches `orphans.no_tags_count`)
- [ ] Response includes `gaps.tag_coverage.top_tags` — list of `{tag, count}` for the 20 most-used tags across active memories, ordered by count descending
- [ ] Response includes `gaps.tag_coverage.total_unique_tags` — total count of distinct tags across all active memories

---

## Theme 5: Consolidation Status

### US-5.1: Last consolidation run

As a **user**, I want to know when consolidation last ran and what it did so that I can assess whether the memory store needs maintenance.

**Acceptance criteria:**
- [ ] Response includes `consolidation.last_run_at` — ISO 8601 timestamp of the most recent consolidation run, or `null` if never run
- [ ] Response includes `consolidation.never_run` — boolean `true` if no consolidation has ever been executed
- [ ] Response includes `consolidation.last_run_summary` — action counts from the most recent run: `{promote, archive, merge, flag_contradiction}` as integers, or `null` if never run
- [ ] Summary counts reflect the most recent single run, not a cumulative total

---

## Theme 6: Report Metadata

### US-6.1: Report envelope

As a **user**, I want the health report to include when it was generated so that I can assess its freshness.

**Acceptance criteria:**
- [ ] Response includes `generated_at` — ISO 8601 UTC timestamp of when the health query ran
- [ ] Response follows the standard `{"success": true, "data": {...}, "meta": {"elapsed_ms": N}}` envelope
- [ ] `meta.elapsed_ms` accurately reflects end-to-end query time for the full report

---

## Non-Functional Requirements

- **Read-only**: No writes, no reinforcement, no stability updates, no state changes of any kind
- **Performance**: Full health report completes in under 3 seconds on a store of 10,000 active memories
- **No new dependencies**: Implemented using existing SurrealDB query capabilities and Python stdlib
- **Tool signature**: `memory_health()` — no parameters required; all thresholds are fixed constants defined in the implementation
- **Retrievability**: Always computed fresh using `decay.compute_retrievability(last_accessed, stability, now)`, never read from the stale stored field
