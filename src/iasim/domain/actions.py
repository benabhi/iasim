"""Primary agent actions and their deterministic resolution order."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iasim.domain.identifiers import AgentId, validate_agent_id


class ActionKind(StrEnum):
    """Primary action categories in SRS section 3.2 resolution order."""

    MOVE = "move"
    MOVE_TO = "move_to"
    GATHER = "gather"
    PICKUP = "pickup"
    DROP = "drop"
    EAT = "eat"
    DRINK = "drink"
    FILL = "fill"
    CRAFT = "craft"
    BUILD = "build"
    USE_ITEM = "use_item"
    OFFER_TRADE = "offer_trade"
    ACCEPT_TRADE = "accept_trade"
    DECLINE_TRADE = "decline_trade"
    OFFER_ALLIANCE = "offer_alliance"
    ACCEPT_ALLIANCE = "accept_alliance"
    BREAK_ALLIANCE = "break_alliance"
    LOOT = "loot"
    ATTACK = "attack"
    THROW = "throw"
    FLEE = "flee"
    WAIT = "wait"
    REST = "rest"
    SLEEP = "sleep"

    @property
    def order(self) -> int:
        """Return the stable resolution rank of the action category."""
        return _ACTION_ORDER[self]


# SRS section 3.2: movement, gathering, crafting, building, item use, trade, combat.
# Item interaction actions share the item-use rank so enumeration order cannot change
# the deterministic resolution order. Alliance declarations share the trade rank so
# social state settles before combat resolves in the same tick.
_ACTION_ORDER: dict[ActionKind, int] = {
    ActionKind.MOVE: 0,
    ActionKind.MOVE_TO: 0,
    ActionKind.GATHER: 1,
    ActionKind.CRAFT: 2,
    ActionKind.BUILD: 3,
    ActionKind.PICKUP: 4,
    ActionKind.DROP: 4,
    ActionKind.EAT: 4,
    ActionKind.DRINK: 4,
    ActionKind.FILL: 4,
    ActionKind.USE_ITEM: 4,
    ActionKind.LOOT: 4,
    ActionKind.OFFER_TRADE: 5,
    ActionKind.ACCEPT_TRADE: 5,
    ActionKind.DECLINE_TRADE: 5,
    ActionKind.OFFER_ALLIANCE: 5,
    ActionKind.ACCEPT_ALLIANCE: 5,
    ActionKind.BREAK_ALLIANCE: 5,
    ActionKind.ATTACK: 6,
    ActionKind.THROW: 6,
    ActionKind.FLEE: 6,
    ActionKind.WAIT: 7,
    ActionKind.REST: 7,
    ActionKind.SLEEP: 7,
}


@dataclass(frozen=True, slots=True)
class Action:
    """A primary action submitted for one agent and one tick."""

    agent_id: AgentId
    tick: int
    kind: ActionKind
    payload: tuple[tuple[str, object], ...] = ()
    request_id: str | None = None

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        if self.tick < 0:
            raise ValueError(f"tick must be non-negative, got {self.tick}")
        if not isinstance(self.kind, ActionKind):
            raise ValueError(f"kind must be an ActionKind, got {self.kind!r}")
        keys = [key for key, _ in self.payload]
        if len(keys) != len(set(keys)):
            raise ValueError("action payload keys must be unique")
        if self.request_id is not None and not self.request_id:
            raise ValueError("request_id must not be empty when provided")

    def payload_dict(self) -> dict[str, object]:
        """Return the payload as a dictionary for resolvers."""
        return dict(self.payload)
