"""Trade offer, acceptance, and decline resolvers with atomic swaps."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import TypeGuard

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, InventoryError, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.trades import (
    TRADE_RANGE,
    TradeLot,
    TradeOffer,
    TradeStatus,
    find_trade,
    replace_trade,
)
from iasim.domain.turns import ActionResolver, TurnEvent


class TradeOutcome(StrEnum):
    """Stable outcomes for the three trade actions."""

    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TRADE = "invalid_trade"
    MISSING_ITEMS = "missing_items"
    INVENTORY_FULL = "inventory_full"
    UNKNOWN_TRADE = "unknown_trade"
    ALREADY_RESOLVED = "already_resolved"
    EXPIRED = "expired"
    NOT_YOUR_TRADE = "not_your_trade"


def resolve_offer_trade(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Propose an item trade to a nearby living agent."""
    payload = action.payload_dict()
    target_id = payload.get("target_id")
    offer = payload.get("offer")
    request = payload.get("request")
    if not isinstance(target_id, str) or not target_id:
        return state, (_event(action, TradeOutcome.INVALID_TARGET),)
    if not _is_lot(offer) or not _is_lot(request):
        return state, (_event(action, TradeOutcome.INVALID_TRADE),)

    proposer = _find_agent(state, action.agent_id)
    if proposer is None:
        return state, (_event(action, TradeOutcome.UNKNOWN_AGENT),)
    target = _find_agent(state, AgentId(target_id))
    if target is None or target.agent_id == proposer.agent_id or not target.is_alive:
        return state, (_event(action, TradeOutcome.INVALID_TARGET),)
    if _distance(proposer, target) > TRADE_RANGE:
        return state, (_event(action, TradeOutcome.OUT_OF_RANGE),)

    rejection = _validate_give(proposer.inventory, offer)
    if rejection is not None:
        return state, (_event(action, rejection),)

    try:
        trade = TradeOffer.propose(
            proposer.agent_id,
            target.agent_id,
            action.tick,
            offer,
            request,
        )
    except ValueError:
        return state, (_event(action, TradeOutcome.INVALID_TRADE),)
    return (
        replace(state, trades=replace_trade(state.trades, trade)),
        (_event(action, TradeOutcome.OFFERED),),
    )


