# Design Dry-Run Report #2

**Document**: `.claude/specs/surreal-service/design.md`
**Reviewed**: 2026-03-21
**Context**: Second pass after addressing all 3 critical + 7 warning findings from dryrun #1.

---

## Critical Gaps (must fix before implementation)

_None._

---

## Warnings (should fix, may cause issues)

### [W1] US-4 acceptance criterion contradicts stateless design decision
- **Pass**: 1 (Completeness)
- **What**: US-4 AC says "Session management (connect/disconnect without losing state)". The design explicitly chose `stateless_http=True` (Decision #6), which disables MCP session tracking. The AC wording implies MCP-level session management, but the actual intent is that memory state (in SurrealDB) survives client disconnects — which stateless mode satisfies.
- **Risk**: Implementer reads the requirement literally and switches to stateful mode, adding unnecessary session management complexity.
- **Suggestion**: Update US-4 AC to: "Client connect/disconnect does not affect stored memories (all state lives in SurrealDB, not in MCP sessions)."

### [W2] task.md is stale — doesn't reflect design updates from dryrun #1
- **Pass**: 8 (Task Spec Alignment)
- **What**: Several design changes aren't reflected in task.md:
  1. No task for creating `protocols.py` (StorageProtocol)
  2. Phase 1 dependencies task doesn't include `uvicorn` and `starlette`
  3. Phase 2 embeddings task says "keeps to_bytes(), from_bytes()" — these are dead code in SurrealDB path
  4. Phase 2 config task says "config table" — should say "preference table"
  5. Phase 4 service task doesn't mention eager warmup or SCM failure configuration
  6. Phase 5 migration task doesn't reflect the detailed migration design (batching, verification, idempotency)
- **Risk**: Tasks are implemented to stale spec. Implementer misses new requirements (StorageProtocol, eager warmup, SCM config) or implements dead code (to_bytes/from_bytes).
- **Suggestion**: Update task.md to match the current design.

---

## Observations (worth discussing)

### [O1] FTS score negation logic in retrieval.py not explicitly called out
The old retrieval.py (line 71) negates FTS5's negative rank: `(-rank if rank < 0 else rank)`. SurrealDB's `search::score()` returns positive BM25 scores, so this negation should be removed. The design says "rewrite retrieval.py" which implicitly covers this, but a developer could copy the negation pattern without thinking.

### [O2] Debug mode (non-service) path still uses lazy engine init
The design specifies eager warmup for the service path. The `main()` / debug path still lazy-loads the engine on first request. The `threading.Lock` covers the race condition, but the first debug-mode request will be slow. This is acceptable for development but worth noting.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 0        | 2        | 2            |

**Verdict**: PASS WITH WARNINGS — All 3 critical gaps from dryrun #1 are resolved. The design architecture is sound and complete. Two housekeeping items remain: a requirement AC that contradicts the stateless decision (W1), and task.md drift (W2). Neither blocks implementation understanding, but both should be fixed to prevent misinterpretation.
