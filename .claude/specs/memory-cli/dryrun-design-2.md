# Design Dry-Run Report #2

**Document**: `.claude/specs/memory-cli/design.md`
**Reviewed**: 2026-03-21

---

## Critical Gaps (must fix before implementation)

### [C1] `build_time_range` allows partial ranges that crash the server
- **Pass**: Pass 2 (Data Flow Trace)
- **What**: The `build_time_range` helper returns `{"start": "2026-01-01", "end": None}` if only `--time-start` is provided. The server code does `datetime.fromisoformat(time_range["end"])` — calling `fromisoformat(None)` raises `TypeError`. The server catches this as a generic `Exception` and returns `success: false`, but the user gets a cryptic error like `"TypeError: fromisoformat: argument must be str"` instead of a useful message.
- **Risk**: Users will get confusing server-side errors when using partial time ranges. The CLI should either require both or handle the partial case.
- **Fix**: Either (a) require both `--time-start` and `--time-end` in click (both or neither), or (b) fill in sensible defaults: `--time-start` without `--time-end` uses "now", `--time-end` without `--time-start` uses epoch. Option (a) is simpler and more predictable.

### [C2] No connection timeout — CLI can hang indefinitely
- **Pass**: Pass 5 (Failure Path Analysis)
- **What**: The design's `call_tool` catches `ConnectionRefusedError` and `OSError`, but does not set a timeout on `streamablehttp_client`. If the server accepts the TCP connection but hangs (e.g., engine warmup taking 60+ seconds for model loading), the CLI blocks indefinitely with no feedback.
- **Risk**: User types a command, nothing happens, they wait forever. US-5.1 requires "Connection timeout is reasonable (5 seconds)."
- **Fix**: Pass a timeout to the HTTP client or wrap `asyncio.run()` with `asyncio.wait_for(call_tool(...), timeout=5.0)`. Catch `asyncio.TimeoutError` and print `"Server at <url> did not respond within 5 seconds."` with exit code 2.

---

## Warnings (should fix, may cause issues)

### [W1] No output format designed for mutating commands
- **Pass**: Pass 1 (Completeness Check)
- **What**: Section 4 (Output Formatting) covers `list`, `recall`, `get`, `stats`, `related`, and `config`. But 7 mutating commands have no human-output format specified: `store`, `update`, `delete`, `archive`, `restore`, `relate`, `unrelate`, `consolidate`. The requirement specifies what each should display on success (e.g., US-3.1: "displays the created memory's ID, type, and importance"; US-3.3: "displays 'Memory <id> deleted'").
- **Risk**: Implementer has no guidance for human output of mutating commands. May output raw JSON or nothing.
- **Suggestion**: Add a "Mutating Command Output" subsection to Section 4 showing the format for each. E.g.: `store` → `Stored memory e756ad4b (semantic, importance: 0.80)`, `delete` → `Deleted 1 memory`, `archive` → `Archived 3 memories`, `consolidate` → `Consolidation: 2 promotions, 1 archival, 0 merges`.

### [W2] `conversation_id` missing from Get Detail output
- **Pass**: Pass 1 (Completeness Check)
- **What**: US-1.2 acceptance criteria lists `conversation_id` as a required field in output. The design's Get Detail example (Section 4) shows Source but not Conversation ID.
- **Risk**: Missing requirement field in implementation.
- **Suggestion**: Add `Conversation: <id or "—">` line to the Get Detail format after Source.

### [W3] Default limits not specified in design
- **Pass**: Pass 1 (Completeness Check)
- **What**: US-1.1 says "default limit 20" for list, US-2.1 says "default limit 10" for recall. The design's mapping table says `--limit`→`limit` but doesn't specify the CLI-side defaults. The MCP `memory_list` tool defaults to 50 and `memory_recall` has no server-side default.
- **Risk**: Without explicit defaults, implementation will either omit limit (getting server default 50 for list, unlimited for recall) or guess wrong.
- **Suggestion**: Add default values to the mapping table: `--limit`→`limit` (default: 20) for list, `--limit`→`limit` (default: 10) for recall.

