"""Declarative alliances between external agents.

Alliances are pure social state: they never prevent attacks, never force
cooperation, and carry no numeric reputation. A pair of agents owns at most one
alliance record, identified deterministically by the sorted pair of agent ids,
so the record is stable across saves, replays, and state hashes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from iasim.domain.chat import CHAT_RADIUS, within_chat_radius
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, validate_agent_id

# Alliances have no distance rule in the SRS; the social radius (SRS 3.9) is
# reused so proposing and accepting require the same closeness as talking.
ALLIANCE_RADIUS = CHAT_RADIUS

# Outcome annotation emitted by combat when an agent attacks an ally (RF-806).
BETRAYAL = "betrayal"


class AllianceStatus(StrEnum):
    """Latest known state of the alliance between two agents."""

    PENDING = "pending"
    ACTIVE = "active"
    BROKEN = "broken"


def alliance_id_for(first: AgentId, second: AgentId) -> str:
    """Return the deterministic identifier of the alliance between two agents."""
    low, high = sorted((str(first), str(second)))
    return f"al_{low}_{high}"


def within_alliance_radius(origin: Position, target: Position) -> bool:
    """Return whether two agents are close enough to propose or accept."""
    return within_chat_radius(origin, target)


@dataclass(frozen=True, slots=True)
class Alliance:
    """One alliance record shared by two agents.

    ``status`` is the latest known state: ``pending`` while an offer waits,
    ``active`` after acceptance, and ``broken`` after a break or a withdrawal.
    A broken record is kept while both agents remain in the session so the
    operator can still see what happened; a new offer replaces it.
    """

    alliance_id: str
    members: tuple[AgentId, AgentId]
    status: AllianceStatus
    proposed_by: AgentId
    offered_tick: int
    accepted_tick: int | None = None
    broken_tick: int | None = None

    def __post_init__(self) -> None:
        if len(self.members) != 2:
            raise ValueError("an alliance must have exactly two members")
        for member in self.members:
            validate_agent_id(member)
        first, second = self.members
        if first == second:
            raise ValueError("an alliance cannot pair an agent with itself")
        if str(first) > str(second):
            raise ValueError("alliance members must be sorted by agent id")
        if self.alliance_id != alliance_id_for(first, second):
            raise ValueError(
                f"invalid alliance id {self.alliance_id!r}; "
                f"expected {alliance_id_for(first, second)!r}"
            )
        if self.proposed_by not in self.members:
            raise ValueError("the proposer must be an alliance member")
        if self.offered_tick < 0:
            raise ValueError("alliance offer tick must be non-negative")
        if self.accepted_tick is not None and self.accepted_tick < self.offered_tick:
            raise ValueError("alliance acceptance cannot predate the offer")
        if self.broken_tick is not None and self.broken_tick < self.offered_tick:
            raise ValueError("alliance break cannot predate the offer")
        if self.status is AllianceStatus.PENDING:
            if self.accepted_tick is not None or self.broken_tick is not None:
                raise ValueError("a pending alliance cannot be accepted or broken")
        elif self.status is AllianceStatus.ACTIVE:
            if self.accepted_tick is None:
                raise ValueError("an active alliance requires an acceptance tick")
            if self.broken_tick is not None:
                raise ValueError("an active alliance cannot be broken")
        elif self.broken_tick is None:
            raise ValueError("a broken alliance requires a break tick")

    @classmethod
    def propose(cls, proposer: AgentId, target: AgentId, tick: int) -> Alliance:
        """Return a pending offer from ``proposer`` to ``target``."""
        first, second = sorted((proposer, target))
        return cls(
            alliance_id=alliance_id_for(proposer, target),
            members=(first, second),
            status=AllianceStatus.PENDING,
            proposed_by=proposer,
            offered_tick=tick,
        )

    @property
    def is_pending(self) -> bool:
        """Return whether the offer still waits for an answer."""
        return self.status is AllianceStatus.PENDING

    @property
    def is_active(self) -> bool:
        """Return whether both agents currently declare the alliance."""
        return self.status is AllianceStatus.ACTIVE

    @property
    def is_broken(self) -> bool:
        """Return whether the alliance was broken, withdrawn, or declined."""
        return self.status is AllianceStatus.BROKEN

    def accepted(self, tick: int) -> Alliance:
        """Return the active record produced by accepting the offer."""
        return replace(
            self,
            status=AllianceStatus.ACTIVE,
            accepted_tick=tick,
            broken_tick=None,
        )

    def ended(self, tick: int) -> Alliance:
        """Return the broken record produced by a break or a withdrawal."""
        return replace(
            self,
            status=AllianceStatus.BROKEN,
            broken_tick=tick,
        )

    def involves(self, agent_id: AgentId) -> bool:
        """Return whether ``agent_id`` is one of the two members."""
        return agent_id in self.members

    def other_member(self, agent_id: AgentId) -> AgentId:
        """Return the member paired with ``agent_id``."""
        if not self.involves(agent_id):
            raise ValueError(f"Agent {agent_id!r} is not part of alliance {self.alliance_id!r}")
        return self.members[1] if self.members[0] == agent_id else self.members[0]

    def as_observation(self) -> dict[str, object]:
        """Return a stable payload for the operator and the agents involved."""
        return {
            "alliance_id": self.alliance_id,
            "members": [str(member) for member in self.members],
            "status": self.status.value,
            "proposed_by": str(self.proposed_by),
            "offered_tick": self.offered_tick,
            "accepted_tick": self.accepted_tick,
            "broken_tick": self.broken_tick,
        }


def alliance_between(
    alliances: Iterable[Alliance],
    first: AgentId,
    second: AgentId,
) -> Alliance | None:
    """Return the record shared by two agents, if any."""
    alliance_id = alliance_id_for(first, second)
    return next(
        (alliance for alliance in alliances if alliance.alliance_id == alliance_id),
        None,
    )


def active_alliance(
    alliances: Iterable[Alliance],
    first: AgentId,
    second: AgentId,
) -> Alliance | None:
    """Return the accepted alliance between two agents, if any."""
    alliance = alliance_between(alliances, first, second)
    return alliance if alliance is not None and alliance.is_active else None


def is_allied(alliances: Iterable[Alliance], first: AgentId, second: AgentId) -> bool:
    """Return whether two agents currently declare an active alliance."""
    return active_alliance(alliances, first, second) is not None


def active_alliances(
    alliances: Iterable[Alliance],
    agent_id: AgentId,
) -> tuple[Alliance, ...]:
    """Return the accepted alliances that involve ``agent_id``, sorted by id."""
    return tuple(
        alliance
        for alliance in sorted(alliances, key=lambda item: item.alliance_id)
        if alliance.is_active and alliance.involves(agent_id)
    )


def pending_offers(
    alliances: Iterable[Alliance],
    agent_id: AgentId,
) -> tuple[Alliance, ...]:
    """Return the pending offers that involve ``agent_id``, sorted by id."""
    return tuple(
        alliance
        for alliance in sorted(alliances, key=lambda item: item.alliance_id)
        if alliance.is_pending and alliance.involves(agent_id)
    )


def replace_alliance(
    alliances: Iterable[Alliance],
    alliance: Alliance,
) -> tuple[Alliance, ...]:
    """Insert or update one record, keeping the tuple sorted by alliance id."""
    kept = tuple(existing for existing in alliances if existing.alliance_id != alliance.alliance_id)
    return tuple(sorted((*kept, alliance), key=lambda item: item.alliance_id))


def drop_agent_alliances(
    alliances: Iterable[Alliance],
    agent_id: AgentId,
) -> tuple[Alliance, ...]:
    """Return the records that do not involve a departed agent."""
    return tuple(alliance for alliance in alliances if not alliance.involves(agent_id))


def drop_departed_alliances(
    alliances: Iterable[Alliance],
    present_ids: Iterable[AgentId],
) -> tuple[Alliance, ...]:
    """Return the records whose two members are still in the session."""
    present = set(present_ids)
    return tuple(
        alliance for alliance in alliances if all(member in present for member in alliance.members)
    )
