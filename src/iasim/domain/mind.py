"""Operator-facing, untrusted mind reports from external agents."""

from __future__ import annotations

from dataclasses import dataclass

from iasim.domain.identifiers import AgentId

MAX_INTENT_LENGTH = 160
MAX_THOUGHT_LENGTH = 500
MAX_PLAN_LENGTH = 300


@dataclass(frozen=True, slots=True)
class MindReport:
    """One sanitized report of an agent's intent, thought, and optional plan."""

    agent_id: AgentId
    tick: int
    intent: str
    thought: str
    plan: str | None = None
    confidence: int | None = None

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("mind report tick must be non-negative")
        if not self.intent or not self.thought:
            raise ValueError("mind report intent and thought must not be empty")
        if len(self.intent) > MAX_INTENT_LENGTH:
            raise ValueError("mind report intent is too long")
        if len(self.thought) > MAX_THOUGHT_LENGTH:
            raise ValueError("mind report thought is too long")
        if self.plan is not None and len(self.plan) > MAX_PLAN_LENGTH:
            raise ValueError("mind report plan is too long")
        if self.confidence is not None and not 0 <= self.confidence <= 100:
            raise ValueError("mind report confidence must be within [0, 100]")

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation for the UI and log."""
        return {
            "agent_id": self.agent_id,
            "tick": self.tick,
            "intent": self.intent,
            "thought": self.thought,
            "plan": self.plan,
            "confidence": self.confidence,
        }

    def as_log_record(self, schema_version: str) -> dict[str, object]:
        """Return one thoughts.jsonl record."""
        return {
            "schema_version": schema_version,
            "event": "mind_report",
            **self.as_dict(),
        }
