# Code Dry-Run Report #1

**Scope**: `src/cognitive_memory/cli.py`
**Design**: `.claude/specs/memory-cli/design.md`
**Reviewed**: 2026-03-22

---

## Bugs (will cause incorrect behavior)

### [B1] Unicode arrows crash on Windows cp1252 subprocess encoding
- **File**: `src/cognitive_memory/cli.py`:296, 300, 379, 614, 635
- **Pass**: Pass 8 (Code Quality)
- **What**: The `get` (relationships), `related`, `relate`, and `unrelate` commands use Unicode arrows `\u2192` (→) and `\u2190` (←) in output. These characters are NOT in the cp1252 codepage used by Windows subprocess consoles. This is the same class of bug that was already fixed for `\u2500` (─) table separators.
- **Impact**: `UnicodeEncodeError: 'charmap' codec can't encode character` when running these commands via subprocess on Windows (e.g., from the integration tests, scripts, or Task Scheduler).
- **Fix**: Replace `\u2192` with `->` and `\u2190` with `<-`. The `\u2014` (em dash) at line 310 is safe — cp1252 includes it at 0x97. The `\u2026` (ellipsis) in `truncate()` is also safe — cp1252 includes it at 0x85.

---

## Gaps (missing implementation)

_None found. All 14 commands, output formats, error handling, and parameter mappings match the design._

---

## Warnings (potential issues)

### [W1] Broad `except Exception` in `call_tool` could mask programming errors
- **File**: `src/cognitive_memory/cli.py`:67-75
- **Pass**: Pass 3 (Error Path Trace)
- **What**: The `except Exception` handler checks if `str(e).lower()` contains "connect", "refused", or "failed". A `KeyError("connection_failed")` or `AttributeError` whose message happens to contain these words would be caught and reported as a connection error instead of surfacing the actual bug.
- **Risk**: Rare in practice — most programming errors won't contain these words. But if one does, it becomes invisible.

### [W2] `result.content[0]` has no bounds check
- **File**: `src/cognitive_memory/cli.py`:40
- **Pass**: Pass 7 (Contract Violations)
- **What**: If the MCP server returns a tool result with empty `content`, `result.content[0]` raises `IndexError`. This would be caught by the broad `except Exception` handler (W1) and the string "list index out of range" doesn't contain "connect"/"failed", so it would re-raise as an unhandled exception — producing a stack trace instead of a friendly error.
- **Risk**: Only happens if the MCP server has a bug. Defensive fix: check `if not result.content:` before indexing.

---

## Style (code quality, conventions)

### [S1] Inconsistent exit pattern in `update` command
- **File**: `src/cognitive_memory/cli.py`:501
- **What**: `update` uses `ctx.exit(2)` + `return` for the no-flags error, while all other commands use `sys.exit(2)` or `sys.exit(1)`. Both work (click's `ctx.exit()` raises `SystemExit`) but the inconsistency could confuse a reader. Minor — functionally equivalent.

---

## Summary

| Bugs | Gaps | Warnings | Style |
|------|------|----------|-------|
| 1    | 0    | 2        | 1     |

**Verdict**: PASS WITH WARNINGS — One bug (Unicode arrows on Windows) is the same class of issue already fixed for table separators and is a straightforward find-and-replace. No design gaps. Warnings are defensive hardening, not functional issues.
