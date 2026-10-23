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

from iasim import MCP_PROTOCOL_VERSION, __version__
from iasim.cli import main
from iasim.errors import (
    ConfigurationError,
    ExitCode,
    McpError,
    PersistenceError,
    WorldGenerationError,
)


class CliTests(unittest.TestCase):
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
        self.assertIn(MCP_PROTOCOL_VERSION, output.getvalue())

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
                exit_code = main(["--seed", "123", "--log-dir", directory])

            log_path, event = self._latest_log(directory)
            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["event"], "session_started")
        self.assertEqual(event["seed"], 123)
        self.assertEqual(event["iasim_version"], __version__)
        self.assertEqual(event["mcp_protocol_version"], MCP_PROTOCOL_VERSION)
        self.assertIn("seed=123", output.getvalue())
        self.assertNotIn("token", log_text)

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

            exit_code = main(
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

    def test_serve_headless_starts_server_with_config_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("iasim.cli.run_server") as run_server_mock:
                exit_code = main(
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
            session = run_server_mock.call_args.args[0]
            token_data = json.loads((run_dir / "agents.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["seed"], 11)
        self.assertEqual(run_server_mock.call_args.kwargs, {"host": "0.0.0.0", "port": 9002})
        self.assertEqual(session.max_agents, 2)
        self.assertEqual(len(session.tokens), 2)
        self.assertEqual(token_data["max_agents"], 2)
        self.assertEqual(len(token_data["agents"]), 2)

    def test_serve_without_headless_is_rejected(self) -> None:
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(error):
                exit_code = main(["serve", "--seed", "1", "--log-dir", directory])
            run_dir = next(Path(directory).iterdir())

        self.assertEqual(exit_code, ExitCode.CONFIGURATION)
        self.assertIn("headless", error.getvalue())
        self.assertFalse((run_dir / "agents.json").exists())

    def test_host_override_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code = main(["--host", "0.0.0.0", "--port", "9001", "--log-dir", directory])
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
            exit_code = main(["--agents", "3", "--min-agents", "2", "--log-dir", directory])
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

            exit_code = main(["--config", str(config_path), "--seed", "5"])

            _, event = self._latest_log(str(log_dir))

        self.assertEqual(exit_code, 0)
        self.assertEqual(event["seed"], 5)

    def test_existing_load_file_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            load_path = Path(directory) / "session.json"
            load_path.write_text("{}", encoding="utf-8")
            log_dir = Path(directory) / "runs"
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["--load", str(load_path), "--seed", "1", "--log-dir", str(log_dir)]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn(f"load requested: {load_path}", output.getvalue())

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
