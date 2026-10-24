"""Social event ledger for messages, alliances, trades, and betrayals.

The ledger is observability state, not simulation state: it never feeds back
into the deterministic rules and is not part of the canonical state hash. It
accumulates structured events so the operator, the session summary, and the
JSONL logs (later) can report per-agent and per-session social metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from iasim.domain.actions import ActionKind
from iasim.domain.alliance_actions import AllianceOutcome
from iasim.domain.alliances import BETRAYAL
from iasim.domain.identifiers import AgentId
from iasim.domain.trade_actions import TradeOutcome


class SocialEventKind(StrEnum):
    """Social facts worth counting in the session metrics."""

    MESSAGE = "message"
    ALLIANCE_OFFERED = "alliance_offered"
    ALLIANCE_FORMED = "alliance_formed"
    ALLIANCE_BROKEN = "alliance_broken"
    ALLIANCE_WITHDRAWN = "alliance_withdrawn"
    ALLIANCE_DECLINED = "alliance_declined"
    TRADE_OFFERED = "trade_offered"
    TRADE_COMPLETED = "trade_completed"
    TRADE_DECLINED = "trade_declined"
    BETRAYAL = "betrayal"


COUNTER_BY_KIND: dict[SocialEventKind, str] = {
    SocialEventKind.MESSAGE: "messages_sent",
    SocialEventKind.ALLIANCE_OFFERED: "alliances_offered",
    SocialEventKind.ALLIANCE_FORMED: "alliances_formed",
    SocialEventKind.ALLIANCE_BROKEN: "alliances_broken",
    SocialEventKind.ALLIANCE_WITHDRAWN: "alliances_withdrawn",
    SocialEventKind.ALLIANCE_DECLINED: "alliances_declined",
    SocialEventKind.TRADE_OFFERED: "trades_offered",
    SocialEventKind.TRADE_COMPLETED: "trades_completed",
    SocialEventKind.TRADE_DECLINED: "trades_declined",
    SocialEventKind.BETRAYAL: "betrayals",
}

SOCIAL_COUNTERS: tuple[str, ...] = tuple(dict.fromkeys(COUNTER_BY_KIND.values()))

# Turn outcomes that carry a social fact, keyed by (action kind, outcome).
_SOCIAL_OUTCOMES: dict[tuple[str, str], SocialEventKind] = {
    (ActionKind.OFFER_ALLIANCE.value, AllianceOutcome.OFFERED.value): (
        SocialEventKind.ALLIANCE_OFFERED
    ),
    (ActionKind.ACCEPT_ALLIANCE.value, AllianceOutcome.ACCEPTED.value): (
        SocialEventKind.ALLIANCE_FORMED
    ),
    (ActionKind.BREAK_ALLIANCE.value, AllianceOutcome.BROKEN.value): (
        SocialEventKind.ALLIANCE_BROKEN
    ),
    (ActionKind.BREAK_ALLIANCE.value, AllianceOutcome.WITHDRAWN.value): (
        SocialEventKind.ALLIANCE_WITHDRAWN
    ),
    (ActionKind.BREAK_ALLIANCE.value, AllianceOutcome.DECLINED.value): (
        SocialEventKind.ALLIANCE_DECLINED
    ),
    (ActionKind.OFFER_TRADE.value, TradeOutcome.OFFERED.value): (SocialEventKind.TRADE_OFFERED),
    (ActionKind.ACCEPT_TRADE.value, TradeOutcome.ACCEPTED.value): (SocialEventKind.TRADE_COMPLETED),
    (ActionKind.DECLINE_TRADE.value, TradeOutcome.DECLINED.value): (SocialEventKind.TRADE_DECLINED),
    # Combat emits a BETRAYAL annotation before or after the hit outcome; the
    # annotation never replaces the primary action result.
    (ActionKind.ATTACK.value, BETRAYAL): SocialEventKind.BETRAYAL,
    (ActionKind.THROW.value, BETRAYAL): SocialEventKind.BETRAYAL,
}


@dataclass(frozen=True, slots=True)
class SocialEvent:
    """One social fact attributed to the acting agent."""

    tick: int
    kind: SocialEventKind
    agent_id: AgentId
    target_id: AgentId | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation for logs and the operator UI."""
        return {
            "tick": self.tick,
            "kind": self.kind.value,
            "agent_id": str(self.agent_id),
            "target_id": None if self.target_id is None else str(self.target_id),
        }


def kind_for_outcome(action_kind: str, outcome: str) -> SocialEventKind | None:
    """Return the social event carried by one turn outcome, if any."""
    return _SOCIAL_OUTCOMES.get((action_kind, outcome))


def empty_counters() -> dict[str, int]:
    """Return one counter slot for every social metric."""
    return dict.fromkeys(SOCIAL_COUNTERS, 0)


class SocialLedger:
    """Per-agent and per-session counters plus the ordered social event log."""

    def __init__(self) -> None:
        self._events: list[SocialEvent] = []
        self._session: dict[str, int] = empty_counters()
        self._agents: dict[AgentId, dict[str, int]] = {}

    def record(self, event: SocialEvent) -> None:
        """Accumulate one social event in the session and its agent."""
        counter = COUNTER_BY_KIND[event.kind]
        self._events.append(event)
        self._session[counter] += 1
        counters = self._agents.setdefault(event.agent_id, empty_counters())
        counters[counter] += 1

    def record_outcome(
        self,
        *,
        tick: int,
        agent_id: AgentId,
        action_kind: str,
        outcome: str,
        target_id: AgentId | None = None,
    ) -> SocialEvent | None:
        """Record a social event for one turn outcome when it carries one."""
        kind = kind_for_outcome(action_kind, outcome)
        if kind is None:
            return None
        event = SocialEvent(tick, kind, agent_id, target_id)
        self.record(event)
        return event

    @property
    def events(self) -> tuple[SocialEvent, ...]:
        """Return the social events in resolution order."""
        return tuple(self._events)

    def snapshot(self) -> dict[str, Any]:
        """Return the counters per session and per agent."""
        return {
            "session": dict(self._session),
            "agents": {
                str(agent_id): dict(counters)
                for agent_id, counters in sorted(
                    self._agents.items(),
                    key=lambda entry: str(entry[0]),
                )
            },
        }

    def counts_by_kind(self) -> dict[str, int]:
        """Return how many events of each kind were recorded."""
        counts = dict.fromkeys((kind.value for kind in SocialEventKind), 0)
        for event in self._events:
            counts[event.kind.value] += 1
        return counts
