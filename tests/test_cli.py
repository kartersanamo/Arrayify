from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from main import should_launch_gui
from tank_tools.config import ProjectConfig
from tests.test_work_regs import build_lm4p_block


class ShouldLaunchGuiTests(unittest.TestCase):
    def test_frozen_default_launches_gui(self) -> None:
        with patch("main.is_frozen", return_value=True):
            self.assertTrue(should_launch_gui(False, False))

    def test_frozen_with_cli_skips_gui(self) -> None:
        with patch("main.is_frozen", return_value=True):
            self.assertFalse(should_launch_gui(False, True))

    def test_explicit_gui(self) -> None:
        with patch("main.is_frozen", return_value=True):
            self.assertTrue(should_launch_gui(True, True))

    def test_dev_default_is_cli(self) -> None:
        with patch("main.is_frozen", return_value=False):
            self.assertFalse(should_launch_gui(False, False))


class ProjectConfigFromPathsTests(unittest.TestCase):
    def test_output_paths_use_input_stem(self) -> None:
        input_csv = Path("/tmp/JuneThird.csv")
        config = ProjectConfig.from_paths(input_csv)
        self.assertEqual(config.input_csv_path, input_csv.resolve())
        self.assertEqual(
            config.arrayified_csv_path.resolve(),
            (input_csv.parent / "JuneThird_arrayified.csv").resolve(),
        )


class PipelineRunAllTests(unittest.TestCase):
    def test_run_all_calls_steps_in_order(self) -> None:
        from tank_tools.config import ProjectConfig
        from tank_tools.io import CsvRepository
        from tank_tools.pipeline import TankPipeline
        from tank_tools.rules import TankRules

        rows = build_lm4p_block()
        config = ProjectConfig(root=Path("/tmp"))
        pipeline = TankPipeline(config, CsvRepository(), TankRules())
        calls: list[str] = []

        with (
            patch.object(
                pipeline._arrayify_service,
                "arrayify_points",
                side_effect=lambda **kwargs: calls.append("arrayify") or kwargs["input_rows"],
            ),
            patch.object(
                pipeline._sounding_service,
                "sound_tanks",
                side_effect=lambda **kwargs: calls.append("sound") or kwargs["input_rows"],
            ),
            patch.object(
                pipeline._work_reg_service,
                "label_work_registers",
                side_effect=lambda *args, **kwargs: calls.append("tank_registers") or kwargs["input_rows"],
            ),
            patch.object(
                pipeline._normalization_service,
                "normalize_tags",
                side_effect=lambda **kwargs: calls.append("normalize") or kwargs["input_rows"],
            ),
        ):
            result = pipeline.run(
                "all",
                rows,
                work_reg_bindings={},
                write_output=False,
            )

        self.assertIsNotNone(result)
        self.assertEqual(calls, ["arrayify", "sound", "tank_registers", "normalize"])


class CliExportTests(unittest.TestCase):
    def test_export_writes_labeled_files(self) -> None:
        from tempfile import TemporaryDirectory

        from tank_tools.cli import TankCli
        from tank_tools.io import CsvRepository

        baseline = build_lm4p_block()
        current = [list(row) for row in baseline]
        current[2][0] = "LM_4P_WORK_REG_0"
        current[2][2] = "Liquid Mud #4-P Register # 0"
        current[2][15] = ""

        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            input_csv = temp / "input.csv"
            baseline_csv = temp / "baseline.csv"
            export_base = temp / "export.csv"
            CsvRepository().write_rows(baseline_csv, baseline)
            CsvRepository().write_rows(input_csv, current)

            args = type(
                "Args",
                (),
                {
                    "command": "export",
                    "input": input_csv,
                    "baseline": baseline_csv,
                    "output": export_base,
                    "output_dir": None,
                    "docx_dir": None,
                    "custom_tag": [],
                    "regs_only": False,
                },
            )()

            cli = TankCli()
            self.assertEqual(cli.run(args), 0)
            self.assertTrue((temp / "export-BYREF-FIRST.csv").is_file())
            self.assertTrue((temp / "export-BYNAME-SECOND.csv").is_file())


if __name__ == "__main__":
    unittest.main()
