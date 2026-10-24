"""Performance budgets for the eight-agent MVP scenario (RF-1307).

Budgets from SRS RNF-02 and RNF-03:

- core tick: p95 < 50 ms with 8 agents on the 80x40 island, excluding agent
  decision latency;
- base UI render: stable at 30 FPS, i.e. p95 render time < 33.3 ms.

The headless run executes 1000 ticks with every agent submitting ``wait`` (the
cheapest valid primary action), so the measurement covers the engine, needs,
weather, memory, metrics, and hash work rather than transport overhead. The UI
measurement renders the full base screen 1000 times with the same live state.
Measured results are recorded in ``docs/performance.md`` and in the
iasim-qul.5 Beads journal.
"""

from __future__ import annotations

import gc
import math
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from iasim.app.session import GameSession
from iasim.domain.actions import Action, ActionKind
from iasim.domain.identifiers import AgentId
from iasim.domain.needs import apply_needs_tick as real_apply_needs_tick
from iasim.domain.session import SessionState
from iasim.domain.turns import ResolvedAction
from iasim.ui.layout import render_base_screen
from iasim.world.generation import generate_layout

CORE_P95_BUDGET_MS = 50.0
UI_P95_BUDGET_MS = 1000.0 / 30.0
TICKS = 1000
WARMUP_TICKS = 20
PERFORMANCE_SEED = 20261023
AGENT_COUNT = 8
_STABLE_NEEDS = {
    "health_centi": 10_000,
    "hunger_centi": 1_500,
    "thirst_centi": 1_500,
    "energy_centi": 8_000,
}


def _stabilized_needs(
    state: SessionState,
    resolved_actions: tuple[ResolvedAction, ...],
    ambient_temperature_centi: int = 2_200,
) -> SessionState:
    """Keep the eight agents alive so all 1000 ticks stay comparable.

    Needs normally evolve once per tick; the benchmark keeps the same agents
    alive by resetting them only when a need approaches a harmful level. That
    avoids adding a per-tick allocation that the production engine never pays.
    """
    evolved = real_apply_needs_tick(
        state,
        resolved_actions,
        ambient_temperature_centi=ambient_temperature_centi,
    )
    if not any(
        agent.attributes.hunger_centi > 4_000
        or agent.attributes.thirst_centi > 4_000
        or agent.attributes.energy_centi < 3_000
        or agent.attributes.health_centi < 9_000
        for agent in evolved.agents
        if agent.is_alive
    ):
        return evolved
    agents = tuple(
        replace(
            agent,
            attributes=replace(agent.attributes, **_STABLE_NEEDS),
        )
        for agent in evolved.agents
    )
    return replace(evolved, agents=agents)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _join_eight(session: GameSession) -> tuple[AgentId, ...]:
    agent_ids: list[AgentId] = []
    for slot in range(AGENT_COUNT):
        joined = session.join(f"Perf{slot + 1}", session.tokens[slot])
        if not joined.get("ok"):
            raise AssertionError(f"join failed for slot {slot}: {joined}")
        agent_ids.append(AgentId(str(joined["agent_id"])))
    return tuple(agent_ids)


class EightAgentPerformanceTests(unittest.TestCase):
    session: GameSession
    timings: list[float]
    agent_ids: tuple[AgentId, ...]

    @classmethod
    def setUpClass(cls) -> None:
        layout = generate_layout(PERFORMANCE_SEED, agent_count=AGENT_COUNT)
        cls.session = GameSession(
            PERFORMANCE_SEED,
            layout=layout,
            max_agents=AGENT_COUNT,
            turn_timeout_ms=60_000,
        )
        cls.agent_ids = _join_eight(cls.session)
        cls.timings = []
        with patch("iasim.app.session.apply_needs_tick", _stabilized_needs):
            for _ in range(WARMUP_TICKS):
                tick = cls.session.tick
                for agent_id in cls.agent_ids:
                    cls.session.submit_action(Action(agent_id, tick, ActionKind.WAIT))
            gc.collect()
            gc.disable()
            try:
                for _ in range(TICKS):
                    tick = cls.session.tick
                    started = time.perf_counter()
                    for agent_id in cls.agent_ids:
                        cls.session.submit_action(Action(agent_id, tick, ActionKind.WAIT))
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    cls.timings.append(elapsed_ms)
                    if cls.session.tick != tick + 1:
                        raise AssertionError(f"tick {tick} did not resolve with 8 agents")
            finally:
                gc.enable()

    def test_the_core_tick_p95_stays_within_the_srs_budget(self) -> None:
        p50 = _percentile(self.timings, 0.50)
        p95 = _percentile(self.timings, 0.95)
        p99 = _percentile(self.timings, 0.99)
        print(
            f"\nRNF-02 core tick: p50={p50:.2f} ms p95={p95:.2f} ms "
            f"p99={p99:.2f} ms budget={CORE_P95_BUDGET_MS:.1f} ms "
            f"({TICKS} ticks, {AGENT_COUNT} agents)"
        )

        self.assertEqual(len(self.timings), TICKS)
        self.assertEqual(len(self.agent_ids), AGENT_COUNT)
        self.assertEqual(len(self.session.state.agents), AGENT_COUNT)
        self.assertLess(
            p95,
            CORE_P95_BUDGET_MS,
            f"p95 tick {p95:.2f} ms exceeded the {CORE_P95_BUDGET_MS} ms budget",
        )

    def test_the_base_ui_render_meets_the_30_fps_budget(self) -> None:
        names = self.session.names_snapshot()
        mind_reports = self.session.mind_reports_snapshot()
        usage = self.session.usage_snapshot()
        timings: list[float] = []
        gc.collect()
        gc.disable()
        try:
            for _ in range(TICKS):
                started = time.perf_counter()
                screen = render_base_screen(
                    self.session.state,
                    names,
                    events=("perf",),
                    capacity=AGENT_COUNT,
                    mind_reports=mind_reports,
                    usage=usage,
                )
                timings.append((time.perf_counter() - started) * 1000.0)
        finally:
            gc.enable()
        p50 = _percentile(timings, 0.50)
        p95 = _percentile(timings, 0.95)
        print(
            f"\nRNF-03 UI render: p50={p50:.2f} ms p95={p95:.2f} ms "
            f"budget={UI_P95_BUDGET_MS:.2f} ms (30 FPS)"
        )

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertLess(
            p95,
            UI_P95_BUDGET_MS,
            f"p95 render {p95:.2f} ms exceeded the 30 FPS budget",
        )


if __name__ == "__main__":
    unittest.main()