def resolve_accept_trade(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Execute one open offer atomically, or reject it without side effects."""
    trade_id = action.payload_dict().get("trade_id")
    if not isinstance(trade_id, str) or not trade_id:
        return state, (_event(action, TradeOutcome.UNKNOWN_TRADE),)

    recipient = _find_agent(state, action.agent_id)
    if recipient is None:
        return state, (_event(action, TradeOutcome.UNKNOWN_AGENT),)
    trade = find_trade(state.trades, trade_id)
    if trade is None or not trade.involves(recipient.agent_id):
        return state, (_event(action, TradeOutcome.UNKNOWN_TRADE),)
    if trade.status is TradeStatus.EXPIRED:
        return state, (_event(action, TradeOutcome.EXPIRED),)
    if not trade.is_open:
        return state, (_event(action, TradeOutcome.ALREADY_RESOLVED),)
    if trade.target_id != recipient.agent_id:
        return state, (_event(action, TradeOutcome.NOT_YOUR_TRADE),)
    if trade.is_expired_at(action.tick):
        return (
            replace(state, trades=replace_trade(state.trades, trade.expired(action.tick))),
            (_event(action, TradeOutcome.EXPIRED),),
        )

    proposer = _find_agent(state, trade.proposer_id)
    if proposer is None or not proposer.is_alive:
        return state, (_event(action, TradeOutcome.INVALID_TARGET),)
    if _distance(proposer, recipient) > TRADE_RANGE:
        return state, (_event(action, TradeOutcome.OUT_OF_RANGE),)

    rejection = _validate_give(proposer.inventory, trade.offer)
    if rejection is None:
        rejection = _validate_give(recipient.inventory, trade.request)
    if rejection is not None:
        return state, (_event(action, rejection),)

    try:
        proposer_inventory, recipient_inventory = _swap(proposer, recipient, trade)
    except InventoryError:
        return state, (_event(action, TradeOutcome.INVENTORY_FULL),)

    updated_agents = tuple(
        replace(
            agent,
            inventory=(
                proposer_inventory
                if agent.agent_id == proposer.agent_id
                else recipient_inventory
                if agent.agent_id == recipient.agent_id
                else agent.inventory
            ),
        )
        for agent in state.agents
    )
    return (
        replace(
            state,
            agents=updated_agents,
            trades=replace_trade(state.trades, trade.accepted(action.tick)),
        ),
        (_event(action, TradeOutcome.ACCEPTED),),
    )


def resolve_decline_trade(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Cancel one open offer as its recipient."""
    trade_id = action.payload_dict().get("trade_id")
    if not isinstance(trade_id, str) or not trade_id:
        return state, (_event(action, TradeOutcome.UNKNOWN_TRADE),)

    recipient = _find_agent(state, action.agent_id)
    if recipient is None:
        return state, (_event(action, TradeOutcome.UNKNOWN_AGENT),)
    trade = find_trade(state.trades, trade_id)
    if trade is None or not trade.involves(recipient.agent_id):
        return state, (_event(action, TradeOutcome.UNKNOWN_TRADE),)
    if trade.status is TradeStatus.EXPIRED:
        return state, (_event(action, TradeOutcome.EXPIRED),)
    if not trade.is_open:
        return state, (_event(action, TradeOutcome.ALREADY_RESOLVED),)
    if trade.target_id != recipient.agent_id:
        return state, (_event(action, TradeOutcome.NOT_YOUR_TRADE),)
    if trade.is_expired_at(action.tick):
        return (
            replace(state, trades=replace_trade(state.trades, trade.expired(action.tick))),
            (_event(action, TradeOutcome.EXPIRED),),
        )

    return (
        replace(state, trades=replace_trade(state.trades, trade.declined(action.tick))),
        (_event(action, TradeOutcome.DECLINED),),
    )


def trade_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the trade resolvers for a TurnEngine."""
    return {
        ActionKind.OFFER_TRADE: resolve_offer_trade,
        ActionKind.ACCEPT_TRADE: resolve_accept_trade,
        ActionKind.DECLINE_TRADE: resolve_decline_trade,
    }


def _swap(
    proposer: Agent,
    recipient: Agent,
    trade: TradeOffer,
) -> tuple[Inventory, Inventory]:
    """Return the final inventories of an atomic exchange.

    Both sides are validated and computed on copies before anything changes, so
    a failure leaves the session untouched.
    """
    proposer_after, given = _take(proposer.inventory, trade.offer)
    recipient_after, received = _take(recipient.inventory, trade.request)
    return _give(proposer_after, received), _give(recipient_after, given)


def _take(inventory: Inventory, lot: TradeLot) -> tuple[Inventory, tuple[ItemStack, ...]]:
    """Remove ``lot`` from ``inventory`` and return the stacks to hand over."""
    stacks: list[ItemStack] = []
    result = inventory
    for item_id, qty in lot:
        stack = result.stack_for(item_id)
        if stack is None or stack.quantity < qty:
            raise InventoryError(f"item {item_id!r} is not available in the quantity required")
        stacks.append(ItemStack(stack.definition, qty, charges=stack.charges))
        result = result.remove(item_id, qty)
    return result, tuple(stacks)


def _give(inventory: Inventory, stacks: tuple[ItemStack, ...]) -> Inventory:
    """Add received stacks, raising ``InventoryError`` when they do not fit."""
    result = inventory
    for stack in stacks:
        result = result.add(stack)
    return result


def _validate_give(inventory: Inventory, lot: TradeLot) -> TradeOutcome | None:
    """Return the rejection for a lot the holder cannot give, if any."""
    for item_id, qty in lot:
        stack = inventory.stack_for(item_id)
        if stack is None or stack.quantity < qty:
            return TradeOutcome.MISSING_ITEMS
    return None


def _is_lot(value: object) -> TypeGuard[TradeLot]:
    if not isinstance(value, tuple) or not value:
        return False
    return all(
        isinstance(entry, tuple)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and bool(entry[0])
        and type(entry[1]) is int
        and entry[1] > 0
        for entry in value
    )


def _distance(first: Agent, second: Agent) -> int:
    return max(
        abs(first.position.x - second.position.x),
        abs(first.position.y - second.position.y),
    )


def _event(action: Action, outcome: TradeOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
