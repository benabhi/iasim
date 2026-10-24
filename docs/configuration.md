# Configuration — v0.1.0

IASim reads an optional TOML file with `--config PATH`. Every CLI flag overrides
the file, and the file overrides built-in defaults. Unknown keys are rejected.
The tables below match `src/iasim/config/models.py`; the SRS is the
requirements authority ([SRS §7.1](SRS.md)).

## Precedence

```text
built-in defaults  <  TOML file (--config)  <  CLI flags
```

Examples:

```bash
iasim --config config/iasim.toml --seed 42 --max-agents 2
iasim serve --headless --host 0.0.0.0 --port 8765
iasim --load runs/20261024/session.json --headless
iasim --replay runs/20261024/replay.json
```

## `[game]`

| Key | Default | CLI flag | Notes |
|---|---:|---|---|
| `seed` | random | `--seed` | Non-negative; generated and logged if omitted. |
| `headless` | `false` | `--headless` | Server only, no window. |
| `min_agents` | `1` | `--min-agents` | 1–8. |
| `max_agents` | `8` | `--max-agents` | 1–8; must be ≥ `min_agents`. |
| `tick_minutes` | `5` | `--tick-minutes` | Minutes of game time per tick. |
| `turn_timeout_ms` | `60000` | `--turn-timeout-ms` | Deadline starts with the first action of the tick. |
| `timeout_disconnects` | `3` | `--timeout-disconnects` | Consecutive timeouts before an agent becomes absent. |
| `allow_late_join` | `false` | — | Reserved; late joins remain disabled. |
| `pause_on_overlay` | `true` | — | Default pause behaviour in the UI. |
| `autosave_every_ticks` | `1000` | `--autosave-every`, `--no-autosave` | `0` disables autosave. |

`--agents N` sets both `min_agents` and `max_agents`; explicit `--min-agents` or
`--max-agents` wins for that field.

## `[world]`

| Key | Default | Notes |
|---|---:|---|
| `width` | `80` | MVP is fixed at 80. |
| `height` | `40` | MVP is fixed at 40. |
| `name` | `"isla_boscosa"` | Display name. |

## `[weather]`

| Key | Default | Notes |
|---|---:|---|
| `snow_enabled` | `false` | F2 feature; accepted for forward compatibility. |
| `season` | `"summer"` | F2 feature; accepted for forward compatibility. |
| `season_days` | `7` | F2 feature; accepted for forward compatibility. |
| `weather_min_ticks` | `12` | Minimum weather duration. |
| `weather_max_ticks` | `72` | Must be ≥ `weather_min_ticks`. |
| `forecast_enabled` | `true` | F2 feature; accepted for forward compatibility. |
| `forecast_horizon_ticks` | `6` | F2 feature; 0–6. |

Snow, seasons and forecast are **not implemented in v0.1.0**; the keys exist in
the MVP configuration contract for F2.

## `[mcp]`

| Key | Default | CLI flag | Notes |
|---|---:|---|---|
| `host` | `"127.0.0.1"` | `--host` | `0.0.0.0` or a LAN IP exposes plaintext HTTP. |
| `port` | `8765` | `--port` | 1–65535. |
| `require_token` | `true` | — | Tokens are required for agents. |
| `dev_open` | `false` | `--dev-open` | Loopback-only; injects slot 1 token for development. It must not be used on a LAN. |

## `[logs]`

| Key | Default | CLI flag | Notes |
|---|---:|---|---|
| `dir` | `"runs"` | `--log-dir` | Base directory; each run gets a timestamp-seed subdirectory. |
| `snapshot_every_ticks` | `100` | `--snapshot-every` | Snapshot cadence. |
| `export_csv` | `true` | — | Writes `metrics.csv` alongside `summary.json`. |

## `[ui]`

| Key | Default | Notes |
|---|---:|---|
| `language` | `"es"` | GUI text is Spanish. |
| `font_path` | `"assets/fonts/DejaVuSansMono.ttf"` | Window backend. |
| `font_width` | `12` | Window backend. |
| `font_height` | `24` | Window backend. |
| `palette` | `"default"` | Window palette name. |
| `map_zoom_font_width` | `24` | F6 window. |
| `map_zoom_font_height` | `24` | F6 window. |

Display settings changed at runtime (palette, scale, ticker, weather default,
confirmations, fullscreen) live in the presentation state for the session; they
are not written back to the TOML file in v0.1.0.

## `[debug]`

Operator-only; never exposed through MCP.

| Key | Default | Notes |
|---|---:|---|
| `enabled` | `false` | Debug console availability. |
| `confirm_destructive` | `true` | Confirmation for destructive commands. |

## `[usage]`

Optional USD pricing per model, used to estimate reported AI usage cost:

```toml
[usage.pricing."my-model"]
input_per_million_usd = 0.15
output_per_million_usd = 0.60
```

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Clean exit. |
| `1` | Configuration error. |
| `2` | World generation error. |
| `3` | MCP transport/port error. |
| `4` | Persistence error. |
| `5` | Internal error. |
