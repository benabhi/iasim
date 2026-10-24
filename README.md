# IASim

Deterministic multi-agent survival sandbox with an MCP interface for external
agents and a 160×45 terminal operator GUI. IASim runs the world and validates
every action; the agents are external clients and IASim never generates their
decisions or calls an LLM itself.

**Version:** `0.1.0` (MVP) · **MCP protocol:** `iasim-mcp/1.0` · **Python:** 3.12+

## Quick start

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run iasim --config config/iasim.toml --seed 42 --max-agents 2
```

The main command opens the full operator GUI and starts the authenticated MCP
server and the world in the same process. Loopback is the default; use
`--host 0.0.0.0` only on a trusted LAN.

```bash
# GUI + MCP (default)
uv run iasim --seed 42 --max-agents 2 --log-dir runs

# Headless server only, for automation/tests
uv run iasim serve --headless --host 127.0.0.1 --port 8765

# Reference agent against a running server (token from the run's agents.json)
uv run python -m iasim.reference_agent \
  --url http://127.0.0.1:8765/mcp \
  --token <TOKEN> --ticks 500
```

`iasim`, `iasim serve` and `python -m iasim` are aliases. The command prints the
MCP endpoint, the run directory and the agents file; by default it never prints
tokens. Tokens are distributed in `agents.json` inside the run directory.

To invite an agent without opening `agents.json`, start with `--show-tokens`:

```bash
uv run iasim serve --show-tokens --host 0.0.0.0 --max-agents 4
```

It prints one `URL` plus `Authorization: Bearer <token>` block per slot, with a
warning, **on the console only**. Tokens are never written to `iasim.log` or the
JSONL artifacts, and the default output stays token-free. Anyone who can read
that console can use the slot; share the token over a private channel and stop
the session if it leaks.

## What the operator sees

The GUI has a map, a tabbed right panel (summary, events, mind, links), the
agent strip and the full-screen views:

| Key | View |
|---|---|
| `F1` | Help and glyph/status legend |
| `F2` | Agent sheet (attributes, mind, inventory, relations) |
| `F3` | World summary (agent table, weather, environment) |
| `F4` | Event log with type/agent filters and `/` search |
| `F5` | Replay notice in a live session; full replay with `iasim --replay <run>/replay.json` |
| `F6` | Enlarged map with legend |
| `F7` | Metrics and session summary |
| `F8` | Display settings; `F11` toggles fullscreen |
| `X` | Inspection cursor; arrows move, `Enter` pins, `Esc` closes |

GUI text is Spanish; the ASCII fallback (`A`) is readable without Unicode
glyphs. See [docs/SRS.md](docs/SRS.md) §5 for the full layout and key map.

## Run artifacts

Each run directory contains `session.json`, `agents.json`, `events.jsonl`,
`actions.jsonl`, `thoughts.jsonl`, `replay.json`, `summary.json`, `metrics.csv`,
`iasim.log` and periodic `snapshots/`.

Replay, metrics and save/load reproduce the same canonical state hash for the
same seed, actions and configuration. See
[docs/release-notes.md](docs/release-notes.md) for the v0.1.0 outcome and
[docs/performance.md](docs/performance.md) for the measured budgets.

## Configuration

`--config` loads a TOML file; every CLI flag overrides the file. Defaults and
the complete table live in [docs/configuration.md](docs/configuration.md).

```toml
[game]
seed = 42
max_agents = 2
tick_minutes = 5

[mcp]
host = "127.0.0.1"
port = 8765
```

Use `--host 0.0.0.0` only on a trusted LAN. The MCP transport is plaintext HTTP
without TLS in the MVP; `--dev-open` is restricted to loopback and only injects
the first slot token for development.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Useful checks: `python scripts/acceptance_checklist.py`,
`python scripts/three_day_scenario.py` and the tests in `tests/`.

## MVP scope and known limitations

v0.1.0 delivers F0/F1: procedural 80×40 island, survival, needs, base weather,
crafting, construction, combat, death and looting, local chat, alliances,
trade, perception/memory, MCP auth/actions/replay/metrics, the operator GUI and
the deterministic reference agent.

Not delivered in v0.1.0 (F2/F3): snow and seasons, passive fauna and fishing,
cooking, simple durability, probabilistic forecast, mouse support, advanced
debug console, and an integrated LLM agent or OpenAI-compatible comparison.

Known limitations:

- The windowed GUI and fullscreen need an interactive desktop; CI verifies the
  renderer and headless paths only.
- LAN clients need the per-slot token from `agents.json`; there is no TLS, so
  use a VPN or tunnel on untrusted networks.
- `--dev-open` is loopback-only and maps unauthenticated requests to slot 1.
- Font scaling is a window-level setting; the text renderer validates it but
  does not resize glyphs.

The SRS ([docs/SRS.md](docs/SRS.md)) is the requirements authority.
