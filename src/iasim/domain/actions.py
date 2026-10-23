"""Primary agent actions and their deterministic resolution order."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iasim.domain.identifiers import AgentId, validate_agent_id


class ActionKind(StrEnum):
    """Primary action categories in SRS section 3.2 resolution order."""

    MOVE = "move"
    GATHER = "gather"
    CRAFT = "craft"
    BUILD = "build"
    USE_ITEM = "use_item"
    TRADE = "trade"
    ATTACK = "attack"
    WAIT = "wait"

    @property
    def order(self) -> int:
        """Return the stable resolution rank of the action category."""
        return _ACTION_ORDER[self]


_ACTION_ORDER: dict[ActionKind, int] = {kind: index for index, kind in enumerate(ActionKind)}


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
