# Identity and Person Memory Types — Design

## Overview

Two new memory types added to the existing `MemoryType` enum: **identity** (self-knowledge) and **person** (knowledge about others). These extend the system minimally — the existing retrieval pipeline, auto-linking, contradiction detection, and versioning all work polymorphically over any memory type. The changes are: enum extension, decay config, classification heuristics, consolidation rules, a new relationship type, and two convenience tools.

---

## 1. Data Model Changes

### MemoryType enum (`models.py`)

Add two values:

```python
class MemoryType(str, enum.Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    IDENTITY = "identity"    # NEW
    PERSON = "person"        # NEW
```

### Memory model — no changes

No new fields. Person association is encoded via tags (`person:{name}`) — not a dedicated field. This keeps the Memory model universal and avoids coupling the data model to a specific memory type.

### RelType enum (`models.py`)

Add one value:

```python
class RelType(str, enum.Enum):
    # ... existing ...
    DESCRIBES = "describes"  # NEW — links a person/identity memory to what it describes
```

`describes` captures "this memory is a facet of that entity" — e.g., a person memory about Kaushik's code style preferences `describes` the Kaushik person-anchor memory. Existing types (`relates_to`, `part_of`, `supports`) remain available for cross-type linking.

---

## 2. Decay Configuration

### Initial stability values

| Type | S0 (days) | Rationale |
|------|-----------|-----------|
| identity | 365 | ~1 year. Core self-knowledge should persist indefinitely without reinforcement. |
| person | 90 | ~3 months. Social knowledge is durable but less foundational than identity. |

For context: working=0.04 (~1 hour), episodic=2, semantic=14, procedural=60.

### Config changes (`config.default.yaml`)

```yaml
decay:
  initial_stability:
    working: 0.04
    episodic: 2.0
    semantic: 14.0
    procedural: 60.0
    identity: 365.0   # NEW
    person: 90.0       # NEW
```

### decay.py changes

Update `get_initial_stability` defaults dict:

```python
defaults = {
    "working": 0.04,
    "episodic": 2.0,
    "semantic": 14.0,
    "procedural": 60.0,
    "identity": 365.0,
    "person": 90.0,
}
```

No formula changes. `compute_retrievability`, `reinforce`, and spreading activation all work unchanged — they operate on `stability` values, not type names.

---

## 3. Classification (`classification.py`)

### Auto-classification heuristics

