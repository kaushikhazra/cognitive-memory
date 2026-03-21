# Design Dry-Run Report #1

**Document**: `.claude/specs/memory-cli/requirement.md`
**Reviewed**: 2026-03-21

---

## Critical Gaps (must fix before implementation)

### [C1] UUID ergonomics — IDs are painful to type on CLI
- **Pass**: Pass 7 (Edge Cases & Boundaries)
- **What**: Memory IDs are UUIDs (36 characters, e.g., `e756ad4b-1b45-4a44-837a-118cfb2d5d79`). Every `get`, `update`, `delete`, `archive`, `restore`, `relate`, `unrelate`, and `related` command requires typing one or more IDs. No short-ID support is specified.
- **Risk**: The CLI will be unusable in practice. Nobody will type or copy-paste 36-character UUIDs repeatedly. This is a terminal-first tool — ergonomics are critical.
- **Fix**: Support short ID matching (like git's short SHA). Accept ID prefixes (e.g., `e756ad4b`) and resolve to the full UUID. Error if ambiguous (multiple matches). Document minimum prefix length (8 chars recommended). This requires either a client-side prefix search (call `memory_list` and filter) or a server-side enhancement. Recommend server-side — add prefix matching to `memory_get` or a new lightweight lookup tool.

### [C2] `list` output doesn't show IDs prominently enough for copy-paste workflow
- **Pass**: Pass 2 (Data Flow Trace)
- **What**: US-1.1 says output includes "truncated content (first 80 chars), type, importance, tags, age, and ID" — but doesn't specify ID placement. In a typical CLI workflow: `list` → find interesting memory → `get <id>`. The ID needs to be the first column (or easily selectable) for this to work.
- **Risk**: If ID is buried after content/type/tags columns, the copy-paste workflow breaks.
- **Fix**: Specify that ID (or short ID prefix) is always the first column in table output. Consider showing 8-char short IDs in list view with a note that they can be used in subsequent commands.

---

## Warnings (should fix, may cause issues)

### [W1] `list` default limit mismatch with MCP tool
- **Pass**: Pass 3 (Interface Contract Validation)
- **What**: US-1.1 specifies default limit of 20 results. The MCP `memory_list` tool defaults to 50. The CLI would override the server default by always passing `limit=20`.
- **Risk**: Inconsistency between the CLI and MCP client behavior. Not a functional issue — the CLI explicitly passes its own default — but users who switch between MCP and CLI may expect consistent defaults.
- **Suggestion**: Either align the CLI default with the MCP default (50), or document the difference. 20 is arguably better for terminal readability.

### [W2] `time_range` missing from `list` command
- **Pass**: Pass 1 (Completeness Check)
- **What**: The MCP `memory_list` tool accepts a `time_range` parameter (dict with `start`/`end`). The requirement exposes `--time-start`/`--time-end` on `recall` (US-2.1) but not on `list` (US-1.1).
- **Risk**: Users can't filter the list view by date range, even though the underlying MCP tool supports it.
- **Suggestion**: Add `--time-start` and `--time-end` flags to the `list` command for consistency with `recall`.

### [W3] Version history display could be overwhelming
- **Pass**: Pass 7 (Edge Cases & Boundaries)
- **What**: US-1.2 says `get` displays "Version history...with timestamps and previous content." A heavily-updated memory could have many versions, each with full content.
- **Risk**: Terminal output becomes unreadable for memories with many versions.
- **Suggestion**: Show version count and latest N versions (e.g., 5) by default. Add `--versions-all` or `--versions <N>` flag to control. Or show versions as summary (timestamp + diff size) with `--verbose` for full content.

### [W4] Nested config display format unspecified
- **Pass**: Pass 7 (Edge Cases & Boundaries)
- **What**: US-4.1 says `cognitive-memory-cli config` displays "all configuration." The configuration is hierarchical with dot-notation keys (e.g., `decay.growth_factor`, `retrieval.weights.semantic`). The requirement doesn't specify how nested structures are rendered.
- **Risk**: Dumping raw nested dicts is hard to read. Flat key-value listing may lose structure.
- **Suggestion**: Specify flat dot-notation display for human output (one key=value per line, sorted). JSON output already handles nesting via `--json`.

### [W5] `recall` parameter name mismatch needs mapping
- **Pass**: Pass 3 (Interface Contract Validation)
- **What**: The CLI's `--type` flag on `recall` maps to the MCP tool's `type_filter` parameter (not `type`). Similarly, the MCP tool's `time_range` expects `{"start": "...", "end": "..."}` while the CLI uses `--time-start`/`--time-end`.
- **Risk**: Not a functional gap — the CLI handles mapping — but the design must explicitly document these translations to avoid implementation shortcuts that pass wrong parameter names.
- **Suggestion**: Document the CLI-flag → MCP-parameter mapping table in the design document.

### [W6] `archive`/`restore` bulk ID routing
- **Pass**: Pass 3 (Interface Contract Validation)
- **What**: The MCP `memory_archive` tool has separate parameters: `id` (single) and `ids` (list). The CLI command `archive <id1> <id2>...` accepts variable args. The CLI must detect single vs. multiple and route to the correct parameter.
- **Risk**: Subtle bug if the CLI always sends a single-element list via `ids` instead of using `id` — depends on server-side handling.
- **Suggestion**: Document this routing logic explicitly in the design: 1 arg → use `id`, 2+ args → use `ids`.

### [W7] No `--sort` on `list`
- **Pass**: Pass 1 (Completeness Check)
- **What**: The `list` command has filters (type, tags, state, importance range) but no sorting options. Users may want to sort by importance, age, access count, or retrievability.
- **Risk**: Users can only see memories in the server's default order.
- **Suggestion**: Consider adding `--sort` flag (e.g., `--sort importance`, `--sort age`, `--sort accessed`) if the MCP tool or a future version supports it. If not server-supported, could be done client-side on the returned results.

---

## Observations (worth discussing)

### [O1] No export/import capability
The requirement has no bulk export (dump all memories to a JSON file) or import (load from JSON file). This is a natural CLI expectation for data management tools (cf. `pg_dump`/`pg_restore`). Not in scope now, but worth considering for a future iteration. Could be built as `cognitive-memory-cli export > backup.json` using `--json` on `list` with a high limit.

### [O2] No shell completion
`click` supports shell completion out of the box (bash, zsh, fish). The requirement doesn't mention it, but enabling it would significantly improve the CLI UX — especially for long command names like `cognitive-memory-cli consolidate --dry-run`. Worth enabling in the design if using `click`.

### [O3] `--json` flag is well-designed for scripting
The consistent `--json` flag on every command, combined with the server's standard `{"success": bool, "data": ..., "meta": {...}}` response format, makes this CLI fully scriptable. This is a good design choice that enables `jq` pipelines and automation.

### [O4] Connection model is clean
The strict "CLI → MCP server → DB" architecture with no direct DB access is the right call. It means the CLI can work against a remote server too (not just localhost), which opens up future multi-machine scenarios.

### [O5] `click` vs `argparse` should be decided in design
The requirement says "prefer `click`" which adds a dependency. `argparse` is stdlib and sufficient for this scope (14 subcommands, simple flags). The design should make a definitive choice and justify the trade-off.

---

## Summary

| Critical | Warnings | Observations |
|----------|----------|--------------|
| 2        | 7        | 5            |

**Verdict**: PASS WITH WARNINGS — The requirement is solid and covers all 14 MCP tools with a clean connection model. The two critical gaps (UUID ergonomics and ID visibility in list output) must be addressed before design — they're usability-breaking for a CLI tool. The warnings are design-level concerns that can be resolved during the design phase.
