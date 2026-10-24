# MVP acceptance audit — v0.1.0

Audit date: 2026-10-24 · Release: `v0.1.0` (annotated tag) · Protocol:
`iasim-mcp/1.0` · Version: `0.1.0`.

This is the closure audit for the F0/F1 MVP described in
[SRS §11.2](SRS.md). It records the epic status, the SRS acceptance criteria
evidence, the documented gaps and the remaining follow-ups. It does not claim
any F2/F3 work.

## Epic status

| Epic | Scope | Status |
|---|---|---|
| `iasim-tek` | F0 deterministic world and minimal loop | CLOSED |
| `iasim-6kr` | F1 survival, inventory, crafting, perception | CLOSED |
| `iasim-7a4` | F1 MCP 1.0 action surface and security | CLOSED |
| `iasim-591` | F1 social systems, combat, permanent death | CLOSED |
| `iasim-9i2` | F1 persistence, replay, metrics | CLOSED |
| `iasim-sv5` | F1 operator UI and observability | CLOSED |
| `iasim-qul` | F1 MVP validation and release | CLOSED after this audit |

All 15 `iasim-qul` children are closed; `iasim-qul.10` created the annotated
`v0.1.0` tag on release commit `7b8da11` and published it.

## Acceptance criteria evidence

| AC | Result | Evidence |
|---|---|---|
| AC-01 160×45 base layout | PASS | `tests/test_ui_layout.py` golden 160×45; acceptance `gui.base`. |
| AC-02 glyphs without tofu | PASS (renderer) | glyph/legend tests; real window is a manual residual. |
| AC-03 same seed/actions same hash | PASS | `tests/test_golden_seed.py` per-tick hashes. |
| AC-04 needs thresholds and death cause | PASS | `tests/test_needs.py`, `tests/test_status.py`. |
| AC-05 gather, craft spear, equip, attack | PASS | crafting/equipment/combat suites plus the three-day scenario. |
| AC-06 rain cools, fire/shelter mitigate | PASS | `tests/test_climate.py`. |
| AC-07 MCP join/observe/move/result | PASS | `tests/test_mcp_server.py`, `tests/test_mcp_integration.py`. |
| AC-08 stale/second action errors | PASS | stale-tick and ALREADY_ACTED tests. |
| AC-09 timeout and absence | PASS | `tests/test_timeouts.py`, `tests/test_mcp_integration.py`. |
| AC-10 atomic trade | PASS | `tests/test_trades.py`. |
| AC-11 kill, corpse, cause, loot | PASS | `tests/test_combat.py`, `tests/test_loot.py`, scenario. |
| AC-12 last death keeps server open | PASS | waiting/session tests; GUI `ESPERANDO AGENTES` checks. |
| AC-13 FOV blocking | PASS | `tests/test_tcod_fov.py`, `tests/test_climate.py`. |
| AC-14 memory persistence/staleness | PASS | `tests/test_memory.py`. |
| AC-15 save/load same hash | PASS | `tests/test_save_load.py`. |
| AC-16 replay same metrics/hash | PASS | `tests/test_replay.py`, `tests/test_golden_seed.py`, scenario. |
| AC-17 headless 1000 ticks, 8 agents | PASS (engine) | `tests/test_performance.py`; real `--headless` CLI smoke in acceptance. |
| AC-18 robustness to invalid input | PASS | MCP limits/security/malformed tests. |
| AC-19 keyboard-only F1–F10 | PARTIAL | F1–F8/F11 implemented and tested; SRS names F1–F10 but F9 is save and F10 has no documented view. |
| AC-20 reported mind/action visible | PASS (renderer) | mind/action panel tests; window visual is manual. |
| AC-21 sanitize/truncate text | PASS | chat/mind sanitization tests. |
| AC-22 loopback + token default | PASS | config/auth tests, acceptance harness. |
| AC-23 24×24 font and F6 legend | PASS (renderer) | F6 legend tests; font/window is manual. |
| AC-24 reference agent 500 ticks | PASS | real MCP 500-tick run documented in `iasim-qul.1`; default suite runs 500 contract + 40 real MCP ticks. |
| AC-25 summary.json + metrics.csv | PASS | `tests/test_export.py`, `tests/test_metrics.py`. |
| AC-26 debug injection replay + agent isolation | GAP | The operator debug console (F12) is not implemented in v0.1.0; it is outside the nine scoped qul children. |
| AC-27 F2 snow/forecast | NOT APPLICABLE | F2 feature, explicitly not delivered. |
| AC-28 LAN URL, warning, token, remote join | PASS (config) | acceptance harness LAN bind/health/auth; second physical host is a manual residual. |
| AC-29 disconnect removes ghost and frees slot | PASS | disconnect/slot tests, acceptance harness. |
| AC-30 GUI live agents, headless no window | PASS (renderer+CLI) | acceptance harness renders all views and starts real headless CLI; real window manual. |

## Remaining work

Follow-ups (already filed, not release blockers for the delivered F0/F1 scope):

- `iasim-145` — pass MCP request ids into the session action log (P2).
- `iasim-59d` — detect abrupt MCP transport loss without a session DELETE (P3).

Documented gaps/residuals:

- Operator debug console (`F12`, AC-26) is not part of the delivered MVP; it
  needs its own approved issue before implementation.
- Real tcod window, visual fullscreen and a second physical LAN host remain
  manual confirmations; the acceptance harness reports them as SKIP with
  automated evidence for the same paths.
- AC-19's F1–F10 wording is inconsistent with the documented views
  (F1–F8 plus F11); F9 is a save shortcut and F10 has no view in the SRS.

No F2/F3 issues were created.

## Release verification

- `pytest`: 787 passed, 1 skipped, 469 subtests.
- `ruff check`, `ruff format --check`, `mypy src`: clean.
- Core tick p95 17.48 ms (budget 50 ms); UI p95 12.33 ms (budget 33.33 ms).
- Three-day scenario: 864 ticks, death at 608, replay MATCH, final hash
  `8256d8aab6bf1a801124c80e2b01971ff84955473f32ad06fef32ff997a09855`.
- Acceptance harness: 28 PASS, 0 FAIL, 3 SKIP.
- Annotated tag `v0.1.0` on release commit `7b8da11`; package version `0.1.0`;
  protocol `iasim-mcp/1.0`.
