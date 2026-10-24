"""Tests for the IASim command-line interface."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

from iasim import __version__
from iasim.app.session import GameSession
from iasim.cli import main
from iasim.errors import (
    ConfigurationError,
    ExitCode,
    McpError,
    PersistenceError,
    WorldGenerationError,
)
from iasim.protocol import PROTOCOL_VERSION


class _FakeServer:
    mcp_url = "http://127.0.0.1:8765/mcp"
    warning = None

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class CliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, Any, Any, Any, Any]:
        server = _FakeServer()
        with (
            patch("iasim.cli.start_server", return_value=server) as start,
            patch("iasim.cli.run_gui") as gui,
            patch("iasim.cli.wait_for_shutdown") as wait,
        ):
            code = main(argv)
        return code, server, gui, wait, start

    def _latest_log(self, directory: str) -> tuple[Path, dict[str, Any]]:
        run_dirs = list(Path(directory).iterdir())
        self.assertEqual(len(run_dirs), 1)
        log_path = run_dirs[0] / "iasim.log"
        self.assertTrue(log_path.is_file())
        line = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        return log_path, json.loads(line)

    def test_version_flag_reports_package_and_protocol_versions(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn(__version__, output.getvalue())
        self.assertIn(PROTOCOL_VERSION, output.getvalue())

    def test_help_flag_exits_successfully(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", output.getvalue())

    def test_startup_creates_run_directory_and_structured_log(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                exit_code, server, gui, wait, _start = self._run(
                    ["--seed", "123", "--log-dir", directory]
                )

            log_path, event = self._latest_log(directory)
            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["event"], "session_started")
        self.assertEqual(event["seed"], 123)
        self.assertEqual(event["iasim_version"], __version__)
        self.assertEqual(event["mcp_protocol_version"], PROTOCOL_VERSION)
        self.assertIn("seed=123", output.getvalue())
        self.assertNotIn("token", log_text)
        gui.assert_called_once()
        wait.assert_not_called()
        self.assertTrue(server.stopped)

    def test_config_file_and_cli_overrides_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "iasim.toml"
            config_path.write_text(
                """
[game]
seed = 1
headless = false
autosave_every_ticks = 1000

