"""Local chat messages and untrusted text sanitization."""

from __future__ import annotations

import re
from dataclasses import dataclass

from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId

CHAT_RADIUS = 8
MAX_CHAT_MESSAGE_LENGTH = 280
_ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def within_chat_radius(origin: Position, target: Position) -> bool:
    """Return whether ``target`` is within the Chebyshev chat radius."""
    return max(abs(origin.x - target.x), abs(origin.y - target.y)) <= CHAT_RADIUS


def sanitize_chat_text(value: str) -> str:
    """Remove ANSI/control sequences and collapse chat text to one line."""
    without_ansi = _ANSI_PATTERN.sub("", value)
    printable = "".join(character if character.isprintable() else " " for character in without_ansi)
    return " ".join(printable.split())


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A sanitized local message queued for next-tick delivery."""

    sender_id: AgentId
    recipients: tuple[AgentId, ...]
    text: str
    sent_tick: int
    deliver_tick: int
    target_id: AgentId | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("chat text must not be empty")
        if self.sent_tick < 0 or self.deliver_tick <= self.sent_tick:
            raise ValueError("chat delivery must be after the sending tick")
        if tuple(sorted(self.recipients)) != self.recipients:
            raise ValueError("chat recipients must be sorted and stable")
        if len(self.recipients) != len(set(self.recipients)):
            raise ValueError("chat recipients must not contain duplicates")

    def as_observation(self) -> dict[str, object]:
        """Return the perception payload shown to one recipient."""
        return {
            "from": self.sender_id,
            "tick": self.sent_tick,
            "text": self.text,
        }
