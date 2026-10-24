# MVP balance notes — iasim-qul.8

Source of truth: `docs/SRS.md` sections 3.4–3.10 and 11.2. The three-day
scenario (`python scripts/three_day_scenario.py`) is the balance probe.

## Audit results

- **Survival:** hunger rises ~0.35/tick and thirst ~0.60/tick. Provided the
  agent reaches fresh water and eats berries, 24 berries and no waterskin are
  enough for 864 ticks; the scenario survives to the forced combat with both
  agents alive at the start of day 3. No unavoidable death was found.
- **Combat:** a stone spear deals 7 + floor(5/2) ± 1 damage with a 0.65 hit
  chance at adjacency; the scenario's 100-health victim dies after 12 attacks
  in about 50 ticks. Fists (2 damage) remain a viable but slow alternative. The
  documented SRS damage values (fists 2, spear 7, axe 6) are unchanged.
- **Crafting and resources:** the level-1 path (`sharp_stone` → `stone_spear`)
  needs only stone, fiber, and wood; `camp_kit` and `workbench_kit` need only
  stone and wood, so the level-2 workbench station is reachable without
  circular requirements. No resource dead end was found.
- **Exploit fixed:** waterskins accepted arbitrary charge counts (the scenario
  previously needed a 200-charge fixture to survive). `ItemDefinition` now
  carries the catalog `water_charges` capacity and `ItemStack` rejects charges
  above `water_capacity × quantity`, so an odre cannot hold more than its three
  documented charges. The scenario now drinks from the island's fresh water
  instead of relying on an oversized waterskin.

## Changes

- `src/iasim/domain/items.py`: new `water_capacity` field and charge validation.
- `src/iasim/crafting/catalog.py`: passes the catalog `water_charges` value into
  the item definition.
- `src/iasim/scenario.py`: removes the 200-charge fixture, lowers the berry
  provision to 24, and walks to fresh water when thirsty.
- `docs/SRS.md`: item table records that the waterskin capacity is enforced.
- Golden scenario hash updated to
  `8256d8aab6bf1a801124c80e2b01971ff84955473f32ad06fef32ff997a09855`; death still
  occurs at tick 608 and replay matches.

## Still open for later phases

- Longer multi-seed survival and combat tuning belongs to the F2 benchmark
  harness (RF-1308/RF-1309); the MVP keeps the SRS rates.
- Gathering/crafting interactions are not exercised by the scripted scenario;
  they are covered by the unit suites and the reference agent.
