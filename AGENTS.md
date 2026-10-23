# AGENTS.md

This file is the mandatory operating contract for every AI agent working in this repository. Read it before doing anything else.

## 1. Non-negotiable rules

1. **Beads (`bd`) is the only task tracker.** Every unit of work must exist as a Beads issue before code is written, reviewed, or committed. Markdown TODO lists, `todowrite`, editor task lists, and ad-hoc notes are forbidden as work trackers.
2. **The SRS is the product source of truth:** `docs/SRS.md`. Do not invent requirements. If the SRS is ambiguous or contradictory, create a `decision` or `spike` issue and ask the user before implementing.
3. **MVP only for now.** Work F0/F1 scope from `docs/SRS.md` sections 11.1 and 11.2. Do not start F2/F3 work unless the user explicitly approves a new issue for it.
4. **One issue, one branch, one concern.** Never work directly on `main`. Never mix unrelated issues in one branch.
5. **English is the engineering language.** Code, identifiers, file and directory names, comments, docstrings, tests, commit messages, branch names, issue titles/descriptions, and technical documentation are written in English. Only GUI text and player-facing strings are Spanish. The existing SRS remains Spanish because it is the product specification.
6. **Do not commit secrets.** Tokens, API keys, credentials, `.env` files, and runtime session data must never be committed.
7. **Do not weaken tests, validation, determinism, or security to make a change pass.** Fix the cause.
8. **Do not add agent administration tools to MCP.** Agents must never receive full-map, RNG, operator, or debug access.

If any instruction conflicts, stop and ask the user. The order of authority is: user instruction, this file, `docs/SRS.md`, the claimed Beads issue, then existing code.

## 2. Session start protocol

Run these commands at the start of every session and after any context loss:

```bash
bd prime
bd ready --json
bd list --status=in_progress --json
```

Then select work only from `bd ready`, unless the user explicitly assigns a different issue.

Before writing code:

```bash
bd show <issue-id>
bd update <issue-id> --claim
git switch main
git pull --ff-only            # only when a remote exists
git switch -c <type>/<issue-id>-<short-slug>
```

If a remote does not exist, skip `git pull` and continue locally.

## 3. Beads workflow

### 3.1 Find and claim work

- `bd ready` lists unblocked work. This is the default queue.
- `bd show <id>` must be read before implementation.
- `bd update <id> --claim` atomically assigns the issue and marks it in progress.
- Never claim an epic. Epics are containers; claim their child tasks.
- Never work on a blocked issue. Resolve or document the blocker first.

### 3.2 Keep the graph correct

Dependencies are mandatory when the order matters:

```bash
bd dep add <blocked-issue> <blocking-issue>
bd dep tree <epic-id>
bd graph
bd blocked
```

- Use `parent` for hierarchy: task under epic, subtask under task.
- Use `blocks` for real execution order.
- Use `relates-to` only for knowledge links, never to fake ordering.
- Use `discovered-from` when new work is found while implementing an issue.
- Run `bd dep cycles` after bulk graph edits.

### 3.3 Record decisions and progress

- `bd note <id> "..."` for implementation notes.
- `bd comment <id> "..."` for review/audit discussion.
- `bd remember "..."` for durable project knowledge that future sessions need.
- `bd memories <query>` before re-litigating an old decision.
- Use `bd supersede` or `bd duplicate`; never delete history merely to hide a mistake.
- Never hand-edit `.beads/` files or the Dolt database.

### 3.4 Close work

Close an issue only when every acceptance criterion is met:

```bash
bd close <id> --reason "Implemented and verified: <evidence>" --suggest-next
```

Before closing:

```bash
bd show <id>
pytest
ruff check .
ruff format --check .
mypy src
git status
```

If a command does not exist yet because the project is not scaffolded, record that in the issue and close only the setup portion that is actually complete. Never claim a test passed when it was not run.

### 3.5 Epics and milestones

- Epics use `--type epic` and have a measurable success criterion.
- Child tasks use `--parent <epic-id>`.
- `bd epic status <epic-id>` reports completion.
- Close an epic only after all children are closed and its success criterion is verified.
- A milestone marks a release; it is not implementation work.

### 3.6 Sync and backup

There is currently no remote configured. Do not fabricate a push.

