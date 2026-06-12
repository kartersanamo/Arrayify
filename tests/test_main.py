from __future__ import annotations

import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tank_tools.cli import TankCli, build_parser
from tank_tools.io import CsvRepository
from tests.test_work_regs import build_lm4p_block


class CliParserTests(unittest.TestCase):
    def test_parser_accepts_run_all(self) -> None:
        parser = build_parser()
        parser.add_argument("--cli", action="store_true")
        args = parser.parse_args(["--input", "test.csv", "run-all"])
        self.assertEqual(args.command, "run-all")
        self.assertEqual(args.input, Path("test.csv"))


class CliMenuTests(unittest.TestCase):
    def test_menu_requires_input_when_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            rows = build_lm4p_block()
            input_csv = temp / "sample.csv"
            CsvRepository().write_rows(input_csv, rows)

            args = Namespace(
                command="menu",
                input=input_csv,
                output_dir=None,
                docx_dir=None,
                custom_tag=[],
                output=None,
                tag_prefix_from=None,
                regs_only=False,
                baseline=None,
            )

            with patch("builtins.input", return_value="1"):
                with patch.object(TankCli, "_run_command", return_value=0) as run_command:
                    cli = TankCli()
                    self.assertEqual(cli.run(args), 0)
                    run_command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
