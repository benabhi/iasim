# Performance baseline (RF-1307)

Budgets come from the SRS (RNF-02 and RNF-03):

| Metric | Budget |
|---|---|
| Core tick, 8 agents on the 80x40 island, agent latency excluded | p95 < 50 ms |
| Base UI render, 8 agents | p95 < 33.33 ms (30 FPS) |

`tests/test_performance.py` measures both budgets and fails when they are
exceeded. The core run joins eight agents on seed `20261023`, submits `wait`
for every agent on 1020 ticks (20 warm-up ticks excluded), and times the
submission that resolves the turn. Needs evolution runs normally, but hunger,
thirst, energy, and health are reset only when a need approaches a harmful
level so the same eight agents stay comparable for the whole run. The UI run
renders the full 160x45 base screen 1000 times against the final live state.
Garbage collection is collected and disabled around the timed loops so the
numbers measure computation rather than GC pause scheduling; GC is re-enabled
in a `finally` block.

## Latest local baseline

Measured on 2026-10-24 on the development machine (Windows 11, Python 3.12,
`.venv`), with `pytest tests/test_performance.py -q -s`:

| Metric | p50 | p95 | p99 | Budget |
|---|---|---|---|---|
| Core tick (1000 ticks, 8 agents) | 15.36 ms | 17.48 ms | 18.34 ms | 50 ms |
| Base UI render (1000 frames, 8 agents) | 11.89 ms | 12.33 ms | — | 33.33 ms |

The run passed both budgets. Results are environment-dependent; rerun the test
and update this table (and the iasim-qul.5 Beads journal) after a performance
change. A budget failure is a release blocker for `v0.1.0`.

## Optimizations made while adding the test

- Cached the libtcod transparency array per immutable `WorldMap` instead of
  rebuilding it for every agent FOV computation.
- Indexed resource nodes by position once per tick in `_update_memory_locked`
  instead of scanning every resource node for every visible cell.
- Reused blank `Cell` instances in `_Canvas` initialization and full-screen
  fills instead of constructing 7200 cells twice per rendered frame.
