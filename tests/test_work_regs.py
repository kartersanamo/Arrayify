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


def make_row(
    register: str,
    description: str = "",
    initial: str = "0",
    dtype: str = "REAL",
    io: str = "%R00101",
) -> list[str]:
    row = [""] * 16
    row[0] = register
    row[1] = dtype
    row[2] = description
    row[12] = initial
    row[15] = io
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
        self.assertTrue(self.rules.is_work_reg_tag("LM_4P_WORK_REG_2"))
        self.assertTrue(self.rules.is_work_reg_tag("LM_4P_WORK_REG[2]"))
        self.assertEqual(
            self.rules.build_work_reg_tag("LM_4P", 0),
            "LM_4P_WORK_REG_0",
        )
        self.assertEqual(
            self.rules.build_work_reg_description("Liquid Mud #4-P", 0),
            "Liquid Mud #4-P Register # 0",
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
        self.assertEqual(by_name["BS_AR2_WORK_REG_0"][1], "INT")
        self.assertEqual(by_name["BS_AR2_WORK_REG_0"][2], "Ballast Anti Roll #2 Register # 0")
        self.assertEqual(by_name["BS_AR2_WORK_REG_3"][15], "")

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
        self.assertEqual(by_name["LM_4P_WORK_REG_0"][1], "INT")
        self.assertEqual(by_name["LM_4P_WORK_REG_0"][2], "Liquid Mud #4-P Register # 0")
        self.assertEqual(by_name["LM_4P_WORK_REG_3"][15], "")
        self.assertEqual(by_name["LM_4P_WORK_REG_0"][15], "")

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
        current[2][2] = "Liquid Mud #4-P Register # 0"
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

    def test_labeled_dual_export_paths(self) -> None:
        paths = ExportPlan.export_paths(
            Path("/tmp/JuneThird.csv"),
            2,
            ("BYREF-FIRST", "BYNAME-SECOND"),
        )
        self.assertEqual(paths[0].name, "JuneThird-BYREF-FIRST.csv")
        self.assertEqual(paths[1].name, "JuneThird-BYNAME-SECOND.csv")

    def test_dual_export_uses_byref_byname_labels(self) -> None:
        baseline = build_lm4p_block()
        current = copy.deepcopy(baseline)
        current[2][0] = TankRules.build_work_reg_tag("LM_4P", 0)
        current[2][2] = "Liquid Mud #4-P Register # 0"
        current[2][15] = ""

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        bindings = scan_work_register_bindings(baseline, TankRules())
        plan = tracker.export_plan(current, work_reg_bindings=bindings)

        self.assertTrue(plan.needs_dual_export)
        assert plan.pass_file_labels == ("BYREF-FIRST", "BYNAME-SECOND")
        assert plan.pass_match_hints == (
            "Match by Ref Address And Data Type",
            "Match by Variable Name",
        )
        self.assertEqual(plan.first_pass_rows[1][0], "LM_4P_WORK_REG_0")
        self.assertEqual(plan.first_pass_rows[1][15], "%R00101")
        self.assertEqual(plan.second_pass_rows[1][1], "INT")
        self.assertEqual(plan.second_pass_rows[1][15], "")

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
        tank_label = "Liquid Mud #4-P"
        for offset in range(4):
            current[offset + 2][0] = TankRules.build_work_reg_tag("LM_4P", offset)
            current[offset + 2][1] = "INT"
            current[offset + 2][2] = TankRules.build_work_reg_description(tank_label, offset)
            current[offset + 2][15] = ""

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        bindings = scan_work_register_bindings(baseline, TankRules())
        plan = tracker.export_plan(current, work_reg_bindings=bindings, work_registers_only=True)

        final_rows = plan._final_pass_rows()
        exported_names = {row[0] for row in final_rows[1:]}
        self.assertIn("LM_4P_WORK_REG_0", exported_names)
        self.assertIn("LM_4P_WORK_REG_3", exported_names)
        self.assertNotIn("R100", exported_names)

    def test_work_register_two_pass_export_when_index_zero_is_word(self) -> None:
        header = ["Name", "Type", "Description"] + [""] * 13
        baseline = [
            header,
            make_row("R10240", dtype="WORD", io="%R10240"),
            make_row("R10241", dtype="INT", io="%R10241"),
            make_row("R10242", dtype="INT", io="%R10242"),
            make_row("R10243", dtype="INT", io="%R10243"),
        ]
        bindings = {"Fuel Oil #2-P Tank Volume": ["R10240", "R10241", "R10242", "R10243"]}
        prefix = "FO_2P"
        tank_label = "Fuel Oil #2-P"
        current = [header]
        for offset in range(4):
            current.append(
                make_row(
                    TankRules.build_work_reg_tag(prefix, offset),
                    TankRules.build_work_reg_description(tank_label, offset),
                    dtype="INT",
                    io="",
                )
            )

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(
            current,
            work_reg_bindings=bindings,
            work_registers_only=True,
        )

        self.assertEqual(plan.pass_count, 2)
        assert plan.pass_file_labels == ("BYREF-FIRST", "BYNAME-SECOND")

        byref_rows = plan.first_pass_rows[1:]
        self.assertEqual(len(byref_rows), 4)
        byref_by_name = {row[0]: row for row in byref_rows}
        self.assertEqual(byref_by_name[f"{prefix}_WORK_REG_0"][1], "WORD")
        self.assertEqual(byref_by_name[f"{prefix}_WORK_REG_0"][15], "%R10240")
        self.assertEqual(byref_by_name[f"{prefix}_WORK_REG_1"][15], "%R10241")

        byname_rows = plan.second_pass_rows[1:]
        self.assertEqual(len(byname_rows), 4)
        byname_by_name = {row[0]: row for row in byname_rows}
        self.assertEqual(byname_by_name[f"{prefix}_WORK_REG_0"][1], "INT")
        self.assertEqual(byname_by_name[f"{prefix}_WORK_REG_0"][15], "")

        paths = ExportPlan.export_paths(
            Path("/tmp/RegsOnly.csv"),
            plan.pass_count,
            plan.pass_file_labels,
        )
        self.assertEqual(paths[0].name, "RegsOnly-BYREF-FIRST.csv")
        self.assertEqual(paths[1].name, "RegsOnly-BYNAME-SECOND.csv")

    def test_work_register_two_pass_export_when_all_baseline_types_are_int(self) -> None:
        header = ["Name", "Type", "Description"] + [""] * 13
        baseline = [
            header,
            make_row("R27240", dtype="INT", io="%R27240"),
            make_row("R27241", dtype="INT", io="%R27241"),
            make_row("R27242", dtype="INT", io="%R27242"),
            make_row("R27243", dtype="INT", io="%R27243"),
        ]
        bindings = {"Methanol Pump Void #1-S Volume": ["R27240", "R27241", "R27242", "R27243"]}
        tank_label = "Methanol Pump Void #1-S"
        current = [header]
        for offset in range(4):
            current.append(
                make_row(
                    TankRules.build_work_reg_tag("ME_1S", offset),
                    TankRules.build_work_reg_description(tank_label, offset),
                    dtype="INT",
                    io="",
                )
            )

        tracker = RowChangeTracker(copy.deepcopy(baseline))
        plan = tracker.export_plan(
            current,
            work_reg_bindings=bindings,
            work_registers_only=True,
        )

        self.assertEqual(plan.pass_count, 2)
        assert plan.pass_file_labels == ("BYREF-FIRST", "BYNAME-SECOND")
        self.assertEqual(len(plan.first_pass_rows[1:]), 4)
        byref_by_name = {row[0]: row for row in plan.first_pass_rows[1:]}
        self.assertEqual(byref_by_name["ME_1S_WORK_REG_0"][1], "INT")
        self.assertEqual(byref_by_name["ME_1S_WORK_REG_0"][15], "%R27240")
        byname_by_name = {row[0]: row for row in plan.second_pass_rows[1:]}
        self.assertEqual(byname_by_name["ME_1S_WORK_REG_0"][15], "")


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
        names = [row[0] for row in result[1:]]
        self.assertIn("LM_4P_WORK_REG_0", names)
        self.assertIn("LM_4P_WORK_REG_1", names)
        self.assertTrue(any(name.startswith("LM_4P_TANK_TABLE") for name in names))


if __name__ == "__main__":
    unittest.main()
