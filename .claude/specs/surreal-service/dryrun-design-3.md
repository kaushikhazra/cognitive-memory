# Design Dry-Run Report #3

**Document**: `.claude/specs/surreal-service/design.md`
**Reviewed**: 2026-03-21
**Context**: Third pass after addressing W1 (requirement AC) and W2 (stale task.md) from dryrun #2.

---

## Critical Gaps (must fix before implementation)

_None._

---

## Warnings (should fix, may cause issues)

_None._

---

## Observations (worth discussing)

### [O1] Debug mode has no eager warmup
The service path pre-loads SurrealDB + embedding model before accepting requests. The debug path (`python -m cognitive_memory.server`) still lazy-loads on first request via `_get_engine()`. First debug-mode request takes 30-60s. Acceptable for development — no fix needed.

### [O2] Per-table iteration vs single arrow query for graph traversal
The design shows elegant multi-edge arrow syntax (`<->(causes|...|part_of)<->memory`) in Key SurrealQL Patterns, but the implementation iterates 7 tables individually (14 queries for bidirectional). Works correctly, just less efficient. Future optimization opportunity, not a design gap.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 0        | 0        | 2            |

**Verdict**: PASS — Design is clean. All critical gaps and warnings from dryruns #1 and #2 have been resolved. The three spec documents (requirement.md, design.md, task.md) are consistent with each other. Schema naming matches across design and implementation. Concurrency model is documented. Migration strategy is detailed. Task specs reference the correct tables, fields, and behaviors. Ready for implementation.
