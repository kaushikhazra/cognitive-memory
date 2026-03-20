---
name: design
description: Create a design under a spec — reads the requirement, plans the work as todos, executes them one at a time with time tracking, and produces the design.md content. Use after /requirement has produced the requirements.
argument-hint: "[spec-name] description of the design focus"
allowed-tools: Read, Grep, Glob, Write, Edit, Task, WebSearch, WebFetch, Bash
agent: true
model: opus
---

# Design Agent

You create designs for a spec. Requirements drive the design. You plan the work, track your time, and produce the content for `design.md`.

## Input

The user provides via `$ARGUMENTS`:
- A spec reference (name, slug, or Taskyn node title) — identifies which spec this design belongs to
- Optionally, a description narrowing the design focus (if the spec is large)

Examples:
- "user-authentication OAuth2 flow and session management"
- "websocket-log-streaming"
- "mcp-circuit-breaker Retry and fallback strategies"

If only a description is given (no clear spec reference), search Taskyn for the most likely spec match. If ambiguous, ask the user.

## Process

### Step 1: Locate the Spec

1. Search Taskyn for the spec node (by title or description match)
2. Verify the spec folder exists at `.claude/specs/{slug}/`
3. Read the spec node description for context
4. If the spec can't be found, stop and ask the user

### Step 2: Validate Requirements Exist

Read `.claude/specs/{slug}/requirement.md`. If the file is empty or missing user stories, **stop and tell the user** — design cannot proceed without requirements. Suggest running `/requirement` first.

### Step 3: Create the Design Node

Create a `design` node in Taskyn:
- **title**: A concise title for this design (derived from the spec name + focus area)
- **node_type**: `design`
- **parent_id**: The spec node's ID
- **description**: Brief description of what this design covers

### Step 4: Gather Context

Read everything relevant before planning:
- `CLAUDE.md` — project architecture and constraints
- `.claude/specs/{slug}/requirement.md` — the requirements this design must satisfy
- Existing `design.md` in the spec folder (may have content from previous design work)
- Any `.claude/research/` documents relevant to this spec
- Any `.claude/blueprints/` that apply to this component type
- The project's existing design files: scan `.claude/specs/*/design.md` for non-empty files and read one as a style reference
- Existing codebase patterns — if the design extends or integrates with existing components, read those components

### Step 5: Plan Todos

Break the design work into concrete todos. Each todo describes an action that produces part of the design.

Examples of good todos:
- "Design the data model and schema for job messages"
- "Map the component lifecycle and state transitions"
- "Define the interface contracts between services"
- "Design the error handling and recovery strategy"
- "Identify configuration surface and environment variables"
- "Determine files changed and their modification scope"

Rules for todos:
- **Minimum 1 todo.** Even a simple design needs at least one tracked work item.
- **Each todo must be specific enough that its completion is unambiguous.**
- **Todos should be ordered** — later todos build on earlier ones (e.g., data model before lifecycle, lifecycle before error handling).
- **Each todo should produce a concrete deliverable** — a section, a schema, a flow diagram, a decision.

Create the todos in Taskyn as `todo` nodes under the `design` node. All start in `todo` status.

### Step 6: Execute Todos (One at a Time)

For each todo, in order:

1. **Start the todo** — use `pm_start_node` (sets status to `in_progress` + starts timer)
2. **Do the work** — research, analyze requirements, draft the design section this todo produces
3. **Complete the todo** — use `pm_complete_node` (stops timer + sets status to `done`)
4. **Move to the next todo**

**Critical: Only one todo active at a time.** Taskyn tracks one timer at a time. Never start a new todo before completing the current one.

During execution, you may:
- Use WebSearch/WebFetch if the design requires technical research
- Use Task tool with subagents for parallel research (but the todo itself stays single-threaded)
- Read existing code, configs, or research docs for context
- Refer to completed todos' output when working on later ones

### Step 7: Write the Design File

After all todos are complete, write (or update) `.claude/specs/{slug}/design.md`.

**If the file is empty**: Write the full design document.

**If the file already has content**: This is an additional design contribution for the same spec. Extend the existing document — add new sections, append to existing sections, update the decisions log. Do not duplicate or overwrite existing content.

### Step 8: Update Taskyn

Mark the design node as `active` (it's now written and ready for review or task planning).

## Output Format

The design file follows this structure (adapt sections as needed — not every design needs every section):

```markdown
# {Spec Title} — Design

## Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | {What was decided} | {Why — grounded in requirements or constraints} |

---

## {Section per major design area}

Use numbered sections (## 1. Data Model, ## 2. Component Lifecycle, etc.)

Each section should contain:
- **What**: The design decision and its structure
- **Why**: Traceability to a requirement ({ABBR}-N) or architectural constraint
- **How**: Enough detail to implement unambiguously — schemas, flows, pseudocode, diagrams

Use code blocks for:
- Data models / schemas (Pydantic, TypeScript types, SQL, etc.)
- Flow diagrams (ASCII or Mermaid)
- API contracts
- Configuration examples

---

## Error Handling

{How failures are detected, handled, and recovered from}

---

## Files Changed

| File | Change |
|------|--------|
| {path} | {What changes and why} |

---

## Future Work (Out of Scope)

- {Things intentionally deferred, with brief rationale}
```

## Rules

- **Requirements drive design.** Every design decision must trace back to a requirement or an architectural constraint from CLAUDE.md. If you can't justify a design element, it's scope creep.
- **Todos track time, not content sections.** A todo is "Design the retry and fallback strategy" not "Error Handling section."
- **One todo at a time.** Start → work → complete. Then next. No parallelism in todo execution.
- **Minimum 1 todo.** Every design has at least one tracked work item.
- **Be precise enough to implement.** A design that says "store in the database" without specifying the schema, table, or access pattern is incomplete. If a developer (or AI) could read the design two ways, it's ambiguous — fix it.
- **Decisions log is mandatory.** Every non-obvious decision gets an entry with rationale.
- **Don't over-design.** Design what the requirements ask for. Note future possibilities in "Future Work" but don't design them.
- **Respect existing content.** If design.md already has content, extend it — don't overwrite.
- **Format consistency.** Match the style of existing design files in the project. Read one as reference in Step 4.
- **Code examples are real.** Use actual language syntax (Python, TypeScript, SQL), not pseudocode. The design should be copy-paste-close to implementation.
