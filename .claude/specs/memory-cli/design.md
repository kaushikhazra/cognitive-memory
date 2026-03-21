# Memory CLI — Design

## Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Use `click` for CLI parsing | 14 subcommands with typed flags — click's decorator-based approach is significantly cleaner than argparse subparsers. Auto-generates `--help`. One new dependency. (NFR) |
| D2 | Single file `cli.py` | Scope is a thin client — connection helper, 14 command handlers, formatting helpers. No need for sub-packages. |
| D3 | No `rich` dependency for tables | Simple fixed-width string formatting. Keeps dependencies minimal. The output is columns of short text, not complex layouts. |
| D4 | One MCP connection per invocation | CLI is one-shot: connect → call tool → print → exit. No connection pooling, no keep-alive. Matches the `stateless_http=True` server mode. |
| D5 | Exit code 0/1/2 convention | 0 = success, 1 = MCP tool error (memory not found, validation), 2 = connection error (server down, timeout). Enables scripting: `cli recall "x" && echo found`. |
| D6 | `--json` passes through raw MCP response | No reshaping — the CLI outputs exactly what the server returns, pretty-printed. Users can pipe to `jq` for filtering. |
| D7 | Tags as comma-separated strings | `--tags "python,ai"` → `["python", "ai"]`. Consistent across all commands. No quoting issues with shell. |

---

## 1. Architecture

```
┌──────────────────────────────────────────────────┐
│  cognitive-memory-cli (click CLI)                │
│                                                   │
│  main() ─── click.group ─── subcommands          │
│       │                         │                 │
│       │ asyncio.run()           │ parse flags     │
│       ▼                         ▼                 │
│  call_tool(url, tool_name, params)                │
│       │                                           │
│       │ streamablehttp_client + ClientSession      │
│       ▼                                           │
│  MCP Server (http://127.0.0.1:8050/mcp)          │
│       │                                           │
│       │ JSON: {"success": bool, "data": ...}      │
│       ▼                                           │
│  format_output(data, json_mode)                   │
│       │                                           │
│       │ human-readable table or JSON              │
│       ▼                                           │
│  stdout + sys.exit(code)                          │
└──────────────────────────────────────────────────┘
```

Every command follows this pipeline. No command accesses the engine, storage, or database directly.

---

## 2. Connection Layer

### URL Resolution

Priority order (highest first):
1. `--url` flag on the current invocation
2. `COGNITIVE_MEMORY_URL` environment variable
3. Default: `http://127.0.0.1:8050/mcp`

```python
DEFAULT_URL = "http://127.0.0.1:8050/mcp"

def resolve_url(ctx: click.Context) -> str:
    """Get server URL from flag > env > default."""
    return (
        ctx.obj.get("url")
        or os.environ.get("COGNITIVE_MEMORY_URL")
        or DEFAULT_URL
    )
```

### MCP Client Wrapper

```python
CONNECT_TIMEOUT = 5  # seconds (US-5.1)

async def _call_tool_inner(url: str, tool_name: str, params: dict) -> dict:
    """Connect to MCP server, call one tool, return parsed response."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, params)
            return json.loads(result.content[0].text)

async def call_tool(url: str, tool_name: str, params: dict) -> dict:
    """Timeout-guarded MCP tool call.

    Returns dict with keys: success, data, error (if failed), meta.
    Raises ConnectionError on network/timeout failures.
    """
    try:
        return await asyncio.wait_for(
            _call_tool_inner(url, tool_name, params),
            timeout=CONNECT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise ConnectionError(
            f"Server at {url} did not respond within {CONNECT_TIMEOUT} seconds."
        )
    except (ConnectionRefusedError, OSError) as e:
        raise ConnectionError(
            f"Cannot connect to cognitive-memory server at {url}. "
            f"Is the server running?\nStart it with: cognitive-memory"
        ) from e
    except json.JSONDecodeError:
        raise ConnectionError(
            f"Server at {url} returned an invalid response."
        )
```

### Sync Bridge

Click commands are synchronous. The MCP client is async. Bridge with `asyncio.run()`:

```python
def run_tool(ctx: click.Context, tool_name: str, params: dict) -> dict:
    """Synchronous wrapper: resolve URL, call tool, handle errors."""
    url = resolve_url(ctx)
    try:
        response = asyncio.run(call_tool(url, tool_name, params))
    except ConnectionError as e:
        click.echo(str(e), err=True)
        sys.exit(2)

    if not response.get("success"):
        click.echo(f"Error: {response.get('error', 'Unknown error')}", err=True)
        sys.exit(1)

    return response
```

---

## 3. Command Structure and MCP Parameter Mapping

### CLI Group

```python
@click.group()
@click.option("--url", default=None, help=f"Server URL (default: {DEFAULT_URL}, env: COGNITIVE_MEMORY_URL)")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
@click.version_option(package_name="cognitive-memory")
@click.pass_context
def cli(ctx, url, json_mode):
    """Cognitive Memory CLI — browse, search, and manage memories."""
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["json"] = json_mode
```

### Command → MCP Tool Mapping

| CLI Command | MCP Tool | Parameter Translations |
|---|---|---|
| `list` | `memory_list` | `--type`→`type`, `--state`→`state`, `--tags`→`tags` (comma split), `--search`→`search`, `--limit`→`limit` (default: 20), `--offset`→`offset`, `--importance-min`→`importance_min`, `--importance-max`→`importance_max` |
| `get <id>` | `memory_get` | `id` (positional) |
| `recall <query>` | `memory_recall` | `query` (positional), `--type`→`type_filter`, `--tags`→`tags` (comma split), `--limit`→`limit` (default: 10), `--time-start`+`--time-end`→`time_range` dict (both required if either given) |
| `stats` | `memory_stats` | _(no params)_ |
| `store <content>` | `memory_store` | `content` (positional or stdin), `--type`→`type`, `--tags`→`tags` (comma split), `--importance`→`importance`, `--source`→`source` |
| `update <id>` | `memory_update` | `id` (positional), `--content`→`content`, `--type`→`type`, `--importance`→`importance`, `--tags`→`tags` (comma split) |
| `delete <ids...>` | `memory_delete` | 1 id→`id`, 2+→`ids`, `confirm=True` (after prompt or `--yes`) |
| `archive [ids...]` | `memory_archive` | IDs given: 1→`id`, 2+→`ids`. No IDs + `--below-retrievability`→`below_retrievability` only. Both→error. |
| `restore <ids...>` | `memory_restore` | 1 id→`id`, 2+→`ids` |
| `relate <src> <tgt>` | `memory_relate` | `source_id`, `target_id`, `--type`→`rel_type` (required), `--strength`→`strength` |
| `unrelate <src> <tgt>` | `memory_unrelate` | `source_id`, `target_id`, `--type`→`rel_type` (required) |
| `related <id>` | `memory_related` | `id`, `--depth`→`depth`, `--rel-types`→`rel_types` (comma split) |
| `consolidate` | `memory_consolidate` | `--dry-run`→`dry_run` |
| `config [key] [value]` | `memory_config` | `@click.argument("key", required=False)`, `@click.argument("value", required=False)`. No args→show all, key only→read, key+value→set. |

### Parameter Transformations

```python
def split_tags(tags: str | None) -> list[str] | None:
    """'python,ai' → ['python', 'ai']. None → None."""
    if tags is None:
        return None
    return [t.strip() for t in tags.split(",") if t.strip()]

def build_time_range(start: str | None, end: str | None) -> dict | None:
    """Two ISO 8601 strings → time_range dict. None if neither provided.
    Requires both or neither — partial ranges are rejected.
    """
    if not start and not end:
        return None
    if bool(start) != bool(end):
        click.echo("Error: --time-start and --time-end must both be provided", err=True)
        sys.exit(2)
    return {"start": start, "end": end}

def route_ids(ids: tuple[str, ...]) -> dict:
    """Single ID → {'id': x}. Multiple → {'ids': list}."""
    if len(ids) == 1:
        return {"id": ids[0]}
    return {"ids": list(ids)}
```

### Stdin Support for `store`

```python
@cli.command()
@click.argument("content", default="-")
# ... flags ...
def store(content, **kwargs):
    if content == "-":
        content = click.get_text_stream("stdin").read().strip()
        if not content:
            click.echo("Error: No content provided via stdin", err=True)
            sys.exit(1)
```

---

## 4. Output Formatting

### JSON Mode

