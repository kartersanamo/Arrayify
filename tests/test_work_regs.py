from __future__ import annotations

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tank_tools.change_tracker import ExportPlan, RowChangeTracker
from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import ArrayifyService, TagNormalizationService, TankWorkRegService
from tank_tools.work_reg_registry import scan_work_register_bindings


def make_row(register: str, description: str = "", initial: str = "0") -> list[str]:
    row = [""] * 16
    row[0] = register
    row[1] = "REAL"
    row[2] = description
    row[12] = initial
    row[15] = "%R00101"
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


class WorkRegRegistryTests(unittest.TestCase):
    def test_scan_bindings_from_raw_layout(self) -> None:
        rows = build_lm4p_block()
        bindings = scan_work_register_bindings(rows, TankRules())
        self.assertEqual(
            bindings["Liquid Mud #4-P Tank Volume"],
            ["R101", "R102", "R103", "R104"],
        )

    def test_scan_bindings_when_work_registers_follow_sounding_block(self) -> None:
        header = ["Name", "Type", "Description"] + [""] * 13
        rows = [header, make_row("R100", "Ballast Anti Roll #2 Tank Volume")]
        rows.append(make_row("R101", "Ballast Anti Roll #2 Tank Volume @ 0", "1.0"))
        rows.append(make_row("R102", "Ballast Anti Roll #2 Tank Volume @ 1", "2.0"))
        rows.extend([make_row("R103"), make_row("R104"), make_row("R105"), make_row("R106")])

        bindings = scan_work_register_bindings(rows, TankRules())
        self.assertEqual(
            bindings["Ballast Anti Roll #2 Tank Volume"],
            ["R103", "R104", "R105", "R106"],
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
        self.bindings = scan_work_register_bindings(build_lm4p_block(), self.rules)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_labels_work_registers_after_sounding_block(self) -> None:
        header = ["Name", "Type", "Description"] + [""] * 13
        rows = [
            header,
            make_row("R100", "Ballast Anti Roll #2 Tank Volume"),
            make_row("R101", "Ballast Anti Roll #2 Tank Volume @ 0", "1.0"),
            make_row("R102", "Ballast Anti Roll #2 Tank Volume @ 1", "2.0"),
            make_row("R103"),
            make_row("R104"),
            make_row("R105"),
            make_row("R106"),
        ]
        bindings = scan_work_register_bindings(rows, self.rules)

        result = self.service.label_work_registers(
            bindings,
            input_rows=copy.deepcopy(rows),
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )

        assert result is not None
        by_name = {row[0]: row for row in result[1:]}
        self.assertEqual(by_name["BS_AR2_WORK_REG[0]"][2], "Ballast Anti Roll #2 Tank Input")
        self.assertEqual(by_name["BS_AR2_WORK_REG[3]"][15], "")

    def test_labels_work_registers_by_saved_bindings(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        arrayified = self._simulate_arrayify_reorder(rows)

        result = self.service.label_work_registers(
            self.bindings,
            input_rows=arrayified,
            tag_prefix_input_path=self.prefix_path,
            write_output=False,
        )

        assert result is not None
        by_name = {row[0]: row for row in result[1:]}
        self.assertEqual(by_name["LM_4P_WORK_REG[0]"][2], "Liquid Mud #4-P Tank Input")
        self.assertEqual(by_name["LM_4P_WORK_REG[3]"][15], "")
        self.assertEqual(by_name["LM_4P_WORK_REG[0]"][15], "")

    def _simulate_arrayify_reorder(self, rows: list[list[str]]) -> list[list[str]]:
        """Place volume + work rows away from their original indices but keep register names."""
        header = rows[0]
        volume = rows[1]
        work = rows[2:6]
        sounding = rows[6:]
        return [header, *sounding, volume, *work]


class ArrayifyWorkRegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = TankRules()
        self.config = ProjectConfig(root=Path("/tmp"))
        self.csv_repository = CsvRepository()
        self.arrayify_service = ArrayifyService(self.config, self.csv_repository, self.rules)

    def test_arrayify_preserves_volume_and_unlabeled_work_registers(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        output = self.arrayify_service.arrayify_points(input_rows=rows, write_output=False)

        assert output is not None
        names = [row[0] for row in output[1:]]
        self.assertIn("R100", names)
        self.assertIn("R101", names)
        self.assertIn("R104", names)
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

    def test_dual_export_when_name_and_ioaddress_change(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[2][0] = "LM_4P_WORK_REG[0]"
        current[2][2] = "Liquid Mud #4-P Tank Input"
        current[2][15] = ""

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        bindings = scan_work_register_bindings(baseline, TankRules())
        plan = tracker.export_plan(current, work_reg_bindings=bindings)

        self.assertTrue(plan.needs_dual_export)
        self.assertEqual(plan.first_pass_rows[1][0], "LM_4P_WORK_REG[0]")
        self.assertEqual(plan.first_pass_rows[1][15], "%R00101")
        self.assertEqual(plan.second_pass_rows[1][15], "")

    def test_dual_export_paths(self) -> None:
        first_path, second_path = ExportPlan.export_paths(Path("/tmp/export.csv"))
        self.assertEqual(first_path.name, "export-FIRST.csv")
        self.assertEqual(second_path.name, "export-SECOND.csv")

    def test_single_export_when_only_description_changes(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[1][2] = "Changed description"

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(current)

        self.assertFalse(plan.needs_dual_export)
        self.assertEqual(plan.first_pass_rows, plan.second_pass_rows)

    def test_first_pass_restores_io_for_arrayify_rename(self) -> None:
        baseline = build_lm4p_block()
        baseline[6][15] = "%R00105"
        current = copy.deepcopy(baseline)
        current[6][0] = "R105[0]"
        current[6][2] = "Liquid Mud #4-P Tank Volume @ 0"
        current[6][15] = "%R00200"

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(current)

        self.assertTrue(plan.needs_dual_export)
        self.assertEqual(plan.first_pass_rows[1][0], "R105[0]")
        self.assertEqual(plan.first_pass_rows[1][15], "%R00105")
        self.assertEqual(plan.second_pass_rows[1][15], "%R00200")

    def test_first_pass_keeps_original_io_when_arrayify_clears_io(self) -> None:
        baseline = build_lm4p_block()
        baseline[6][15] = "%R00105"
        current = copy.deepcopy(baseline)
        current[6][0] = "LM_4P_TANK_TABLE[0]"
        current[6][2] = "Liquid Mud #4-P Tank Volume @ 0"
        current[6][15] = ""

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(current)

        self.assertTrue(plan.needs_dual_export)
        self.assertEqual(plan.first_pass_rows[1][0], "LM_4P_TANK_TABLE[0]")
        self.assertEqual(plan.first_pass_rows[1][15], "%R00105")
        self.assertEqual(plan.second_pass_rows[1][15], "")

    def test_io_only_change_does_not_restore_baseline_io(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[1][15] = "%R99999"

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(current)

        self.assertFalse(plan.needs_dual_export)
        self.assertEqual(plan.first_pass_rows[1][15], "%R99999")
        self.assertEqual(plan.first_pass_rows, plan.second_pass_rows)

    def test_export_synthesizes_array_parent_row(self) -> None:
        header = ["Name", "Type", "Description"] + [""] * 13
        baseline = [
            header,
            make_row("R105", "Liquid Mud #4-P Tank Volume", "1.0"),
            make_row("R106"),
            make_row("R107"),
            make_row("R108"),
        ]
        current = copy.deepcopy(baseline)
        for offset in range(4):
            current[offset + 1][0] = f"R105[{offset}]"
            current[offset + 1][2] = f"Liquid Mud #4-P Tank Volume @ {offset}"
            current[offset + 1][12] = str(offset + 1)

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(current)

        exported = plan.second_pass_rows[1:]
        exported_by_name = {row[0]: row for row in exported}

        self.assertIn("R105", exported_by_name)
        self.assertEqual(exported_by_name["R105"][7], "4")
        self.assertEqual(exported_by_name["R105"][12], "0, 0, 0, 0")
        self.assertEqual([row[0] for row in exported[:5]], ["R105", "R105[0]", "R105[1]", "R105[2]", "R105[3]"])

    def test_work_registers_only_export_excludes_other_changes(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[1][2] = "Changed volume description"
        current[2][0] = "LM_4P_WORK_REG[0]"
        current[2][2] = "Liquid Mud #4-P Tank Input"
        current[3][0] = "LM_4P_WORK_REG[1]"
        current[3][2] = "Liquid Mud #4-P Tank Total"

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        bindings = scan_work_register_bindings(baseline, TankRules())
        plan = tracker.export_plan(current, work_reg_bindings=bindings, work_registers_only=True)

        exported_names = {row[0] for row in plan.second_pass_rows[1:]}
        self.assertEqual(exported_names, {"LM_4P_WORK_REG[0]", "LM_4P_WORK_REG[1]"})
        self.assertNotIn("R100", exported_names)


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
        self.bindings = scan_work_register_bindings(build_lm4p_block(), self.rules)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_normalize_skips_work_reg_tags(self) -> None:
        rows = copy.deepcopy(build_lm4p_block())
        labeled = self.work_reg_service.label_work_registers(
            self.bindings,
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
