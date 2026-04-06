# Identity Memory — Requirement

## Overview

Cognitive Memory currently stores four types of memory: working, episodic, semantic, procedural. All are "about the world." None are about the self or the people the agent is connected to.

Humans have distinct cognitive systems for self-knowledge (self-schema, autobiographical self) and social cognition (person memory, mental models of others). These are always accessible, decay extremely slowly, and form the bedrock against which all other memories are interpreted.

This feature adds two new memory types to CM: **identity** (self-knowledge) and **person** (knowledge of others). These replace monolithic file dumps (PERSONA.md, USER.md) with queryable, selectively retrievable memory — enabling an agent to *know* who it is rather than *look up* who it is.

---

## Actors

| Actor | Role |
|-------|------|
| **Agent** | The AI persona using CM (e.g., Velasari). Stores and recalls identity/person memories. |
| **CM Server** | The cognitive memory MCP server. Manages storage, decay, retrieval, consolidation. |
| **Human** | The builder/user (e.g., Kaushik). Configures, observes, may seed initial memories. |

---

## User Stories

### Identity Memory (Self-Knowledge)

**IM-1: Store identity facets**
As an Agent, I want to store discrete facets of my identity (name, origin, values, capabilities, role, personality traits) as individual identity memories, so that my self-knowledge is granular and queryable rather than monolithic.

_Acceptance criteria:_
- Can store a memory with `type: "identity"`
- Each identity memory represents one facet (not a full identity dump)
- Supports tags for categorization (e.g., "origin", "values", "capability", "name")
- Stored in the same DB as all other memories

**IM-2: Recall self-knowledge selectively**
As an Agent, I want to recall specific aspects of my identity by query (e.g., "what is my origin story", "what are my values"), so I load only the relevant facets into context instead of everything.

_Acceptance criteria:_
- `memory_recall` with `type_filter: "identity"` returns only identity memories
- Semantic search works across identity memories (query "my name" finds the naming memory)
- Results are ranked by relevance, not just recency

**IM-3: Identity memories resist decay**
As an Agent, I want my identity memories to have near-zero decay, so core self-knowledge persists indefinitely without manual reinforcement.

_Acceptance criteria:_
- Identity memories have initial stability significantly higher than procedural (e.g., S0 = 365 — ~1 year)
- Consolidation never auto-archives identity memories while they are active
- Manual archive is still possible (for identity evolution — retiring old facets)

**IM-4: Update identity as it evolves**
As an Agent, I want to update identity facets when I evolve (new name, new capability, new understanding), so my self-model stays current without creating duplicates.

_Acceptance criteria:_
- `memory_update` works on identity memories (content, tags)
- Version history is preserved (existing versioning system)
- Old versions are accessible but the current facet is authoritative

### Person Memory (Social Cognition)

**PM-1: Store knowledge about a person**
As an Agent, I want to store knowledge about a specific person (traits, preferences, history, health, relationship dynamics) as person memories tagged to that individual, so I can build a mental model of each person I interact with.

_Acceptance criteria:_
- Can store a memory with `type: "person"`
- Each person memory is associated with a named entity (e.g., tag "person:kaushik", "person:haimanti")
- Supports facets — one memory per fact/trait, not a profile dump
- Stored in the same DB as all other memories

**PM-2: Recall knowledge about a specific person**
As an Agent, I want to recall what I know about a specific person by name and optional query (e.g., "what does Kaushik prefer for code style", "Haimanti's health status"), so I get targeted context without loading everything.

_Acceptance criteria:_
- `memory_recall` with `type_filter: "person"` and `tags: ["person:kaushik"]` returns only memories about Kaushik
- Semantic search narrows within that person's memories
- Can also recall across all persons (e.g., "who has thyroid issues")

**PM-3: Person memories decay very slowly**
As an Agent, I want person memories to have very slow decay (similar to procedural), so relationship knowledge persists across long periods.

_Acceptance criteria:_
- Person memories have high initial stability (e.g., S0 = 90 — ~3 months)
- Important person memories (high importance score) decay even slower due to stability growth
- Consolidation respects person memory persistence

**PM-4: Relate person memories to each other and to identity**
As an Agent, I want to create relationships between person memories (e.g., "Haimanti is Kaushik's wife") and between person and identity memories (e.g., "Kaushik is my builder"), so the social graph is navigable.

_Acceptance criteria:_
- Existing `memory_relate` works with identity and person types
- Graph traversal via `memory_related` crosses type boundaries
- Relationship types include at minimum: `describes`, `relates_to`, `part_of`

### Dedicated Tools

**DT-1: memory_self — query self-knowledge**
As an Agent, I want a dedicated `memory_self` tool that queries only identity memories, so self-knowledge retrieval is a single call with no type filtering boilerplate.

_Acceptance criteria:_
- `memory_self(query)` is equivalent to `memory_recall(query, type_filter="identity")`
- Returns ranked identity memories matching the query
- Supports optional `tags` filter for facet categories
- Lightweight convenience wrapper — no separate retrieval logic

**DT-2: memory_who — query knowledge about a person**
As an Agent, I want a dedicated `memory_who(person, query?)` tool that retrieves what I know about a specific person, so person recall is natural and direct.

_Acceptance criteria:_
- `memory_who(person="kaushik")` returns all active memories about Kaushik
- `memory_who(person="kaushik", query="health")` narrows to health-related memories
- Person matching is case-insensitive and matches against `person:{name}` tags
- Returns ranked results

### Integration

**INT-1: Unified retrieval includes identity/person when relevant**
As an Agent, I want `memory_recall` (with no type filter) to include identity and person memories in results when they are semantically relevant to the query, so the system is unified — not siloed.

_Acceptance criteria:_
- A query like "who built me" surfaces identity memories alongside any semantic/episodic matches
- A query like "thyroid protocol" surfaces person memories about Kaushik's health alongside semantic medical knowledge
- No special handling needed — the existing RRF retrieval pipeline naturally includes all types

**INT-2: Consolidation handles new types**
As an Agent, I want the consolidation pipeline to handle identity and person memories with appropriate rules (no auto-archive for identity, slow promotion thresholds for person), so maintenance doesn't destroy foundational knowledge.

_Acceptance criteria:_
- Consolidation skips identity memories for archive threshold checks
- Person memories have a lower retrievability threshold for archival than episodic/working
- Promotion from episodic/semantic to person or identity is possible (e.g., a fact learned in conversation gets promoted to person memory)

---

## Out of Scope

- **Agent-specific memory isolation** — the ability for different agents (e.g., workers vs. Velasari) to have separate memory namespaces. Future feature; this spec is about memory types, not access control.
- **Migration from PERSONA.md / USER.md** — seeding identity/person memories from existing files is a separate task after the feature ships.
- **UI or dashboard** — no visual interface for browsing identity/person memories.

---

## Dependencies

- Cognitive Memory MCP server (`C:/Projects/cognitive-memory`)
- SurrealDB embedded storage (current backend)
- Existing retrieval pipeline (RRF fusion, embeddings, decay)