All commands check `ctx.obj["json"]`. If true, output the raw MCP response:

```python
def output_json(response: dict) -> None:
    """Print raw MCP response as pretty JSON."""
    click.echo(json.dumps(response, indent=2, default=str))
```

### List Table (US-1.1)

```
ID        Type       Imp   Age     Tags              Content
────────  ─────────  ────  ──────  ────────────────  ──────────────────────────────────────────
e756ad4b  semantic   0.80  2h ago  python, ai        Python is a versatile programming lang…
a3f1c902  episodic   0.65  3d ago  meeting           Discussed the new CLI architecture with…
```

Columns: ID (8 char), Type (9), Importance (4, 2dp), Age (6), Tags (16, truncated), Content (remaining, truncated with `…`).

### Recall Table (US-2.1)

```
#   Score  ID        Type       Tags              Found By   Content
──  ─────  ────────  ─────────  ────────────────  ─────────  ──────────────────────────────────
1   0.847  e756ad4b  semantic   python, ai        semantic   Python is a versatile programm…
2   0.712  a3f1c902  episodic   meeting           keyword    Discussed the new CLI architect…
```

### Get Detail (US-1.2)

```
Memory e756ad4b-1b45-4a44-837a-118cfb2d5d79

Content:
  Python is a versatile programming language used widely in AI and data science.

Type:           semantic
State:          active
Importance:     0.80
Stability:      3.50
Retrievability: 0.92
Access Count:   12
Tags:           python, ai
Source:         conversation with Kaushik
Conversation:   conv-abc123
Created:        2026-03-19 12:30:00 UTC
Updated:        2026-03-20 08:15:00 UTC
Last Accessed:  2026-03-21 17:00:00 UTC

Relationships:
  → relates_to  a3f1c902 (strength: 0.85)
  ← supports    b7d2e410 (strength: 1.00)

Versions (2):
  [1] 2026-03-19 12:30:00 — Python is a versatile programming language
  [2] 2026-03-20 08:15:00 — Python is a versatile programming language used widely in AI…
```

### Stats Display (US-1.3)

```
Memory Statistics

By Type:
  working:     3
  episodic:    45
  semantic:    128
  procedural:  12

By State:
  active:      175
  archived:    13

Decay (avg retrievability):
  working:     0.32
  episodic:    0.71
  semantic:    0.89
  procedural:  0.95

Total: 188 memories
```

### Related Table (US-1.4)

```
Direction  Rel Type    Strength  ID        Content
─────────  ──────────  ────────  ────────  ──────────────────────────────────────────
→          relates_to  0.85      a3f1c902  Discussed the new CLI architecture with…
←          supports    1.00      b7d2e410  The MCP server pattern is proven and sta…
```

### Config Display (US-4.1)

Flat dot-notation, one key per line, sorted:

```
decay.base_stability       = 2.0
decay.growth_factor        = 3.0
decay.min_stability        = 0.5
retrieval.weights.graph    = 0.15
retrieval.weights.keyword  = 0.25
retrieval.weights.semantic = 0.40
retrieval.weights.temporal = 0.20
```

### Mutating Command Output

Simple single-line confirmations for write operations:

```
store       → Stored e756ad4b (semantic, importance: 0.80)
update      → Updated e756ad4b (content, tags)          # lists which fields changed
delete      → Deleted 1 memory                          # or "Deleted 3 memories"
archive     → Archived 1 memory                         # or "Archived 12 memories (below retrievability 0.3)"
restore     → Restored 1 memory
relate      → Related e756ad4b → a3f1c902 (relates_to, strength: 1.00)
unrelate    → Unrelated e756ad4b → a3f1c902 (relates_to)
consolidate → Consolidation complete: 2 promotions, 1 archival, 0 merges
              (dry-run: "Would promote 2, archive 1, merge 0")
config set  → Set decay.growth_factor = 3.0
```

Delete confirmation prompt (before calling MCP tool):

```
Permanently delete memory e756ad4b? [y/N] y
Deleted 1 memory
```

Skipped with `--yes` flag. For multiple IDs: `Permanently delete 3 memories? [y/N]`.

### Empty Results

When a query or list returns zero results, print a friendly message instead of an empty table:

```
list    → No memories found.
recall  → No memories match your query.
related → No related memories found.
```

