# Three-day two-agent scenario — iasim-qul.7

- Seed: 20261023
- Duration: 864 ticks (3 days, 288 ticks/day)
- Final hash: `8256d8aab6bf1a801124c80e2b01971ff84955473f32ad06fef32ff997a09855`
- Replay: MATCH

The scenario uses only the island's fresh water and 24 berries per agent (plus the crafted spear); no waterskin fixture is needed after the balance pass, and the waterskin charge capacity is now enforced.

## Scenario outcome

- Survivor: `ag_01`
- Casualty: `ag_02` at tick 608 (attack, killer ag_01)
- Alliance formed: True
- Corpse looted: True
- Chat messages: 1 · mind reports: 13

## Session metrics

| Metric | Value |
|---|---|
| survival_ticks | 1472 |
| actions_total | 1473 |
| actions_failed | 260 |
| messages_sent | 1 |
| alliances_formed | 1 |
| attacks_made | 12 |
| kills | 1 |
| mind_reports | 13 |
| exploration_pct | 0.4802 |
| resources_gathered | {} |
| items_crafted | {} |

## Casualty metrics

- Survival ticks: 608
- Cause of death: attack
- Killed by: ag_01
- Actions: 609

## Artifacts

`actions.jsonl`, `agents.json`, `events.jsonl`, `initial_snapshot.json`, `metrics.csv`, `replay.json`, `session.json`, `snapshots`, `summary.json`, `thoughts.jsonl`

The run directory, metrics, replay and hashes are deterministic for seed 20261023; rerun with `python scripts/three_day_scenario.py`.
