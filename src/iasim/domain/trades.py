"""Atomic item trade records between two agents.

A trade offer belongs to one proposer and one recipient, carries the items each
side gives, and expires a fixed number of ticks after it was made. Offers are
pure social state: they grant nothing until the recipient accepts, and the swap
is all-or-nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from iasim.domain.identifiers import AgentId, ItemId, validate_agent_id, validate_item_id

TRADE_RANGE = 2
TRADE_TTL_TICKS = 5

TradeLot = tuple[tuple[ItemId, int], ...]


class TradeStatus(StrEnum):
    """Lifecycle of one trade offer."""

    OPEN = "open"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


def trade_id_for(proposer: AgentId, target: AgentId, tick: int) -> str:
    """Return the deterministic identifier of one offer.

    An agent submits at most one primary action per tick, so the proposer,
    recipient, and tick already identify the offer uniquely.
    """
    return f"tr_{proposer}_{target}_{tick:06d}"


def parse_lot(entries: object) -> TradeLot | None:
    """Parse a wire lot into a canonical lot, or return ``None`` when invalid.

    Accepts a sequence of ``{"item_id": ..., "qty": ...}`` mappings, which is
    what the MCP surface receives, or ``(item_id, qty)`` pairs.
    """
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return None
    pairs: list[tuple[ItemId, int]] = []
    for entry in entries:
        if isinstance(entry, Mapping):
            item_id = entry.get("item_id")
            qty = entry.get("qty")
        elif isinstance(entry, tuple) and len(entry) == 2:
            item_id, qty = entry
        else:
            return None
        if not isinstance(item_id, str) or not item_id:
            return None
        if type(qty) is not int or qty < 1:
            return None
        try:
            validate_item_id(item_id)
        except ValueError:
            return None
        pairs.append((ItemId(item_id), qty))
    return _normalize_lot(pairs)


@dataclass(frozen=True, slots=True)
class TradeOffer:
    """One item trade proposed by ``proposer_id`` to ``target_id``.

    ``offer`` lists what the proposer gives and ``request`` what it wants in
    return. Both lots are sorted by item id and hold positive quantities.
    """

    trade_id: str
    proposer_id: AgentId
    target_id: AgentId
    offered_tick: int
    offer: TradeLot
    request: TradeLot
    status: TradeStatus = TradeStatus.OPEN
    resolved_tick: int | None = None

    def __post_init__(self) -> None:
        validate_agent_id(self.proposer_id)
        validate_agent_id(self.target_id)
        if self.proposer_id == self.target_id:
            raise ValueError("a trade cannot target its own proposer")
        expected_id = trade_id_for(self.proposer_id, self.target_id, self.offered_tick)
        if self.trade_id != expected_id:
            raise ValueError(f"invalid trade id {self.trade_id!r}; expected {expected_id!r}")
        if self.offered_tick < 0:
            raise ValueError("trade offer tick must be non-negative")
        _validate_lot(self.offer, "offer")
        _validate_lot(self.request, "request")
        if self.status is TradeStatus.OPEN:
            if self.resolved_tick is not None:
                raise ValueError("an open trade cannot be resolved")
        elif self.resolved_tick is None:
            raise ValueError("a closed trade requires a resolution tick")
        if self.resolved_tick is not None and self.resolved_tick < self.offered_tick:
            raise ValueError("a trade cannot resolve before it was offered")

    @classmethod
    def propose(
        cls,
        proposer: AgentId,
        target: AgentId,
        tick: int,
        offer: TradeLot,
        request: TradeLot,
    ) -> TradeOffer:
        """Return one open offer between two agents."""
        return cls(
            trade_id=trade_id_for(proposer, target, tick),
            proposer_id=proposer,
            target_id=target,
            offered_tick=tick,
            offer=offer,
            request=request,
        )

    @property
    def is_open(self) -> bool:
        """Return whether the recipient can still answer the offer."""
        return self.status is TradeStatus.OPEN

    @property
    def expires_at_tick(self) -> int:
        """Return the tick at which the offer is no longer valid."""
        return self.offered_tick + TRADE_TTL_TICKS

    def is_expired_at(self, tick: int) -> bool:
        """Return whether the offer must be considered expired at ``tick``."""
        return self.is_open and tick >= self.expires_at_tick

    def accepted(self, tick: int) -> TradeOffer:
        """Return the accepted record produced by the recipient."""
        return replace(self, status=TradeStatus.ACCEPTED, resolved_tick=tick)

    def declined(self, tick: int) -> TradeOffer:
        """Return the declined record produced by the recipient."""
        return replace(self, status=TradeStatus.DECLINED, resolved_tick=tick)

    def expired(self, tick: int) -> TradeOffer:
        """Return the expired record produced by the expiry pass."""
        return replace(self, status=TradeStatus.EXPIRED, resolved_tick=tick)

    def involves(self, agent_id: AgentId) -> bool:
        """Return whether ``agent_id`` is the proposer or the recipient."""
        return agent_id in (self.proposer_id, self.target_id)

    def as_observation(self) -> dict[str, object]:
        """Return a stable payload for the operator and the agents involved."""
        return {
            "trade_id": self.trade_id,
            "from": str(self.proposer_id),
            "to": str(self.target_id),
            "tick": self.offered_tick,
            "expires_at_tick": self.expires_at_tick,
            "offer": [{"item_id": item_id, "qty": qty} for item_id, qty in self.offer],
            "request": [{"item_id": item_id, "qty": qty} for item_id, qty in self.request],
            "status": self.status.value,
        }


def find_trade(trades: Iterable[TradeOffer], trade_id: str) -> TradeOffer | None:
    """Return the offer with ``trade_id``, if it exists."""
    return next((trade for trade in trades if trade.trade_id == trade_id), None)


def open_trades(trades: Iterable[TradeOffer], agent_id: AgentId) -> tuple[TradeOffer, ...]:
    """Return the open offers that involve ``agent_id``, sorted by id."""
    return tuple(
        trade
        for trade in sorted(trades, key=lambda item: item.trade_id)
        if trade.is_open and trade.involves(agent_id)
    )


def replace_trade(trades: Iterable[TradeOffer], trade: TradeOffer) -> tuple[TradeOffer, ...]:
    """Insert or update one offer, keeping the tuple sorted by trade id."""
    kept = tuple(existing for existing in trades if existing.trade_id != trade.trade_id)
    return tuple(sorted((*kept, trade), key=lambda item: item.trade_id))


def expire_trades(trades: Iterable[TradeOffer], tick: int) -> tuple[TradeOffer, ...]:
    """Return the offers with every expired one marked, keeping id order."""
    return tuple(
        sorted(
            (trade.expired(tick) if trade.is_expired_at(tick) else trade for trade in trades),
            key=lambda item: item.trade_id,
        )
    )


def drop_agent_trades(trades: Iterable[TradeOffer], agent_id: AgentId) -> tuple[TradeOffer, ...]:
    """Return the offers that do not involve a departed agent."""
    return tuple(trade for trade in trades if not trade.involves(agent_id))


def drop_departed_trades(
    trades: Iterable[TradeOffer],
    present_ids: Iterable[AgentId],
) -> tuple[TradeOffer, ...]:
    """Return the offers whose two agents are still in the session."""
    present = set(present_ids)
    return tuple(
        trade for trade in trades if trade.proposer_id in present and trade.target_id in present
    )


def _normalize_lot(pairs: Iterable[tuple[ItemId, int]]) -> TradeLot | None:
    normalized = tuple(sorted(pairs, key=lambda pair: str(pair[0])))
    if not normalized:
        return None
    item_ids = [item_id for item_id, _ in normalized]
    if len(item_ids) != len(set(item_ids)):
        return None
    return normalized


def _validate_lot(lot: TradeLot, name: str) -> None:
    if not lot:
        raise ValueError(f"{name} lot must not be empty")
    item_ids: list[ItemId] = []
    for item_id, qty in lot:
        validate_item_id(item_id)
        if type(qty) is not int or qty < 1:
            raise ValueError(f"{name} lot quantities must be positive integers")
        item_ids.append(item_id)
    if len(item_ids) != len(set(item_ids)):
        raise ValueError(f"{name} lot must not repeat an item")
    if item_ids != sorted(item_ids, key=str):
        raise ValueError(f"{name} lot must be sorted by item id")