### Age Formatting

```python
def format_age(dt_str: str) -> str:
    """ISO datetime string → relative age string."""
    dt = datetime.fromisoformat(dt_str)
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 60:      return "now"
    if seconds < 3600:    return f"{int(seconds // 60)}m ago"
    if seconds < 86400:   return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:  return f"{int(seconds // 86400)}d ago"
    if seconds < 2592000: return f"{int(seconds // 604800)}w ago"
    return f"{int(seconds // 2592000)}mo ago"
```

---

## 5. Error Handling

### Error Categories

| Category | Cause | Exit Code | Output |
|---|---|---|---|
| Connection error | Server not running, network failure | 2 | `Cannot connect to cognitive-memory server at <url>. Is the server running?\nStart it with: cognitive-memory` |
| Timeout error | Server unresponsive (5s limit) | 2 | `Server at <url> did not respond within 5 seconds.` |
| Tool error | MCP tool returns `success: false` | 1 | `Error: <error message from server>` |
| Usage error | Missing required flag, invalid value | 2 | Click's built-in usage error (shows `--help` hint) |

### Exception Flow

```
click parses args
  └─ invalid? → click prints usage error, exit 2
  └─ valid → run_tool()
       └─ ConnectionError? → print message, exit 2
       └─ success: false? → print error, exit 1
       └─ success: true → format + print, exit 0
```

No stack traces reach the user. All exceptions are caught and formatted as plain text to stderr.

---

## 6. File Structure

```
src/cognitive_memory/
    cli.py              # New — all CLI code
    server.py           # Existing — MCP server
    service.py          # Existing — Windows service
    ...
```

### cli.py Internal Layout

```
# Imports (click, asyncio, json, mcp client)
# Constants (DEFAULT_URL)
# Connection helpers (resolve_url, call_tool, run_tool)
# Output helpers (format_age, print_table, output_json, split_tags, build_time_range, route_ids)
# Click group (cli) with global flags
# Browsing commands (list_, get, stats, related)
# Search commands (recall)
# Management commands (store, update, delete, archive, restore, relate, unrelate, consolidate)
# Config command (config)
# Entry point: def main(): cli()
```

Note: `list` is a Python builtin, so the click command function is named `list_` with `@cli.command("list")`.

---

## 7. Testing Strategy

### Unit Tests

Mock `call_tool` at the sync bridge level. `run_tool` is the seam — replace it to test command logic without network:

```python
def test_list_empty(runner, mock_run_tool):
    mock_run_tool.return_value = {"success": True, "data": {"memories": []}, "meta": {}}
    result = runner.invoke(cli, ["list"])
    assert "No memories found" in result.output
```

Use `click.testing.CliRunner` for invoking commands and capturing output.

### Integration Tests

Spawn the real MCP server (same pattern as `test_mcp_client.py`), then invoke CLI commands against it:

```python
# Start server on a test port with in-memory DB
# Run: cognitive-memory-cli --url http://127.0.0.1:{port}/mcp store "test"
# Verify: cognitive-memory-cli --url ... list --json | jq '.data.memories | length'
```

### What to Test

- Each command's human output format (snapshot tests)
- `--json` flag produces valid JSON on every command
- Connection error message when server is down
- Empty results messages
- Parameter transformations (split_tags, build_time_range, route_ids)
- Delete confirmation prompt (with and without `--yes`)
- Stdin pipe for `store -`

---

## Files Changed

| File | Change |
|------|--------|
| `src/cognitive_memory/cli.py` | **New** — CLI tool with all 14 commands and helpers |
| `pyproject.toml` | Add `click>=8.0` to dependencies, add `cognitive-memory-cli = "cognitive_memory.cli:main"` to `[project.scripts]` |

---

## Future Work (Out of Scope)

- **Short ID prefix matching** — resolve 8-char prefixes to full UUIDs (deferred; CLI is primarily a search tool)
- **Shell tab completion** — click supports it natively via `click.shell_complete`; enable when CLI is stable
- **Export/import** — bulk dump to JSON file; can be approximated with `list --json --limit 9999 > backup.json`
- **`--sort` on `list`** — requires server-side support or client-side re-sort
- **`rich` tables** — optional dependency for prettier output; current simple formatting is sufficient
