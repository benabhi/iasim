"""Minimal MCP server exposing the IASim session."""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from iasim.app.session import SCHEMA_VERSION, GameSession
from iasim.config import is_loopback_host
from iasim.domain.identifiers import AgentId
from iasim.domain.items import EquipSlot
from iasim.mcp.idempotency import MAX_REQUEST_ID_LENGTH, RequestCache, RequestSignature
from iasim.mcp.limits import MAX_TEXT_FIELD_LENGTH, LimitKind, RateLimiter
from iasim.mcp.protocol import PROTOCOL_VERSION
from iasim.mcp.schemas import PositiveQuantity, RequestId, Tick, TimeoutMillis, TradeItem

DEFAULT_RESOURCE_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_ISSUER_URL = "http://127.0.0.1:8765"
AUTH_SCOPE = "iasim:agent"
LAN_WARNING = (
    "MCP is exposed beyond loopback over plaintext HTTP. "
    "Use bearer tokens only on a trusted LAN; use a VPN or tunnel for untrusted networks."
)


def server_connection_info(host: str, port: int) -> dict[str, Any]:
    """Return advertised endpoints and a LAN exposure warning for ``host``/``port``."""
    advertised_host = _advertised_host(host)
    mcp_url = f"http://{advertised_host}:{port}/mcp"
    issuer_url = f"http://{advertised_host}:{port}"
    loopback = is_loopback_host(host)
    return {
        "host": host,
        "port": port,
        "advertised_host": advertised_host,
        "mcp_url": mcp_url,
        "issuer_url": issuer_url,
        "loopback": loopback,
        "warning": None if loopback else LAN_WARNING,
    }


def _advertised_host(host: str) -> str:
    normalized = host.strip()
    if normalized in {"0.0.0.0", "::"}:
        return _local_ipv4() or "127.0.0.1"
    return normalized or "127.0.0.1"


def _local_ipv4() -> str | None:
    try:
        addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    for info in addresses:
        address = str(info[4][0])
        if not is_loopback_host(address):
            return address
    return None


class SessionTokenVerifier:
    """Validate per-slot session tokens without an external OAuth server."""

    def __init__(self, session: GameSession) -> None:
        self._session = session

    async def verify_token(self, token: str) -> AccessToken | None:
        agent_id = self._session.agent_id_for_token(token)
        if agent_id is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(agent_id),
            scopes=[AUTH_SCOPE],
            resource=None,
        )


