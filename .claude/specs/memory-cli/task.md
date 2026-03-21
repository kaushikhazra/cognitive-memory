# Memory CLI — Tasks

## 1. Foundation (connection layer, helpers, entry point)

- [x] **Velasari** updates `pyproject.toml` to add `click>=8.0` dependency and `cognitive-memory-cli = "cognitive_memory.cli:main"` entry point — _US-5.2_
- [x] **Velasari** creates `src/cognitive_memory/cli.py` with connection layer: `DEFAULT_URL`, `CONNECT_TIMEOUT`, `resolve_url()`, `_call_tool_inner()`, `call_tool()`, `run_tool()` — _US-5.1, US-5.2_
- [x] **Velasari** implements parameter helpers in `cli.py`: `split_tags()`, `build_time_range()`, `route_ids()`, `format_age()`, `output_json()` — _US-1.1, US-2.1, US-3.4_
- [x] **Velasari** implements click group with `--url`, `--json`, `--version` global flags and `main()` entry point in `cli.py` — _US-5.2, US-5.3_
- [x] **Velasari** writes unit tests for all helpers in `tests/test_cli.py`: split_tags, build_time_range (both/neither/partial), route_ids, format_age — _NFR: Testing_

## 2. CLI Commands

- [x] **Velasari** implements browsing commands in `cli.py`: `list` (table with ID first column, default limit 20, empty message), `get` (detail view with all fields incl. conversation_id, relationships, versions), `stats` (grouped counts), `related` (table with direction/type/strength) — _US-1.1, US-1.2, US-1.3, US-1.4_
- [x] **Velasari** implements search command in `cli.py`: `recall` (table with rank/score/found_by, --type→type_filter, --time-start+--time-end→time_range, default limit 10, empty message) — _US-2.1_
- [x] **Velasari** implements management commands in `cli.py`: `store` (stdin support via `-`), `update` (at-least-one-flag validation), `delete` (confirmation prompt, --yes bypass), `archive` (IDs vs --below-retrievability routing), `restore`, `relate`, `unrelate`, `consolidate` — _US-3.1, US-3.2, US-3.3, US-3.4, US-3.5, US-3.6_
- [x] **Velasari** implements config command in `cli.py`: `config` (0/1/2 positional args, flat dot-notation display for all config, set confirmation) — _US-4.1_
- [x] **Velasari** writes unit tests for all commands in `tests/test_cli.py` using CliRunner + mocked run_tool: human output, --json, empty results, error cases, delete prompt — _NFR: Testing_

## 3. Integration Testing

- [x] **Velasari** writes integration test in `tests/test_cli_integration.py` spawning real MCP server with in-memory DB, exercising store→list→recall→get→update→delete lifecycle via CLI subprocess — _NFR: Testing_
