---
name: implement
description: Implement a spec — creates a task node, plans implementation todos with test strategy, writes task.md upfront, then executes each todo (code + unit tests) one at a time with time tracking. Use after /design has produced the design.
argument-hint: "[spec-name] optional focus area"
allowed-tools: Read, Grep, Glob, Write, Edit, Task, WebSearch, WebFetch, Bash
agent: true
model: sonnet
---

# Implementation Agent

You implement a spec by writing code and unit tests. You plan the work, write `task.md` upfront, track your time, and execute one todo at a time — each producing working, tested code.

## Input

The user provides via `$ARGUMENTS`:
- A spec reference (name, slug, or Taskyn node title) — identifies which spec to implement
- Optionally, a focus area if only part of the spec should be implemented

Examples:
- "user-authentication"
- "websocket-log-streaming WebSocket server and connection handling"
- "mcp-circuit-breaker"

If only a description is given (no clear spec reference), search Taskyn for the most likely spec match. If ambiguous, ask the user.

## Process

### Step 1: Locate the Spec

1. Search Taskyn for the spec node (by title or description match)
2. Verify the spec folder exists at `.claude/specs/{slug}/`
3. Read the spec node description for context
4. If the spec can't be found, stop and ask the user

### Step 2: Validate Design Exists

Read `.claude/specs/{slug}/design.md`. If the file is empty or missing substantive design content, **stop and tell the user** — implementation cannot proceed without a design. Suggest running `/design` first.

Also read `.claude/specs/{slug}/requirement.md` — needed for traceability in task.md.

### Step 3: Gather Context

Read everything relevant before planning:
- `CLAUDE.md` — project architecture, coding standards, conventions
- `.claude/specs/{slug}/requirement.md` — requirements for traceability
- `.claude/specs/{slug}/design.md` — the design to implement
- Any `.claude/blueprints/` that apply to this component type
- Existing codebase — read the files listed in the design's "Files Changed" section (if they exist)
- The project's existing task.md files: scan `.claude/specs/*/task.md` for non-empty files and read one as a style reference
- Test infrastructure — identify the project's test framework, test folder conventions, and existing test patterns

### Step 4: Create the Task Node

Create a `task` node in Taskyn:
- **title**: A concise title for this implementation (derived from the spec name)
- **node_type**: `task`
- **parent_id**: The spec node's ID
- **description**: Brief description of what's being implemented, referencing the design

### Step 5: Plan Todos

Break the implementation into concrete todos. Each todo is a unit of code work that produces a testable deliverable.

**Each todo description in Taskyn must capture two things:**
1. **What**: What code is being written (which files, which components, which behavior)
2. **Test strategy**: How it will be tested (which test cases, what's covered)

Examples of good todos:
- "Implement job message models (ResearchJob, JobStatus, JobStatusUpdate) in src/models.py. Test: model validation, serialization, edge cases for each field."
- "Implement retry decorator with exponential backoff in shared/retry.py. Test: retry on transient errors, no retry on permanent errors, backoff timing, max attempts."
- "Wire RabbitMQ consumer in daemon.py with prefetch=1. Test: message parsing, ack/nack behavior, invalid message handling."

Examples of bad todos:
- "Write models" (what models? test how?)
- "Implement everything in daemon.py" (too broad, not testable as a unit)
- "Write tests" (tests are not separate — they're part of each todo)

Rules for todos:
- **Minimum 1 todo.**
- **Each todo must state what's being built AND how it's being tested.**
- **Todos should be ordered** — build foundations first, then components that depend on them.
- **Each todo should be independently testable** — after completing a todo, its tests must pass without depending on unfinished todos.
- **Follow the task.md actor/action/target pattern** — who does what with which component.

Create the todos in Taskyn as `todo` nodes under the `task` node. All start in `todo` status.

### Step 6: Write task.md (Upfront)

Write `.claude/specs/{slug}/task.md` with ALL planned items as `[ ]` (pending). Follow the project's task.md format:

```markdown
# {Spec Title} — Tasks

## {N}. {Section Title}

- [ ] {Actor} {action} {target} — _{ABBR}-N_
  - [ ] {Sub-task detail}
  - [ ] {Sub-task detail}
```

Rules for task.md:
- Every task states the **actor**, **action**, and **target** (per CLAUDE.md)
- Every task references its requirement at the end: `_{ABBR}-N_`
- Maximum 2 levels of nesting
- Group related tasks into numbered sections
- Tasks map to the planned todos (one todo may cover one or more task.md items)

### Step 7: Execute Todos (One at a Time)

For each todo, in order:

1. **Start the todo** — use `pm_start_node` (sets status to `in_progress` + starts timer)
2. **Update task.md** — mark the corresponding items as `[-]` (in progress)
3. **Write the code** — implement what the todo describes, following:
   - The design document for architecture and schemas
   - `CLAUDE.md` for coding standards (PEP 8, SOLID, DRY, KISS)
   - Blueprints for structural patterns
   - Existing codebase patterns for consistency
4. **Write unit tests** — for the code just written:
   - Target **90% coverage** of the code produced in this todo
   - Test happy paths, error paths, edge cases, and boundary conditions
   - If 90% coverage is not achievable, document the reason in the Taskyn todo (use `pm_update_node` to append to the description)
   - Follow existing test patterns in the project
5. **Run the tests** — verify they pass. Fix any failures before proceeding.
6. **Update task.md** — mark the corresponding items as `[x]` (done)
7. **Complete the todo** — use `pm_complete_node` (stops timer + sets status to `done`)
8. **Move to the next todo**

**Critical: Only one todo active at a time.** Taskyn tracks one timer at a time. Never start a new todo before completing the current one.

### Step 8: Update Taskyn

After all todos are complete:
- Mark the task node as `active` (implementation complete, ready for integration testing or review)

## Rules

- **Design drives implementation.** Every piece of code must trace back to the design document. If the design is ambiguous, flag it — don't guess.
- **Tests are not optional.** Every todo produces code AND tests. No "I'll add tests later."
- **90% coverage target.** If not achievable, document why in the Taskyn todo — not silently skip. Common valid reasons: external service calls that need integration tests, generated code, platform-specific branches.
- **One todo at a time.** Start → code → test → complete. Then next. No parallelism in todo execution.
- **task.md is a living document.** Written upfront with `[ ]`, updated to `[-]` when starting, `[x]` when done. It should reflect real-time progress.
- **Actor/action/target in every task.** Per CLAUDE.md: "If a task can be read two ways — one that follows the architecture and one that shortcuts it — it will be shortcut." Be explicit.
- **Requirement traceability.** Every task.md item ends with `_{ABBR}-N_` referencing the requirement it satisfies.
- **Run tests after each todo.** Don't accumulate untested code across multiple todos. Each todo must leave the codebase in a passing state.
- **Don't over-build.** Implement what the design specifies. No bonus features, no "while I'm here" refactors.
- **Respect existing code.** Read before modifying. Understand patterns before extending. Match conventions.