def create_server(
    session: GameSession,
    *,
    resource_url: str = DEFAULT_RESOURCE_URL,
    issuer_url: str = DEFAULT_ISSUER_URL,
) -> MCPServer[Any]:
    """Create the authenticated MCP server with the full MVP tool catalog."""
    limiter = RateLimiter()
    requests = RequestCache()

    def action(
        request_id: str | None,
        signature: RequestSignature,
        run: Callable[[AgentId], dict[str, Any]],
        *text: str | None,
    ) -> dict[str, Any]:
        return _action_request(
            session,
            limiter,
            requests,
            request_id,
            signature,
            run,
            text=text,
        )

    server: MCPServer[Any] = MCPServer(
        "IASim",
        version=PROTOCOL_VERSION,
        token_verifier=SessionTokenVerifier(session),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=[AUTH_SCOPE],
            validate_token_resource=False,
        ),
    )

    @server.tool()
    def iasim_join(name: str) -> dict[str, Any]:
        """Join the session with the bearer token and return the agent id."""
        if _text_too_long(name):
            return _message_too_long(session)
        access = get_access_token()
        if access is None:
            return _unauthorized(session)
        result = session.join(name, access.token)
        if result.get("ok"):
            result["protocol_version"] = PROTOCOL_VERSION
        return result

    @server.tool()
    def iasim_leave() -> dict[str, Any]:
        """Leave the session without dying and free the slot."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.leave(agent_id)

    @server.tool()
    def iasim_observe() -> dict[str, Any]:
        """Return the current perception-limited observation."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.observe(agent_id)

    @server.tool()
    def iasim_get_session_info() -> dict[str, Any]:
        """Return day, tick, phase, and roster; never the seed or the RNG."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        result = session.info(agent_id)
        if result.get("ok"):
            result["protocol_version"] = PROTOCOL_VERSION
        return result

    @server.tool()
    def iasim_get_recipes() -> dict[str, Any]:
        """List every recipe with its ingredients and station requirement."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.recipes()

    @server.tool()
    def iasim_get_inventory() -> dict[str, Any]:
        """Return the inventory, equipment, and carrying capacity."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.inventory_for(agent_id)

    @server.tool()
    def iasim_inspect(
        target_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> dict[str, Any]:
        """Return details of one visible agent, corpse, or tile."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        if _text_too_long(target_id):
            return _message_too_long(session)
        return session.inspect(agent_id, target_id, x, y)

    @server.tool()
    def iasim_move(
        tick: Tick,
        dx: int,
        dy: int,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Queue a one-cell move in one of eight directions."""
        return action(
            request_id,
            ("move", tick, dx, dy),
            lambda agent_id: session.move(agent_id, tick, dx, dy),
        )

    @server.tool()
    def iasim_move_to(
        tick: Tick,
        x: int,
        y: int,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Advance one step along a deterministic route to the target."""
        return action(
            request_id,
            ("move_to", tick, x, y),
            lambda agent_id: session.move_to(agent_id, tick, x, y),
        )

    @server.tool()
    def iasim_wait(tick: Tick, request_id: RequestId | None = None) -> dict[str, Any]:
        """Queue a wait action for the current tick."""
        return action(
            request_id,
            ("wait", tick),
            lambda agent_id: session.wait(agent_id, tick),
        )

    @server.tool()
    def iasim_rest(tick: Tick, request_id: RequestId | None = None) -> dict[str, Any]:
        """Rest for one tick and recover energy."""
        return action(
            request_id,
            ("rest", tick),
            lambda agent_id: session.rest(agent_id, tick),
        )

    @server.tool()
    def iasim_sleep(
        tick: Tick,
        until: str | None = None,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Sleep until energy_full, dawn, or hours:N."""
        return action(
            request_id,
            ("sleep", tick, until),
            lambda agent_id: session.sleep(agent_id, tick, until),
            until,
        )

    @server.tool()
    def iasim_gather(
        tick: Tick,
        x: int,
        y: int,
        node_id: str | None = None,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Gather a manual or tool-gated resource from an adjacent tile."""
        return action(
            request_id,
            ("gather", tick, x, y, node_id),
            lambda agent_id: session.gather(agent_id, tick, x, y, node_id),
            node_id,
        )

    @server.tool()
    def iasim_pickup(
        tick: Tick,
        x: int,
        y: int,
        item_id: str | None = None,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Pick up a ground item from the current or an adjacent tile."""
        return action(
            request_id,
            ("pickup", tick, x, y, item_id),
            lambda agent_id: session.pickup(agent_id, tick, x, y, item_id),
            item_id,
        )

    @server.tool()
    def iasim_drop(
        tick: Tick,
        item_id: str,
        qty: PositiveQuantity = 1,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Drop one or more units of an inventory item."""
        return action(
            request_id,
            ("drop", tick, item_id, qty),
            lambda agent_id: session.drop(agent_id, tick, item_id, qty),
            item_id,
        )

    @server.tool()
    def iasim_eat(
        tick: Tick,
        item_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Eat one unit of food from the inventory."""
        return action(
            request_id,
            ("eat", tick, item_id),
            lambda agent_id: session.eat(agent_id, tick, item_id),
            item_id,
        )

    @server.tool()
    def iasim_drink(
        tick: Tick,
        x: int | None = None,
        y: int | None = None,
        item_id: str | None = None,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Drink from an adjacent fresh-water tile or from a waterskin."""
        return action(
            request_id,
            ("drink", tick, x, y, item_id),
            lambda agent_id: session.drink(agent_id, tick, x=x, y=y, item_id=item_id),
            item_id,
        )

    @server.tool()
    def iasim_use(
        tick: Tick,
        item_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Use a consumable such as a bandage from the inventory."""
        return action(
            request_id,
            ("use", tick, item_id),
            lambda agent_id: session.use_item(agent_id, tick, item_id),
            item_id,
        )

    @server.tool()
    def iasim_equip(
        tick: Tick,
        item_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Equip one inventory item into the slot declared by the catalog."""
        return action(
            request_id,
            ("equip", tick, item_id),
            lambda agent_id: session.equip(agent_id, tick, item_id),
            item_id,
        )

    @server.tool()
    def iasim_unequip(
        tick: Tick,
        slot: EquipSlot,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Move one equipped item back into the inventory."""
        return action(
            request_id,
            ("unequip", tick, slot.value),
            lambda agent_id: session.unequip(agent_id, tick, slot.value),
        )

    @server.tool()
    def iasim_fill(
        tick: Tick,
        item_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Fill a waterskin from adjacent fresh water."""
        return action(
            request_id,
            ("fill", tick, item_id),
            lambda agent_id: session.fill(agent_id, tick, item_id),
            item_id,
        )

    @server.tool()
    def iasim_craft(
        tick: Tick,
        recipe_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Craft one recipe when ingredients and station requirements are met."""
        return action(
            request_id,
            ("craft", tick, recipe_id),
            lambda agent_id: session.craft(agent_id, tick, recipe_id),
            recipe_id,
        )

    @server.tool()
    def iasim_build(
        tick: Tick,
        structure_id: str,
        x: int,
        y: int,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Build a fire, workbench, or shelter on an adjacent tile."""
        return action(
            request_id,
            ("build", tick, structure_id, x, y),
            lambda agent_id: session.build(agent_id, tick, structure_id, x, y),
            structure_id,
        )

    @server.tool()
    def iasim_say(message: str, target_id: str | None = None) -> dict[str, Any]:
        """Send one sanitized local chat message to agents in range."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        if _text_too_long(message, target_id):
            return _message_too_long(session)
        return session.say(agent_id, message, target_id)

    @server.tool()
    def iasim_attack(
        tick: Tick,
        target_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Attack an adjacent living agent with the equipped weapon."""
        return action(
            request_id,
            ("attack", tick, target_id),
            lambda agent_id: session.attack(agent_id, tick, target_id),
            target_id,
        )

    @server.tool()
    def iasim_throw(
        tick: Tick,
        item_id: str,
        target_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Throw a stone at a visible target up to four tiles away."""
        return action(
            request_id,
            ("throw", tick, item_id, target_id),
            lambda agent_id: session.throw(agent_id, tick, item_id, target_id),
            item_id,
            target_id,
        )

    @server.tool()
    def iasim_flee(
        tick: Tick,
        target_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Flee up to two cells away from a living target."""
        return action(
            request_id,
            ("flee", tick, target_id),
            lambda agent_id: session.flee(agent_id, tick, target_id),
            target_id,
        )

    @server.tool()
    def iasim_loot(
        tick: Tick,
        corpse_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Loot all remaining items from an adjacent corpse."""
        return action(
            request_id,
            ("loot", tick, corpse_id),
            lambda agent_id: session.loot(agent_id, tick, corpse_id),
            corpse_id,
        )

    @server.tool()
    def iasim_offer_alliance(
        tick: Tick,
        target_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Offer an alliance to a nearby living agent."""
        return action(
            request_id,
            ("offer_alliance", tick, target_id),
            lambda agent_id: session.offer_alliance(agent_id, tick, target_id),
            target_id,
        )

    @server.tool()
    def iasim_accept_alliance(
        tick: Tick,
        alliance_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Accept a pending alliance offer addressed to the agent."""
        return action(
            request_id,
            ("accept_alliance", tick, alliance_id),
            lambda agent_id: session.accept_alliance(agent_id, tick, alliance_id),
            alliance_id,
        )

    @server.tool()
    def iasim_break_alliance(
        tick: Tick,
        target_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Break an alliance, or close a pending offer."""
        return action(
            request_id,
            ("break_alliance", tick, target_id),
            lambda agent_id: session.break_alliance(agent_id, tick, target_id),
            target_id,
        )

    @server.tool()
    def iasim_offer_trade(
        tick: Tick,
        target_id: str,
        offer: list[TradeItem],
        request: list[TradeItem],
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Offer an item trade to a nearby living agent.

        Each lot is a list of ``{"item_id": str, "qty": int}`` entries with no
        extra keys; both lots must be non-empty.
        """
        offer_lot = [(entry.item_id, entry.qty) for entry in offer]
        request_lot = [(entry.item_id, entry.qty) for entry in request]
        return action(
            request_id,
            ("offer_trade", tick, target_id, tuple(offer_lot), tuple(request_lot)),
            lambda agent_id: session.offer_trade(
                agent_id,
                tick,
                target_id,
                [entry.model_dump() for entry in offer],
                [entry.model_dump() for entry in request],
            ),
            target_id,
        )

    @server.tool()
    def iasim_accept_trade(
        tick: Tick,
        trade_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Accept an open trade offer and swap the items atomically."""
        return action(
            request_id,
            ("accept_trade", tick, trade_id),
            lambda agent_id: session.accept_trade(agent_id, tick, trade_id),
            trade_id,
        )

    @server.tool()
    def iasim_decline_trade(
        tick: Tick,
        trade_id: str,
        request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Decline an open trade offer."""
        return action(
            request_id,
            ("decline_trade", tick, trade_id),
            lambda agent_id: session.decline_trade(agent_id, tick, trade_id),
            trade_id,
        )

    @server.tool()
    def iasim_report_mind(
        tick: Tick,
        intent: str,
        thought: str,
        plan: str | None = None,
        confidence: int | None = None,
    ) -> dict[str, Any]:
        """Report intent, thought, and plan for operator display."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.report_mind(
            agent_id,
            tick,
            intent=intent,
            thought=thought,
            plan=plan,
            confidence=confidence,
        )

    @server.tool()
    def iasim_report_usage(
        tick: Tick,
        input_tokens: int,
        output_tokens: int,
        model: str,
        reasoning_effort: str | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        """Report LLM token usage and model metadata for operator statistics."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.report_usage(
            agent_id,
            tick,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            reasoning_effort=reasoning_effort,
            cost_usd=cost_usd,
        )

    @server.tool()
    def iasim_wait_for_tick(
        since_tick: Tick,
        timeout_ms: TimeoutMillis = 1000,
    ) -> dict[str, Any]:
        """Wait until a tick newer than since_tick is available."""
        agent_id = _guard(session, limiter, LimitKind.INFO)
        if isinstance(agent_id, dict):
            return agent_id
        return session.wait_for_tick(agent_id, since_tick, timeout_ms)

    @server.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(request: Request) -> Response:
        """Return a minimal unauthenticated health response."""
        return JSONResponse(session.health())

    return server


def _joined_agent(session: GameSession) -> AgentId | None:
    access = get_access_token()
    if access is None:
        return None
    return session.agent_for_token(access.token)


def _guard(
    session: GameSession,
    limiter: RateLimiter,
    kind: LimitKind,
) -> AgentId | dict[str, Any]:
    agent_id = _joined_agent(session)
    if agent_id is None:
        return _unauthorized(session)
    if not limiter.allow(str(agent_id), kind):
        return _rate_limited(session, kind)
    return agent_id


def _action_request(
    session: GameSession,
    limiter: RateLimiter,
    requests: RequestCache,
    request_id: str | None,
    signature: RequestSignature,
    run: Callable[[AgentId], dict[str, Any]],
    *,
    text: tuple[str | None, ...] = (),
) -> dict[str, Any]:
    """Run one primary action, replaying a repeated request id."""
    agent_id = _guard(session, limiter, LimitKind.ACTION)
    if isinstance(agent_id, dict):
        return agent_id
    if text and _text_too_long(*text):
        return _message_too_long(session)
    if request_id is None:
        return run(agent_id)

    cleaned = request_id.strip()
    if not cleaned or len(cleaned) > MAX_REQUEST_ID_LENGTH:
        return _invalid_request_id(session)
    cached = requests.lookup(str(agent_id), cleaned)
    if cached is not None:
        if cached.signature != signature:
            return _request_id_conflict(session)
        return dict(cached.result)

    result = run(agent_id)
    if result.get("ok"):
        requests.store(str(agent_id), cleaned, signature, result)
    return result


def _text_too_long(*values: str | None) -> bool:
    return any(value is not None and len(value) > MAX_TEXT_FIELD_LENGTH for value in values)


def _rate_limited(session: GameSession, kind: LimitKind) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "RATE_LIMITED",
            "message": f"{kind.value} rate limit exceeded; retry later",
        },
    }


def _message_too_long(session: GameSession) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "MESSAGE_TOO_LONG",
            "message": f"text fields must be at most {MAX_TEXT_FIELD_LENGTH} characters",
        },
    }


def _invalid_request_id(session: GameSession) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "INVALID_REQUEST_ID",
            "message": (f"request_id must be 1-{MAX_REQUEST_ID_LENGTH} non-blank characters"),
        },
    }


def _request_id_conflict(session: GameSession) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "REQUEST_ID_CONFLICT",
            "message": "request_id was already used for a different action",
        },
    }


def _unauthorized(session: GameSession) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "UNAUTHORIZED",
            "message": "bearer token is not bound to a joined agent",
        },
    }


def create_app(
    session: GameSession,
    *,
    resource_url: str = DEFAULT_RESOURCE_URL,
    issuer_url: str = DEFAULT_ISSUER_URL,
) -> tuple[MCPServer[Any], Starlette]:
    """Create the MCP server and its streamable HTTP application."""
    server = create_server(session, resource_url=resource_url, issuer_url=issuer_url)
    return server, server.streamable_http_app()


def run_server(
    session: GameSession,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the streamable HTTP MCP server until stopped."""
    connection = server_connection_info(host, port)
    print(f"MCP endpoint: {connection['mcp_url']}")
    if connection["warning"] is not None:
        print(f"warning: {connection['warning']}")
    server = create_server(
        session,
        resource_url=str(connection["mcp_url"]),
        issuer_url=str(connection["issuer_url"]),
    )
    server.run("streamable-http", host=host, port=port)
