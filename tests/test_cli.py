"""Tests for the scaffolded IASim command-line interface."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from iasim import MCP_PROTOCOL_VERSION, __version__
from iasim.cli import main


class CliTests(unittest.TestCase):
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

    def test_no_arguments_returns_zero_and_reports_scaffold_state(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("scaffold ready", output.getvalue())


if __name__ == "__main__":
    unittest.main()