### [W4] `archive` with `--below-retrievability` and no IDs — routing ambiguity
- **Pass**: Pass 7 (Edge Cases & Boundaries)
- **What**: The `archive` command takes `<ids...>` as variable positional args and `--below-retrievability` as a flag. If the user runs `archive --below-retrievability 0.3` with no IDs, `ids` is an empty tuple. `route_ids(())` would produce `{"ids": []}` (since `len == 0` falls to the else branch). The MCP tool receives both `ids=[]` and `below_retrievability=0.3`. Fortunately `if ids:` is falsy for `[]`, so the server falls through to the `below_retrievability` branch. But this relies on Python falsy behavior for empty lists.
- **Risk**: Fragile — works by accident, not by design. If someone adds `ids is not None` check server-side, it breaks.
- **Suggestion**: Don't call `route_ids` when `ids` tuple is empty. Branch explicitly: if IDs provided, use `route_ids`; if `--below-retrievability` provided, send only that param; if both, error.

### [W5] Empty results messages not designed
- **Pass**: Pass 1 (Completeness Check)
- **What**: US-1.1 says "Empty results show a friendly 'No memories found' message." US-2.1 says "Empty results show a friendly message." The design doesn't specify how commands handle empty results — the table headers would print but no rows.
- **Risk**: Users see an empty table with just headers, which looks broken.
- **Suggestion**: Add to Section 4: when `data.memories` is empty, print `"No memories found."` instead of the table. When recall returns empty, print `"No memories match your query."`.

### [W6] No testing strategy in design
- **Pass**: Pass 1 (Completeness Check)
- **What**: The requirement's NFR section says "CLI should be testable by mocking the MCP client session. Integration tests can use the same server-spawn pattern as test_mcp_client.py." The design has no testing section.
- **Risk**: Implementer may skip tests or build a non-testable structure (e.g., `asyncio.run` deep inside command handlers, making them hard to mock).
- **Suggestion**: Add a brief testing section: (a) unit tests mock `call_tool` at the sync bridge level, (b) integration tests spawn the server like `test_mcp_client.py`, (c) `run_tool` is the seam — mock it to test command logic independently of the network.

### [W7] `config` command with three modes — click handling not shown
- **Pass**: Pass 3 (Interface Contract Validation)
- **What**: `config` has three modes: no args (show all), one arg (read key), two args (set key=value). Click's positional args are either required or optional with defaults. The design says "key (optional positional), value (optional positional)" but doesn't show how click handles `config decay.growth_factor 3.0` vs `config decay.growth_factor` vs `config`.
- **Risk**: Click doesn't naturally support "0, 1, or 2 positional args" without explicit handling. The implementer may get the argument parsing wrong.
- **Suggestion**: Show the click signature: `@click.argument("key", required=False, default=None)` and `@click.argument("value", required=False, default=None)`. Or use `@click.argument("args", nargs=-1)` and parse manually.

---

## Observations (worth discussing)

### [O1] Previous dry-run warnings addressed
The design resolves several items from dryrun-design-1: C2 (ID column placement) → fixed, W4 (config format) → flat dot-notation designed, W5 (parameter mapping) → mapping table in Section 3, W6 (ID routing) → `route_ids` helper, O5 (click decision) → D1. Good follow-through.

### [O2] Previous dry-run warnings still open
W1 (default limit mismatch), W2 (time_range on list), W3 (version overflow), W7 (no --sort) from dryrun-design-1 are not addressed in the design. W1 and W3 reappear as warnings in this report. W2 and W7 were deferred to Future Work, which is acceptable.

### [O3] `call_tool` error handling could catch `json.JSONDecodeError`
If the MCP server returns a non-JSON response (unlikely but possible during server errors), `json.loads(result.content[0].text)` would raise `JSONDecodeError`. Adding this to the except clause in `call_tool` would make the CLI more robust.

### [O4] `run_tool` returns full response but most commands only need `data`
Every command calls `run_tool()` which returns the full `{"success": true, "data": ..., "meta": ...}` dict, then indexes into `response["data"]`. A convenience wrapper like `run_tool_data()` that returns just `data` would reduce repetition in 14 command handlers. Minor ergonomic improvement.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 2        | 7        | 4            |

**Verdict**: PASS WITH WARNINGS — The design is solid and well-structured. The two critical gaps (partial time ranges crashing the server, and missing connection timeout) are straightforward fixes. The warnings are mostly about completeness — filling in output formats for mutating commands, specifying defaults, and handling edge cases. None require architectural changes.
