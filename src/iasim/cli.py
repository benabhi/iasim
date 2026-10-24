"""Command-line entry point for IASim."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import secrets
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from iasim import __version__
from iasim.app.replay import replay_saved_run
from iasim.app.session import GameSession
from iasim.config import ConfigError, IasimConfig, load_config
from iasim.domain.usage import ModelPricing
from iasim.errors import ExitCode, IasimError, PersistenceError
from iasim.mcp.server import start_server
from iasim.protocol import PROTOCOL_VERSION
from iasim.ui.app import run_gui, wait_for_shutdown

LOG_FILENAME = "iasim.log"
_LOG_FIELDS = (
    "agents_max",
    "agents_min",
    "autosave_every_ticks",
    "config_path",
    "headless",
    "iasim_version",
    "mcp_host",
    "mcp_port",
    "mcp_protocol_version",
    "replay_path",
    "run_dir",
    "seed",
)


class IasimArgumentParser(argparse.ArgumentParser):
    """Argument parser that routes invalid input through the config exit code."""

    def error(self, message: str) -> NoReturn:
        raise ConfigError(message, source="<cli>")


class JsonFormatter(logging.Formatter):
    """Render one structured JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "event": record.getMessage(),
            "level": record.levelname,
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        for field in _LOG_FIELDS:
            if field in record.__dict__:
                payload[field] = record.__dict__[field]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level IASim argument parser."""
    parser = IasimArgumentParser(
        prog="iasim",
        description="Deterministic multi-agent survival simulation sandbox.",
    )
    parser.add_argument("--config", type=Path, help="load configuration from a TOML file")
    parser.add_argument("--seed", type=int, help="set the deterministic session seed")
    parser.add_argument("--headless", action="store_true", help="run without a window")
    parser.add_argument("--agents", type=_positive_int, help="set the lobby agent count")
    parser.add_argument("--host", help="set the MCP bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="set the MCP port")
    parser.add_argument("--max-agents", type=_positive_int, help="set the concurrent agent limit")
    parser.add_argument("--dev-open", action="store_true", help="disable auth on loopback only")
    parser.add_argument(
        "--min-agents",
        type=_positive_int,
        help="set the minimum agent count",
    )
    parser.add_argument(
        "--tick-minutes", type=_positive_int, help="set minutes per simulation tick"
    )
    parser.add_argument("--turn-timeout-ms", type=_positive_int, help="set the turn deadline in ms")
    parser.add_argument(
        "--timeout-disconnects",
        type=_positive_int,
        help="set consecutive timeouts before an agent becomes absent",
    )
    parser.add_argument(
        "--snapshot-every",
        type=_positive_int,
        help="set the snapshot cadence in ticks",
    )
    parser.add_argument(
        "--autosave-every",
        type=_non_negative_int,
        help="set the autosave cadence in ticks (0 disables)",
    )
    parser.add_argument("--no-autosave", action="store_true", help="disable automatic saves")
    parser.add_argument("--log-dir", type=Path, help="set the run log directory")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve",),
        help="'serve' is an alias of the default integrated startup",
    )
    session_source = parser.add_mutually_exclusive_group()
    session_source.add_argument("--load", type=Path, help="load a saved session")
    session_source.add_argument("--replay", type=Path, help="replay a saved session")
    parser.add_argument(
        "--version",
        action="version",
        version=f"IASim {__version__} (MCP protocol {PROTOCOL_VERSION})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments, start a session, and return an exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        config = load_config(args.config, _build_overrides(args))
        _validate_session_source(args)
        seed = _resolve_seed(config)
        run_dir = _create_run_dir(config, seed)
        logger = _configure_logging(run_dir)
        try:
            logger.info("session_started", extra=_startup_fields(config, args, seed, run_dir))
        finally:
            _close_logger(logger)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(ExitCode.CONFIGURATION)
    except IasimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:
        print(f"error: internal error: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL)

    print(f"IASim {__version__} | seed={seed} | run={run_dir}")
    if args.load is not None:
        print(f"load requested: {args.load}")
    if args.replay is not None:
        report = replay_saved_run(args.replay)
        status = "match" if report.matched else "divergence"
        print(
            f"replay {status}: {report.ticks_replayed} ticks, "
            f"{report.actions_replayed} actions, offset {report.action_offset}"
        )
        if not report.matched:
            print(f"replay detail: {report.detail}", file=sys.stderr)
            return int(ExitCode.PERSISTENCE)
        return int(ExitCode.SUCCESS)

    headless = args.headless or config.game.headless
    server = None
    session = None
    try:
        session = _create_session(config, seed, run_dir, args)
        server = start_server(
            session,
            host=config.mcp.host,
            port=config.mcp.port,
            dev_open=config.mcp.dev_open,
        )
        print(f"MCP endpoint: {server.mcp_url}")
        if server.warning is not None:
            print(f"warning: {server.warning}")
        print(f"agents file: {run_dir / 'agents.json'} (tokens are never printed)")
        if headless:
            print("headless mode: MCP only; press Ctrl+C to stop")
            wait_for_shutdown()
        else:
            print("operator GUI: 160x45 | F1 ayuda | Q salir")
            run_gui(session, capacity=config.game.max_agents)
    except KeyboardInterrupt:
        print("IASim stopped")
    except IasimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except OSError as exc:
        print(f"error: MCP server could not start: {exc}", file=sys.stderr)
        return int(ExitCode.MCP)
    except Exception as exc:
        print(f"error: internal error: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL)
    finally:
        if server is not None:
            server.stop()
        if session is not None and not session.is_finished:
            with contextlib.suppress(IasimError):
                session.finish()

    return int(ExitCode.SUCCESS)


def _create_session(
    config: IasimConfig,
    seed: int,
    run_dir: Path,
    args: argparse.Namespace,
) -> GameSession:
    if args.load is not None:
        return GameSession.load(
            args.load,
            token_path=args.load.parent / "agents.json",
            log_dir=run_dir,
            snapshot_every_ticks=config.logs.snapshot_every_ticks,
            turn_timeout_ms=config.game.turn_timeout_ms,
            timeout_disconnects=config.game.timeout_disconnects,
            weather_min_ticks=config.weather.weather_min_ticks,
            weather_max_ticks=config.weather.weather_max_ticks,
            usage_pricing=_usage_pricing(config),
        )
    return GameSession(
        seed,
        tick_minutes=config.game.tick_minutes,
        turn_timeout_ms=config.game.turn_timeout_ms,
        timeout_disconnects=config.game.timeout_disconnects,
        max_agents=config.game.max_agents,
        token_path=run_dir / "agents.json",
        weather_min_ticks=config.weather.weather_min_ticks,
        weather_max_ticks=config.weather.weather_max_ticks,
        usage_pricing=_usage_pricing(config),
        log_dir=run_dir,
        snapshot_every_ticks=config.logs.snapshot_every_ticks,
    )


def _build_overrides(args: argparse.Namespace) -> dict[str, Any]:
    game: dict[str, Any] = {}
    mcp: dict[str, Any] = {}
    logs: dict[str, Any] = {}

    if args.seed is not None:
        game["seed"] = args.seed
    if args.headless:
        game["headless"] = True
    if args.agents is not None:
        game["min_agents"] = args.agents
        game["max_agents"] = args.agents
    if args.min_agents is not None:
        game["min_agents"] = args.min_agents
    if args.max_agents is not None:
        game["max_agents"] = args.max_agents
    if args.tick_minutes is not None:
        game["tick_minutes"] = args.tick_minutes
    if args.turn_timeout_ms is not None:
        game["turn_timeout_ms"] = args.turn_timeout_ms
    if args.timeout_disconnects is not None:
        game["timeout_disconnects"] = args.timeout_disconnects
    if args.autosave_every is not None:
        game["autosave_every_ticks"] = args.autosave_every
    if args.no_autosave:
        game["autosave_every_ticks"] = 0
    if args.snapshot_every is not None:
        logs["snapshot_every_ticks"] = args.snapshot_every
    if args.host is not None:
        mcp["host"] = args.host
    if args.port is not None:
        mcp["port"] = args.port
    if args.dev_open:
        mcp["dev_open"] = True
    if args.log_dir is not None:
        logs["dir"] = args.log_dir

    overrides: dict[str, Any] = {}
    if game:
        overrides["game"] = game
    if mcp:
        overrides["mcp"] = mcp
    if logs:
        overrides["logs"] = logs
    return overrides


def _validate_session_source(args: argparse.Namespace) -> None:
    for label, path in (("load", args.load), ("replay", args.replay)):
        if path is not None and not path.is_file():
            raise PersistenceError(f"{label} file does not exist: {path}")


def _resolve_seed(config: IasimConfig) -> int:
    if config.game.seed is not None:
        return config.game.seed
    return secrets.randbits(63)


def _usage_pricing(config: IasimConfig) -> dict[str, ModelPricing]:
    return {
        model: ModelPricing(
            input_per_million_usd=price.input_per_million_usd,
            output_per_million_usd=price.output_per_million_usd,
        )
        for model, price in config.usage.pricing.items()
    }


def _create_run_dir(config: IasimConfig, seed: int) -> Path:
    base = config.logs.dir
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PersistenceError(f"cannot create log directory {base}: {exc}") from exc

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = base / f"{timestamp}-seed{seed}"
    try:
        run_dir.mkdir()
    except OSError as exc:
        raise PersistenceError(f"cannot create run directory {run_dir}: {exc}") from exc
    return run_dir


def _configure_logging(run_dir: Path) -> logging.Logger:
    logger = logging.getLogger("iasim")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(run_dir / LOG_FILENAME, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def _startup_fields(
    config: IasimConfig,
    args: argparse.Namespace,
    seed: int,
    run_dir: Path,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "agents_max": config.game.max_agents,
        "agents_min": config.game.min_agents,
        "autosave_every_ticks": config.game.autosave_every_ticks,
        "headless": config.game.headless,
        "iasim_version": __version__,
        "mcp_host": config.mcp.host,
        "mcp_port": config.mcp.port,
        "mcp_protocol_version": PROTOCOL_VERSION,
        "run_dir": str(run_dir),
        "seed": seed,
    }
    if args.config is not None:
        fields["config_path"] = str(args.config)
    if args.replay is not None:
        fields["replay_path"] = str(args.replay)
    return fields