- When a remote exists: `bd dolt push` after meaningful local work, and `bd dolt pull` before starting.
- Use `bd sync` only when the remote workflow is configured.
- Local durability: `bd export --all` before risky database operations.
- Never commit `.beads/embeddeddolt/` or other runtime database files.

## 4. Issue quality standard

Every issue must be actionable without reopening the whole SRS.

Required content:

- **Title:** imperative, specific, English, no vague "improve stuff".
- **Description:** context, scope, and the exact SRS requirement IDs (for example `RF-501`, `RF-1104`).
- **Acceptance criteria:** observable and testable.
- **Dependencies:** blockers recorded with `bd dep add`, not only mentioned in prose.
- **Non-goals:** what is intentionally excluded.
- **Relevant SRS section:** use `--spec-id` and/or an external reference such as `docs/SRS.md#44-agentes-y-atributos-rf-400`.

Recommended creation command:

```bash
bd create \
  --title "Implement deterministic shadowcasting FOV" \
  --type feature \
  --priority 1 \
  --parent <epic-id> \
  --labels "mvp,phase:1,area:perception" \
  --estimate 180 \
  --spec-id "RF-501" \
  --description "..." \
  --acceptance "..." \
  --design "..." \
  --notes "..." \
  --json
```

Use `--validate` when the issue type requires template sections. Run `bd lint` after bulk edits.

### Priority scale

| Priority | Meaning |
|---|---|
| P0 | Blocks the MVP or the build; drop everything |
| P1 | Required MVP capability on the critical path |
| P2 | Normal MVP work |
| P3 | Useful polish or non-critical MVP work |
| P4 | Backlog; not for current MVP execution |

### Label vocabulary

Use lowercase, comma-separated labels:

- Phase: `phase:0`, `phase:1`
- Scope: `mvp`
- Area: `area:core`, `area:world`, `area:agents`, `area:crafting`, `area:perception`, `area:social`, `area:combat`, `area:mcp`, `area:ui`, `area:persistence`, `area:metrics`, `area:config`, `area:tests`, `area:release`
- Kind when useful: `risk`, `security`, `determinism`, `performance`, `docs`

Do not invent a parallel label taxonomy.

## 5. Git workflow

### 5.1 Branches

Branch from an up-to-date `main`:

```text
feat/<issue-id>-<short-slug>
fix/<issue-id>-<short-slug>
test/<issue-id>-<short-slug>
docs/<issue-id>-<short-slug>
chore/<issue-id>-<short-slug>
refactor/<issue-id>-<short-slug>
perf/<issue-id>-<short-slug>
```

Examples:

```text
feat/iasim-a3f2-deterministic-rng
fix/iasim-b7c1-timeout-disconnect
test/iasim-c9d4-mcp-reconnect
```

Rules:

- `main` is always releasable.
- No direct commits to `main`.
- Keep branches short-lived and scoped to one issue.
- Rebase on `main` before review when the branch is private; do not rewrite shared history.
- Delete merged feature branches.

### 5.2 Commits

Use Conventional Commits:

```text
<type>(<scope>): <imperative summary>

<body explaining why and any trade-offs>

Refs: <issue-id>
```

Allowed types: `feat`, `fix`, `test`, `docs`, `refactor`, `perf`, `chore`, `build`, `ci`.

- Subject in English, imperative, no trailing period, 72 characters or fewer.
- Reference the Beads issue in the footer.
- Commit only working, coherent states.
- Do not commit generated/runtime artifacts, secrets, or unrelated formatting changes.

### 5.3 Tags and semantic versioning