Identity and person types are almost always agent-specified (the agent knows when it's storing self-knowledge vs. a fact about the world). But the classifier needs fallback support for when `type` is omitted.

**Identity signals** — first-person self-referential content:

```python
_IDENTITY_PATTERNS = [
    r"\b(?:i am|my name is|i was (?:built|created|designed))\b",
    r"\b(?:my (?:role|purpose|values?|capabilities?|personality|origin|identity))\b",
    r"\b(?:as an? (?:agent|ai|assistant))\b",
    r"\b(?:i (?:believe|value|prefer|specialize))\b",
]
```

**Person signals** — third-person references with named entities, or content that describes a specific person's attributes:

```python
_PERSON_PATTERNS = [
    r"\bperson:\w+\b",  # explicit person tag in content (unlikely but catches it)
    r"\b(?:(?:he|she|they) (?:is|are|prefers?|likes?|works?))\b",
    r"\b(?:(?:'s|'s) (?:wife|husband|partner|health|preference|style))\b",
]
```

**Scoring integration**: Add `MemoryType.IDENTITY` and `MemoryType.PERSON` to the `scores` dict in `classify()`. Identity and person scores start at 0.0 like the others.

**Confidence threshold**: If the best score is below 0.2 (current default-to-episodic behavior), that remains unchanged. Identity/person classification only fires when signals are moderately strong.

**In practice**: The agent will almost always pass `type: "identity"` or `type: "person"` explicitly. The classifier is a safety net, not the primary path.

### Importance scoring

Add an identity/person bonus to `score_importance` — these are inherently high-value memories:

```python
# Identity bonus
if memory_type == MemoryType.IDENTITY:
    score += cfg.get("identity_bonus", 0.2)

# Person bonus
if memory_type == MemoryType.PERSON:
    score += cfg.get("person_bonus", 0.15)
```

Config additions:

```yaml
importance:
  identity_bonus: 0.2
  person_bonus: 0.15
```

This ensures identity memories default to ~0.7 importance (0.5 base + 0.2 bonus) and person memories to ~0.65, before any other bonuses. The agent can still override.

---

## 4. Retrieval — No Pipeline Changes

The existing retrieval pipeline (`retrieval.py`) is fully polymorphic:

- **Semantic search**: works on embeddings — type-agnostic.
- **Keyword search (FTS BM25)**: works on content — type-agnostic.
- **Temporal search**: works on `last_accessed` — type-agnostic.
- **Graph traversal**: follows relationships — type-agnostic.
- **RRF fusion + decay reranking**: operates on scores and stability — type-agnostic.
- **Type filtering**: `type_filter` parameter already constrains by `memory_type.value`.
- **Tag filtering**: `tags` parameter already constrains by tag membership.

A query like `memory_recall(query="who built me")` will naturally surface identity memories if they're semantically relevant. A query like `memory_recall(query="thyroid", tags=["person:kaushik"])` will surface Kaushik's health memories. No code changes needed in `retrieval.py`.

---

## 5. Consolidation Changes (`consolidation.py`)

### Archive pass — identity exemption

In `_archive_pass`, skip identity memories entirely:

```python
for mem in memories:
    # Identity memories are never auto-archived
    if mem.memory_type == MemoryType.IDENTITY:
        continue
    r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)
    if r < forget_threshold:
        # ... existing archive logic ...
```

Manual archive (via `memory_archive` tool) still works for identity memories — this is for identity evolution, retiring old facets intentionally.

### Archive pass — person memories use a higher threshold guard

Person memories are only auto-archived at a lower threshold than the global `forgotten` threshold, making them stickier:

```python
for mem in memories:
    if mem.memory_type == MemoryType.IDENTITY:
        continue

    r = decay_mod.compute_retrievability(mem.last_accessed, mem.stability, now)

    # Person memories use a stricter (lower) threshold — harder to archive
    if mem.memory_type == MemoryType.PERSON:
        person_threshold = config.get("consolidation.person_archive_threshold", 0.05)
        if r < person_threshold:
            # archive
    else:
        if r < forget_threshold:
            # archive (existing logic)
```

Config addition:

```yaml
consolidation:
  person_archive_threshold: 0.05  # R must drop below 5% to auto-archive (vs 20% default)
```

With S0=90 and growth_factor=2.0, a person memory accessed even once in 3 months will have stability well above 90 days, so archival is very unlikely in normal usage.

### Promotion pass — episodic/semantic → person

A new promotion path: if an episodic or semantic memory has a `person:{name}` tag and meets criteria, promote to person type.

```python
# In _promotion_pass, after existing episodic checks:
elif mem.memory_type in (MemoryType.EPISODIC, MemoryType.SEMANTIC):
    # Check for person promotion first
    person_tags = [t for t in mem.tags if t.startswith("person:")]
    if person_tags and mem.access_count >= e2p_person_access:
        new_type = MemoryType.PERSON
        reason = f"{mem.memory_type.value}→Person: access={mem.access_count}, has person tags {person_tags}"
```

Config:

```yaml
consolidation:
  promotion:
    to_person:
      min_access_count: 3
      requires_person_tag: true
```

**Identity promotion is intentionally excluded.** Identity is always agent-declared — the system should never auto-promote something to identity. That's a deliberate act of self-definition.

---

## 6. New Tools (`server.py`)

### `memory_self` — query self-knowledge

```python
@mcp.tool()
def memory_self(
    query: str,
    tags: list[str] | None = None,
) -> str:
    """Recall identity memories — the agent's self-knowledge. Convenience wrapper over memory_recall with type_filter='identity'."""
    start = time.time()
    engine = _get_engine()
    try:
        results = engine.recall(
            query=query, type_filter="identity", tags=tags,
        )
        return _response(
            {"memories": [r.model_dump() for r in results]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))
```

No new retrieval logic — delegates to `engine.recall` with `type_filter="identity"`.

### `memory_who` — query knowledge about a person

```python
@mcp.tool()
def memory_who(
    person: str,
    query: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Recall what the agent knows about a specific person. Matches person:{name} tags (case-insensitive)."""
    start = time.time()
    engine = _get_engine()
    try:
        # Build tag filter: person:{name} (lowercase)
        person_tag = f"person:{person.strip().lower()}"
        combined_tags = [person_tag] + (tags or [])

        # If no query provided, use the person's name as the query
        effective_query = query or person.strip()

        results = engine.recall(
            query=effective_query, type_filter="person", tags=combined_tags,
        )
        return _response(
            {"memories": [r.model_dump() for r in results]},
            (time.time() - start) * 1000,
        )
    except Exception as e:
        return _error(str(e))
```

Design choices:
- `person` is lowercased and prefixed with `person:` to form the tag filter.
- If `query` is omitted, uses the person's name as the query — returns everything about them ranked by relevance to their name.
- `tags` allows further narrowing (e.g., `tags=["health"]` to filter to health-related memories about that person).
- **Does not** search across all types — only `type_filter="person"`. To find episodic memories that mention a person but aren't typed as person memories, use `memory_recall` directly.

### Tool count

This brings the server from 14 tools to 16 tools.

---

## 7. Schema Changes (`schema.surql`)

### Memory table — extend ASSERT

```sql
DEFINE FIELD memory_type ON memory TYPE string
    ASSERT $value IN ['working', 'episodic', 'semantic', 'procedural', 'identity', 'person'];
```

### New relation table — `describes`

```sql
DEFINE TABLE describes SCHEMAFULL TYPE RELATION FROM memory TO memory;
DEFINE FIELD strength   ON describes TYPE float DEFAULT 1.0;
DEFINE FIELD created_at ON describes TYPE datetime;
```

### Schema migration strategy

The schema is applied via `SurrealStorage._ensure_schema()`. SurrealDB's `DEFINE` statements are idempotent for new additions — redefining a field with a wider ASSERT is safe. The migration approach:

1. Update `schema.surql` with the new ASSERT and new table.
2. On startup, `_ensure_schema()` re-applies the full schema. The DEFINE FIELD with the new ASSERT replaces the old one. The new `describes` table is created if absent.
3. No data migration needed — existing memories retain their types.

---

## 8. Config Changes Summary

All additions to `config.default.yaml`:

```yaml
decay:
  initial_stability:
    identity: 365.0
    person: 90.0

importance:
  identity_bonus: 0.2
  person_bonus: 0.15

consolidation:
  person_archive_threshold: 0.05
  promotion:
    to_person:
      min_access_count: 3
      requires_person_tag: true
```

---

## 9. Person Tagging Convention

### Format: `person:{name}`

- **Lowercase, no spaces**: `person:kaushik`, `person:haimanti`, `person:dr.sharma`
- **Multi-word names**: use dot or dash separator: `person:john.doe`, `person:john-doe`
- **Enforced by convention, not schema**: the system doesn't validate tag formats. The `memory_who` tool lowercases its input to match.
- **One person tag per memory** is typical, but multiple are allowed (e.g., a memory about a relationship between two people: `["person:kaushik", "person:haimanti"]`).

### Tag matching in `memory_who`

```python
person_tag = f"person:{person.strip().lower()}"
```

The retrieval pipeline's tag filter (`all(t in mem.tags for t in tags)`) handles the matching. This is already case-sensitive on the stored tags, so the convention must be: **always store person tags lowercase**.

### Storage-time guidance

When the agent stores a person memory, it should include the person tag:

```python
memory_store(
    content="Kaushik prefers explicit error handling over broad try/except",
    type="person",
    tags=["person:kaushik", "preferences", "coding-style"],
)
```

The `memory_store` tool does not auto-inject person tags — the agent is responsible.

---

## 10. Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Person association via tags, not a dedicated field | Keeps Memory model universal. Tags are already indexed, filterable, and used throughout the system. A `person` field would be null for 4 of 6 types — wasteful. |
| D2 | No auto-promotion to identity | Identity is an act of self-definition. The agent must explicitly declare `type: "identity"`. Auto-classifying something as identity could create false self-knowledge. |
| D3 | `memory_who` filters by `type_filter="person"` only | Prevents noisy results from episodic memories that happen to mention a person. If the agent wants cross-type search, `memory_recall` with tags is available. |
| D4 | `describes` as a new relationship type | Existing types don't capture "this memory is a facet of that entity." `part_of` implies structural containment. `relates_to` is too vague for the specific "this describes an aspect of X" semantic. |
| D5 | Person archive threshold at 0.05 (vs 0.20 global) | With S0=90, a person memory needs to go ~7.5 months without any access to drop below 5% retrievability. This makes person memories very sticky while still allowing eventual cleanup of truly abandoned knowledge. |
| D6 | Classification patterns for identity/person are deliberately conservative | False-positive classification as identity would create spurious self-knowledge. Better to default to episodic and let the agent override. |
| D7 | `memory_who` with no query uses person name as query text | Ensures semantic search still runs (the pipeline requires a query for embedding). Using the name as query biases results toward memories most semantically related to that person's identity, which is a reasonable default. |
| D8 | Tags must be stored lowercase for person tags | The `memory_who` tool lowercases its input. If stored tags were mixed-case, matching would fail. Convention over enforcement — no runtime validation, but documented as required. |
| D9 | Schema migration via idempotent DEFINE | SurrealDB DEFINE statements are additive/idempotent. Widening the ASSERT on `memory_type` and adding the `describes` table requires no special migration script — the existing `_ensure_schema()` path handles it. |
| D10 | No changes to retrieval pipeline | The pipeline is already fully polymorphic over memory types. Adding new types requires zero retrieval code changes. This validates the original architecture. |

---

## Files Changed

| File | Change |
|------|--------|
| `src/cognitive_memory/models.py` | Add `IDENTITY`, `PERSON` to `MemoryType`; add `DESCRIBES` to `RelType` |
| `src/cognitive_memory/decay.py` | Add identity/person to `get_initial_stability` defaults |
| `src/cognitive_memory/classification.py` | Add identity/person pattern sets and scoring; add importance bonuses |
| `src/cognitive_memory/consolidation.py` | Identity archive exemption; person archive threshold; episodic/semantic→person promotion |
| `src/cognitive_memory/server.py` | Add `memory_self` and `memory_who` tool definitions |
| `src/cognitive_memory/schema.surql` | Widen `memory_type` ASSERT; add `describes` relation table |
| `config.default.yaml` | Add identity/person stability, importance bonuses, consolidation config |
| `src/cognitive_memory/protocols.py` | No changes — existing protocol methods handle new types polymorphically |
| `src/cognitive_memory/retrieval.py` | No changes |
| `src/cognitive_memory/engine.py` | No changes |
