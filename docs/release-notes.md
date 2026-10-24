# IASim v0.1.0 — MVP release notes

Release date: 2026-10-24 · Package version: `0.1.0` · MCP protocol:
`iasim-mcp/1.0` · Python 3.12+.

## What shipped

IASim v0.1.0 is the F0/F1 MVP described in [SRS §11.2](SRS.md):

- Procedural 80×40 island, deterministic seed, day/night cycle (288 ticks per
  day, 5 minutes per tick by default), base weather and temperature.
- Survival: attributes, needs, statuses, permanent death, corpses and looting.
- Inventory with weight and slots, equipment, gathering, tier-1 and
  workbench-tier-2 crafting, construction.
- Perception-limited observation, FOV and memory, local chat, alliances, trade,
  adjacent melee combat, thrown stones, fleeing and bleeding.
- Authenticated MCP over streamable HTTP with the full action surface, timeouts,
  idempotent request ids, rate limits and ephemeral agents.
- 160×45 operator GUI with the tabbed panel, F1–F8/F11 views, inspection cursor,
  Spanish text and ASCII fallback.
- Run directories with JSONL logs, atomic save/load, snapshots,
  deterministic replay, `summary.json`, `metrics.csv` and a session summary.
- Report API usage and mind reports for the operator, without exposing hidden
  state to agents.
- Deterministic scripted reference agent, acceptance harness and performance
  budgets.

## Verification at release

- Suite: `pytest` — full suite green (780+ tests, 460+ subtests).
- Static gates: `ruff check`, `ruff format --check` and `mypy src` clean.
- Performance (8 agents, SRS RNF-02/03): core tick p95 **17.48 ms** (budget
  50 ms), UI render p95 **12.33 ms** (budget 33.33 ms). See
  [performance.md](performance.md).
- Three-day scenario: **864 ticks**, alliance and chat, death at tick **608**,
  corpse looted, replay **MATCH**, final hash
  `8256d8aa…`. See [scenario-qul7.md](scenario-qul7.md).
- Acceptance harness: **28 PASS / 0 FAIL / 3 SKIP**; the SKIPs are the window,
  visual fullscreen and second physical host. See
  [acceptance-qul6.md](acceptance-qul6.md).
- Determinism: golden seed and replay tests pin per-tick hashes. See
  [tests/test_golden_seed.py](../tests/test_golden_seed.py).

## Known limitations

- GUI/fullscreen require a desktop; CI covers renderers, CLI, headless and LAN
  configuration.
- LAN MCP is plaintext HTTP without TLS; distribute `agents.json` tokens only
  on a trusted network. `--dev-open` is loopback-only and development-only.
- Font scaling is validated but applied by the window backend, not the text
  renderer.
- The scenario and acceptance matrix are deterministic scripts, not free-form
  agent intelligence.

## Not in v0.1.0 (F2/F3)

Snow per tile, 7-day seasons, passive fauna and fishing, cooking, simple
durability, probabilistic forecast, optional mouse support, the advanced debug
console, and an integrated LLM agent or OpenAI-compatible comparison are **not
delivered** in this release. Do not treat them as shipped features.

## Upgrade notes

This is the first release; there is no migration from an earlier version. The
canonical save format, metrics columns and MCP protocol version are documented
in the SRS and are the compatibility baseline for future releases.