Use [Semantic Versioning 2.0.0](https://semver.org/):

```text
vMAJOR.MINOR.PATCH
```

- `MAJOR`: incompatible protocol, save-format, or behavior break.
- `MINOR`: backward-compatible feature.
- `PATCH`: backward-compatible fix.
- Pre-releases: `v0.1.0-rc.1`, `v0.1.0-beta.2`.
- MVP release target: `v0.1.0`.
- Tags are annotated and created only after the release issue's acceptance criteria pass:

```bash
git tag -a v0.1.0 -m "IASim MVP v0.1.0"
```

- The version in `pyproject.toml` is the single source of truth for the package version.
- Do not tag unverified work. Do not move or reuse a published tag.

## 6. Code standards

### 6.1 Stack and layout

- Python 3.12+.
- Package manager and runner: `uv`.
- Dependency and tool configuration: `pyproject.toml`.
- Source layout: `src/iasim/`; tests: `tests/`.
- Rendering: `python-tcod` (libtcod).
- MCP transport: local HTTP as specified in the SRS.
- Data models and validation: Pydantic where a schema boundary exists; dataclasses or typed models for internal domain objects.
- Tests: `pytest`.

Expected module boundaries:

```text
src/iasim/
  app/            # session orchestration and use cases
  domain/         # pure simulation rules and entities
  world/          # map generation, terrain, resources
  agents/         # needs, attributes, perception, inventory
  social/         # chat, alliances, trade
  combat/         # attacks, damage, death
  mcp/            # transport, auth, tools, schemas
  persistence/    # save/load, JSONL, replay, metrics
  ui/             # terminal rendering and input
  config/         # TOML parsing and validation
  cli/            # command-line entry points
```

- `domain/` must not import `ui/`, `mcp/`, or persistence adapters.
- `mcp/` must not contain game rules; it validates and delegates to `app/`.
- `ui/` is presentation only; it must not mutate simulation state directly.
- Determinism is a domain invariant: seeded RNG, stable ordering, integer or carefully specified arithmetic.

### 6.2 Python style

- Use type annotations on public functions, methods, and non-trivial locals.
- Prefer small functions and explicit data models over nested dictionaries.
- Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants.
- File names are English, lowercase, and descriptive.
- Public modules, classes, and functions require docstrings explaining purpose, inputs, outputs, and invariants.
- Comments explain **why**, not **what**. Remove commented-out code.
- Raise domain-specific exceptions; never use bare `except:`.
- Do not use mutable global state. Inject configuration, RNG, clock, and repositories.
- Log through the project logger. Never log tokens, secrets, or full agent prompts containing credentials.
- Keep lines readable; use `ruff format`.
- No unused code, dead flags, or speculative abstractions.
- All GUI-visible strings are Spanish; all internal identifiers and logs are English.

### 6.3 Testing and quality gates

Every implementation task must add or update tests.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

- Unit tests cover pure rules and edge cases.
- Integration tests cover MCP join, observe, action, timeout, reconnect, save/load, and replay.
- Determinism tests use a golden seed and assert the canonical state hash.
- Performance tests cover 8 agents and the SRS tick budget.
- A bug fix requires a regression test that fails before the fix.
- Visual/UI tasks require the manual checklist in the SRS.

### 6.4 Documentation

- The SRS is the requirements authority. Update it before implementing a changed requirement.
- Architecture decisions that affect multiple issues must be recorded in a `decision` Beads issue.
- Public protocol changes require an SRS update and a schema/version note.
- Do not create duplicate planning documents; link to the Beads issue and SRS anchors instead.

## 7. Architecture and safety invariants

- Agents are external. IASim never generates agent decisions.
- One primary action per tick, plus free `say` and `report_mind` as specified.
- Every action is validated against tick, ownership, range, visibility, requirements, and inventory.
- Agent observations contain only perceived information, never the full map, RNG, or other agents' hidden state.
- The operator UI may see everything; the MCP surface must not.
- Death is permanent; corpses are lootable; the session ends when no agents remain.
- All randomness flows through the seeded deterministic RNG.
- Save, replay, and metrics must reproduce the same canonical state hash.
- The debug console is operator-only and never exposed through MCP.

## 8. Definition of Done

A task is done only when all of the following are true:

- The issue was claimed in Beads and its acceptance criteria were met.
- The implementation is in English, typed, documented, and follows module boundaries.
- Unit/integration tests pass and the quality gates above are clean.
- The SRS is updated if behavior or a public contract changed.
- No secrets, runtime databases, or generated artifacts are staged.
- The branch contains only the issue's changes.
- `bd close <id> --reason "..."` records the evidence.
- `git status` is clean except for intentionally untracked, gitignored files.
- If a remote exists, the branch is pushed and a PR is opened with the issue ID.

## 9. Session close protocol

Before saying the work is complete:

```bash
bd close <completed-ids> --reason "Verified: <evidence>"
pytest
ruff check .
ruff format --check .
mypy src
git status
bd epic status <epic-id>    # when the task belongs to an epic
```

Then report:

- Beads issue IDs closed or updated.
- Tests and quality gates actually run.
- Files changed.
- Remaining blockers or follow-up issues.
- Whether a release tag was created.

No remote is configured yet. Do not push, pull, or claim remote sync until the user configures an origin.
