"""Tests for TOML configuration loading and validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iasim.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def _write_config(self, directory: str, text: str) -> Path:
        path = Path(directory) / "iasim.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_are_valid(self) -> None:
        config = load_config()

        self.assertIsNone(config.game.seed)
        self.assertEqual(config.game.max_agents, 8)
        self.assertEqual(config.world.width, 80)
        self.assertEqual(config.world.height, 40)
        self.assertEqual(config.mcp.host, "127.0.0.1")
        self.assertEqual(config.mcp.port, 8765)
        self.assertEqual(config.ui.language, "es")

    def test_valid_toml_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(
                directory,
                """
[game]
seed = 42
min_agents = 2
max_agents = 4
headless = true

[world]
name = "test_island"

[logs]
snapshot_every_ticks = 25

[debug]
enabled = true
""",
            )

            config = load_config(path)

        self.assertEqual(config.game.seed, 42)
        self.assertEqual(config.game.min_agents, 2)
        self.assertEqual(config.game.max_agents, 4)
        self.assertTrue(config.game.headless)
        self.assertEqual(config.world.name, "test_island")
        self.assertEqual(config.logs.snapshot_every_ticks, 25)
        self.assertTrue(config.debug.enabled)

    def test_cli_overrides_take_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(
                directory,
                """
[game]
seed = 1

[mcp]
port = 8765
""",
            )

            config = load_config(
                path,
                overrides={"game": {"seed": 7}, "mcp": {"port": 9999}},
            )

        self.assertEqual(config.game.seed, 7)
        self.assertEqual(config.mcp.port, 9999)

    def test_invalid_field_reports_file_key_and_expectation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, '[game]\ntick_minutes = "five"\n')

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        message = str(raised.exception)
        self.assertIn(str(path), message)
        self.assertIn("game.tick_minutes", message)
        self.assertIn("integer", message)
        self.assertIn("five", message)

    def test_unknown_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, "[game]\nnot_a_setting = true\n")

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        self.assertIn("game.not_a_setting", str(raised.exception))
        self.assertIn("Extra inputs are not permitted", str(raised.exception))

    def test_invalid_toml_reports_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, "[game\nseed = 1\n")

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        message = str(raised.exception)
        self.assertIn(str(path), message)
        self.assertIn("invalid TOML", message)

    def test_missing_file_is_rejected(self) -> None:
        path = Path("does-not-exist.toml")

        with self.assertRaises(ConfigError) as raised:
            load_config(path)

        self.assertIn(str(path), str(raised.exception))
        self.assertIn("does not exist", str(raised.exception))

    def test_agent_minimum_cannot_exceed_maximum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(
                directory,
                "[game]\nmin_agents = 5\nmax_agents = 2\n",
            )

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        self.assertIn("game.max_agents", str(raised.exception))
        self.assertIn("min_agents", str(raised.exception))

    def test_dev_open_requires_loopback_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(
                directory,
                '[mcp]\nhost = "0.0.0.0"\ndev_open = true\n',
            )

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        self.assertIn("mcp", str(raised.exception))
        self.assertIn("loopback", str(raised.exception))

    def test_world_dimensions_are_fixed_for_the_mvp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, "[world]\nwidth = 100\n")

            with self.assertRaises(ConfigError) as raised:
                load_config(path)

        self.assertIn("world.width", str(raised.exception))
        self.assertIn("80", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