[mcp]
port = 8765
""",
                encoding="utf-8",
            )
            log_dir = Path(directory) / "runs"

            exit_code, _server, gui, wait, _start = self._run(
                [
                    "--config",
                    str(config_path),
                    "--seed",
                    "9",
                    "--port",
                    "9001",
                    "--headless",
                    "--agents",
                    "3",
                    "--no-autosave",
                    "--log-dir",
                    str(log_dir),
                ]
            )
            _, event = self._latest_log(str(log_dir))

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["seed"], 9)
        self.assertEqual(event["mcp_port"], 9001)
        self.assertTrue(event["headless"])
        self.assertEqual(event["agents_min"], 3)
        self.assertEqual(event["agents_max"], 3)
        self.assertEqual(event["autosave_every_ticks"], 0)
        self.assertEqual(event["config_path"], str(config_path))
        wait.assert_called_once()
        gui.assert_not_called()

    def test_serve_headless_starts_server_with_config_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, _server, gui, wait, start = self._run(
                [
                    "serve",
                    "--headless",
                    "--seed",
                    "11",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9002",
                    "--max-agents",
                    "2",
                    "--log-dir",
                    directory,
                ]
            )
            log_path, event = self._latest_log(directory)
            run_dir = log_path.parent
            session = start.call_args.args[0]
            token_data = json.loads((run_dir / "agents.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["seed"], 11)
        self.assertEqual(
            start.call_args.kwargs,
            {"host": "0.0.0.0", "port": 9002, "dev_open": False},
        )
        self.assertEqual(session.max_agents, 2)
        self.assertEqual(len(session.tokens), 2)
        self.assertEqual(token_data["max_agents"], 2)
        self.assertEqual(len(token_data["agents"]), 2)
        wait.assert_called_once()
        gui.assert_not_called()

    def test_serve_without_headless_opens_the_gui(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                exit_code, _server, gui, wait, _start = self._run(
                    ["serve", "--seed", "1", "--log-dir", directory]
                )
            run_dir = next(Path(directory).iterdir())
            has_agents = (run_dir / "agents.json").is_file()

        self.assertEqual(exit_code, 0)
        gui.assert_called_once()
        wait.assert_not_called()
        self.assertTrue(has_agents)
        self.assertIn("operator GUI", output.getvalue())

    def test_host_override_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, _server, _gui, _wait, _start = self._run(
                ["--host", "0.0.0.0", "--port", "9001", "--log-dir", directory]
            )
            _, event = self._latest_log(directory)

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["mcp_host"], "0.0.0.0")
        self.assertEqual(event["mcp_port"], 9001)

    def test_dev_open_rejects_lan_host(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--host", "0.0.0.0", "--dev-open"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("loopback", error.getvalue())

    def test_explicit_min_agents_wins_over_agents_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, _server, _gui, _wait, _start = self._run(
                ["--agents", "3", "--min-agents", "2", "--log-dir", directory]
            )
            _, event = self._latest_log(directory)

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["agents_min"], 2)
        self.assertEqual(event["agents_max"], 3)

    def test_log_directory_can_come_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory) / "from-config"
            config_path = Path(directory) / "iasim.toml"
            config_path.write_text(
                f'[logs]\ndir = "{log_dir.as_posix()}"\n',
                encoding="utf-8",
            )

            exit_code, _server, _gui, _wait, _start = self._run(
                ["--config", str(config_path), "--seed", "5"]
            )

            _, event = self._latest_log(str(log_dir))

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["seed"], 5)

    def test_existing_load_file_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = GameSession(42, token_path=path / "agents.json")
            load_path = path / "session.json"
            source.save(load_path)
            log_dir = path / "runs"

            exit_code, _server, _gui, _wait, start = self._run(
                ["--load", str(load_path), "--seed", "1", "--log-dir", str(log_dir)]
            )
            loaded = start.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertIsInstance(loaded, GameSession)
        self.assertEqual(loaded.state.tick, source.state.tick)

    def test_cli_gameplay_flags_are_honored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, _server, _gui, _wait, start = self._run(
                [
                    "--headless",
                    "--seed",
                    "3",
                    "--max-agents",
                    "3",
                    "--tick-minutes",
                    "7",
                    "--turn-timeout-ms",
                    "1500",
                    "--timeout-disconnects",
                    "5",
                    "--snapshot-every",
                    "33",
                    "--autosave-every",
                    "50",
                    "--log-dir",
                    directory,
                ]
            )
            session = start.call_args.args[0]

        self.assertEqual(exit_code, 0)
        self.assertEqual(session.max_agents, 3)
        self.assertEqual(session.state.tick_minutes, 7)
        self.assertEqual(session.turn_timeout_ms, 1500)
        self.assertEqual(session.timeout_disconnects, 5)
        self.assertEqual(session.snapshot_every_ticks, 33)

    def test_bare_and_serve_commands_are_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = self._run(["--seed", "1", "--log-dir", str(Path(directory) / "a")])
            second = self._run(["serve", "--seed", "1", "--log-dir", str(Path(directory) / "b")])

        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        first[2].assert_called_once()
        second[2].assert_called_once()

    def test_show_tokens_prints_invite_credentials_without_logging_them(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                code, _server, gui, wait, start = self._run(
                    [
                        "serve",
                        "--show-tokens",
                        "--headless",
                        "--seed",
                        "7",
                        "--log-dir",
                        directory,
                    ]
                )
            session = start.call_args.args[0]
            run_dir = next(Path(directory).iterdir())
            log_text = "\n".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in run_dir.iterdir()
                if path.is_file() and path.name != "agents.json"
            )

        self.assertEqual(code, 0)
        gui.assert_not_called()
        wait.assert_called_once()
        for token in session.tokens:
            self.assertIn(token, output.getvalue())
            self.assertNotIn(token, log_text)
        self.assertIn("Authorization: Bearer", output.getvalue())
        self.assertIn("WARNING: do not share", output.getvalue())
        self.assertIn("slot 1 (ag_01)", output.getvalue())

    def test_default_startup_never_prints_tokens(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                code, _server, _gui, _wait, start = self._run(
                    ["serve", "--headless", "--seed", "7", "--log-dir", directory]
                )
            session = start.call_args.args[0]

        self.assertEqual(code, 0)
        for token in session.tokens:
            self.assertNotIn(token, output.getvalue())
        self.assertNotIn("Authorization: Bearer", output.getvalue())
        self.assertIn("tokens are never printed", output.getvalue())

    def test_lan_startup_prints_url_and_warning_but_never_tokens(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                exit_code, server, _gui, _wait, start = self._run(
                    [
                        "serve",
                        "--headless",
                        "--host",
                        "0.0.0.0",
                        "--port",
                        "9003",
                        "--log-dir",
                        directory,
                    ]
                )
            session = start.call_args.args[0]
            log_texts = "".join(
                path.read_text(encoding="utf-8")
                for path in next(Path(directory).iterdir()).glob("*.log")
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(server.mcp_url, "http://127.0.0.1:8765/mcp")
        self.assertIn("MCP endpoint:", output.getvalue())
        self.assertIn("tokens are never printed", output.getvalue())
        for token in session.tokens:
            self.assertNotIn(token, output.getvalue())
            self.assertNotIn(token, log_texts)

    def test_gui_mode_finishes_the_session_on_quit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, server, gui, _wait, start = self._run(
                ["--seed", "4", "--log-dir", directory]
            )
            session = start.call_args.args[0]

        self.assertEqual(exit_code, 0)
        gui.assert_called_once()
        self.assertTrue(server.stopped)
        self.assertTrue(session.is_finished)

    def test_missing_config_returns_configuration_exit_code(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--config", "missing.toml"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("missing.toml", error.getvalue())

    def test_invalid_cli_value_returns_configuration_exit_code(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--port", "0"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("mcp.port", error.getvalue())

    def test_unknown_flag_returns_configuration_exit_code(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--not-a-flag"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("unrecognized arguments", error.getvalue())

    def test_missing_load_file_returns_persistence_exit_code(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--load", "missing.json"])

        self.assertEqual(exit_code, ExitCode.PERSISTENCE)
        self.assertIn("load file does not exist", error.getvalue())

    def test_missing_replay_file_returns_persistence_exit_code(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--replay", "missing.json"])

        self.assertEqual(exit_code, ExitCode.PERSISTENCE)
        self.assertIn("replay file does not exist", error.getvalue())

    def test_load_and_replay_are_mutually_exclusive(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--load", "a.json", "--replay", "b.json"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("not allowed with argument", error.getvalue())

    def test_dev_open_rejects_non_loopback_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "iasim.toml"
            config_path.write_text('[mcp]\nhost = "0.0.0.0"\n', encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(["--config", str(config_path), "--dev-open"])

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("loopback", error.getvalue())

    def test_exit_code_contract_is_complete(self) -> None:
        self.assertEqual(int(ExitCode.SUCCESS), 0)
        self.assertEqual(int(ExitCode.CONFIGURATION), 1)
        self.assertEqual(int(ExitCode.WORLD_GENERATION), 2)
        self.assertEqual(int(ExitCode.MCP), 3)
        self.assertEqual(int(ExitCode.PERSISTENCE), 4)
        self.assertEqual(int(ExitCode.INTERNAL), 5)
        self.assertEqual(ConfigurationError.exit_code, ExitCode.CONFIGURATION)
        self.assertEqual(WorldGenerationError.exit_code, ExitCode.WORLD_GENERATION)
        self.assertEqual(McpError.exit_code, ExitCode.MCP)
        self.assertEqual(PersistenceError.exit_code, ExitCode.PERSISTENCE)


if __name__ == "__main__":
    unittest.main()
