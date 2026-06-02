from __future__ import annotations

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tank_tools.change_tracker import RowChangeTracker
from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import ArrayifyService, TagNormalizationService, TankWorkRegService


def make_row(register: str, description: str = "", initial: str = "0") -> list[str]:
    row = [""] * 16
    row[0] = register
    row[1] = "REAL"
    row[2] = description
    row[12] = initial
    row[15] = ""
    return row


def build_lm4p_block() -> list[list[str]]:
    header = ["Name", "Type", "Description"] + [""] * 13
    rows = [
        header,
        make_row("R100", "Liquid Mud #4-P Tank Volume"),
        make_row("R101"),
        make_row("R102"),
        make_row("R103"),
        make_row("R104"),
        make_row("R105", "Liquid Mud #4-P Tank Volume @ 0", "1.0"),
        make_row("R106", "Liquid Mud #4-P Tank Volume @ 1", "2.0"),
    ]
    return rows


class TankRulesWorkRegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = TankRules()

    def test_volume_prefix_parsing(self) -> None:
        prefix = self.rules.volume_description_to_work_reg_prefix("Liquid Mud #4-P Tank Volume", {})
        self.assertEqual(prefix, "LM_4P")

    def test_work_reg_tag_and_description(self) -> None:
        self.assertTrue(self.rules.is_work_reg_tag("LM_4P_WORK_REG[2]"))
        self.assertEqual(
            self.rules.build_work_reg_description("Liquid Mud #4-P", 0),
            "Liquid Mud #4-P Tank Input",
        )


class TankWorkRegServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = TankRules()
        self.config = ProjectConfig(root=Path("/tmp"))
        self.csv_repository = CsvRepository()
        self.service = TankWorkRegService(self.config, self.csv_repository, self.rules)
        self._temp_dir = TemporaryDirectory()
        self.prefix_path = Path(self._temp_dir.name) / "prefix.csv"
        self.csv_repository.write_rows(self.prefix_path, [["Name", "Type", "Description"]])

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_labels_four_work_registers(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        result = self.service.label_work_registers(
            input_rows=rows,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )
        self.assertIsNotNone(result)

        assert result is not None
        self.assertEqual(result[2][0], "LM_4P_WORK_REG[0]")
        self.assertEqual(result[2][2], "Liquid Mud #4-P Tank Input")
        self.assertEqual(result[5][0], "LM_4P_WORK_REG[3]")
        self.assertEqual(result[5][2], "Liquid Mud #4-P Tank Output")

    def test_idempotent_rerun(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        first = self.service.label_work_registers(
            input_rows=rows,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )
        second = self.service.label_work_registers(
            input_rows=first,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )
        self.assertEqual(first, second)


class ArrayifyWorkRegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = TankRules()
        self.config = ProjectConfig(root=Path("/tmp"))
        self.csv_repository = CsvRepository()
        self.work_reg_service = TankWorkRegService(self.config, self.csv_repository, self.rules)
        self.arrayify_service = ArrayifyService(self.config, self.csv_repository, self.rules)
        self._temp_dir = TemporaryDirectory()
        self.prefix_path = Path(self._temp_dir.name) / "prefix.csv"
        self.csv_repository.write_rows(self.prefix_path, [["Name", "Type", "Description"]])

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_arrayify_preserves_volume_and_work_registers(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        labeled = self.work_reg_service.label_work_registers(
            input_rows=rows,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )
        output = self.arrayify_service.arrayify_points(input_rows=labeled, write_output=False, keep_other_values=False)

        assert output is not None
        names = [row[0] for row in output[1:]]
        self.assertIn("R100", names)
        self.assertIn("LM_4P_WORK_REG[0]", names)
        self.assertIn("LM_4P_WORK_REG[3]", names)
        self.assertTrue(any(name.startswith("R105[") for name in names))


class RowChangeTrackerTests(unittest.TestCase):
    def test_export_only_modified_rows(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[1][2] = "Changed"

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        export_rows = tracker.rows_for_export(current)

        self.assertEqual(len(export_rows), 2)
        self.assertEqual(export_rows[1][0], "R100")

    def test_export_includes_new_register_names(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current.append(make_row("R999", "New row"))

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        export_rows = tracker.rows_for_export(current)

        exported_names = {row[0] for row in export_rows[1:]}
        self.assertIn("R999", exported_names)
        self.assertNotIn("R101", exported_names)


class NormalizeWorkRegSkipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = TankRules()
        self.config = ProjectConfig(root=Path("/tmp"))
        self.csv_repository = CsvRepository()
        self.work_reg_service = TankWorkRegService(self.config, self.csv_repository, self.rules)
        self.normalize_service = TagNormalizationService(self.config, self.csv_repository, self.rules)
        self._temp_dir = TemporaryDirectory()
        self.prefix_path = Path(self._temp_dir.name) / "prefix.csv"
        self.csv_repository.write_rows(
            self.prefix_path,
            [
                ["Name", "Type", "Description"],
                ["LM_4P_LEVEL", "REAL", "Liquid Mud #4-P Tank Volume"],
            ],
        )

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_normalize_skips_work_reg_tags(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        labeled = self.work_reg_service.label_work_registers(
            input_rows=rows,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )

        result = self.normalize_service.normalize_tags(
            input_rows=labeled,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )

        assert result is not None
        self.assertEqual(result[2][0], "LM_4P_WORK_REG[0]")
        self.assertEqual(result[3][0], "LM_4P_WORK_REG[1]")
        self.assertTrue(result[6][0].startswith("LM_4P_TANK_TABLE"))
        self.assertNotEqual(result[2][0], result[6][0])


if __name__ == "__main__":
    unittest.main()
