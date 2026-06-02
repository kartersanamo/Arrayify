from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from tank_tools.change_tracker import RowChangeTracker
from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.models import WorkRegMatch, WorkRegMiss
from tank_tools.output_format import bullet_prefix, sub_bullet_prefix
from tank_tools.rules import TankRules


class TankWorkRegService:
    WORK_REG_COUNT = 4

    def __init__(self, config: ProjectConfig, csv_repository: CsvRepository, rules: TankRules) -> None:
        self._config = config
        self._csv_repository = csv_repository
        self._rules = rules

    def label_work_registers(
        self,
        input_path: Path | None = None,
        output_path: Path | None = None,
        input_rows: list[list[str]] | None = None,
        tag_prefix_input_path: Path | None = None,
        write_output: bool = True,
        cli_style: bool = True,
        event_callback: Callable[[dict[str, object]], None] | None = None,
        custom_tag_provider: Callable[[str], str | None] | None = None,
        change_tracker: RowChangeTracker | None = None,
    ) -> list[list[str]] | None:
        print("Labeling work registers....")

        if input_rows is None:
            source_path = input_path or self._config.input_csv_path
            if not source_path.is_file():
                print(f"Input file not found: {source_path}")
                return None
            rows = self._csv_repository.read_rows(source_path)
            if not rows:
                print(f"Input file is empty: {source_path}")
                return None
        else:
            rows = input_rows

        if not rows:
            print("Input rows are empty.")
            return None

        output_path = output_path or self._config.files_dir / f"{self._config.input_stem}_work_regs.csv"
        if write_output and output_path.exists():
            print(f"Conflicting output file path: {output_path}")
            return None

        tag_prefix_source = tag_prefix_input_path or self._config.input_csv_path
        if not tag_prefix_source.is_file():
            print(f"Tag prefix source file not found: {tag_prefix_source}")
            return None

        prefix_map = self._rules.load_tag_prefix_map(self._csv_repository.read_rows(tag_prefix_source))
        custom_prefix_map: dict[str, str] = {}
        prompted_descriptions: set[str] = set()
        matched_rows: list[WorkRegMatch] = []
        missed_rows: list[WorkRegMiss] = []
        labeled_count = 0

        row_index = 1
        while row_index < len(rows):
            row = rows[row_index]
            if len(row) <= 2 or not self._rules.is_register_name(row[0]) or "[" in row[0]:
                row_index += 1
                continue

            volume_description = row[2].strip()
            if not self._rules.is_tank_volume_description(volume_description):
                row_index += 1
                continue

            work_row_indices = self._collect_work_register_indices(rows, row_index + 1)
            if work_row_indices is None:
                print(
                    f"Skipping work registers for '{volume_description}': "
                    f"expected {self.WORK_REG_COUNT} consecutive empty register rows."
                )
                missed_rows.append(
                    WorkRegMiss(
                        volume_description=volume_description,
                        reason=f"expected {self.WORK_REG_COUNT} empty register rows below volume row",
                    )
                )
                row_index += 1
                continue

            prefix = self._resolve_prefix(
                volume_description,
                prefix_map,
                custom_prefix_map,
                prompted_descriptions,
                custom_tag_provider,
            )
            if prefix is None:
                missed_rows.append(
                    WorkRegMiss(
                        volume_description=volume_description,
                        reason="no tag prefix match",
                    )
                )
                row_index += 1
                continue

            tank_label = self._rules.tank_label_from_volume_description(volume_description)
            for offset, work_row_index in enumerate(work_row_indices):
                work_row = rows[work_row_index]
                source_register = work_row[0].split("[", 1)[0]
                tag = self._rules.build_work_reg_tag(prefix, offset)
                work_description = self._rules.build_work_reg_description(tank_label, offset)
                work_row[0] = tag
                work_row[2] = work_description
                if len(work_row) > 15:
                    work_row[15] = ""
                labeled_count += 1
                matched_rows.append(
                    WorkRegMatch(
                        volume_description=volume_description,
                        register=source_register,
                        tag=tag,
                        description=work_description,
                    )
                )

            if event_callback is not None:
                event_callback(
                    {
                        "type": "preview",
                        "workflow": "work_regs",
                        "description": volume_description,
                        "rows": [list(item) for item in rows],
                    }
                )

            row_index = work_row_indices[-1] + 1

        self._print_summary(matched_rows, missed_rows, cli_style)
        if write_output:
            self._csv_repository.write_rows(output_path, rows)
            print(f"Labeled {labeled_count} work register rows.")
            print(f"Wrote work register CSV to {output_path}")
        else:
            print(f"Labeled {labeled_count} work register rows.")

        if event_callback is not None:
            event_callback({"type": "completed", "workflow": "work_regs", "rows": [list(item) for item in rows]})

        return rows

    def _collect_work_register_indices(self, rows: list[list[str]], start_index: int) -> list[int] | None:
        labeled_indices = self._collect_labeled_work_register_indices(rows, start_index)
        if labeled_indices is not None:
            return labeled_indices

        indices: list[int] = []
        scan_index = start_index

        while scan_index < len(rows) and len(indices) < self.WORK_REG_COUNT:
            current_row = rows[scan_index]
            if len(current_row) <= 2 or not self._rules.is_register_name(current_row[0]) or "[" in current_row[0]:
                break

            if current_row[2].strip():
                break

            indices.append(scan_index)
            scan_index += 1

        if len(indices) != self.WORK_REG_COUNT:
            return None

        return indices

    def _collect_labeled_work_register_indices(self, rows: list[list[str]], start_index: int) -> list[int] | None:
        indices: list[int] = []
        expected_index = 0

        for scan_index in range(start_index, min(start_index + self.WORK_REG_COUNT, len(rows))):
            current_row = rows[scan_index]
            if len(current_row) <= 2 or not self._rules.is_work_reg_tag(current_row[0]):
                return None

            match = re.match(r"^.+_WORK_REG\[(\d+)\]$", current_row[0])
            if match is None or int(match.group(1)) != expected_index:
                return None

            indices.append(scan_index)
            expected_index += 1

        if len(indices) != self.WORK_REG_COUNT:
            return None

        return indices

    def _resolve_prefix(
        self,
        volume_description: str,
        prefix_map: dict[str, str],
        custom_prefix_map: dict[str, str],
        prompted_descriptions: set[str],
        custom_tag_provider: Callable[[str], str | None] | None,
    ) -> str | None:
        if volume_description in custom_prefix_map:
            return custom_prefix_map[volume_description]

        prefix = self._rules.volume_description_to_work_reg_prefix(volume_description, prefix_map)
        if prefix is not None:
            return prefix

        if volume_description not in prompted_descriptions:
            prompted_descriptions.add(volume_description)
            if custom_tag_provider is None:
                custom_input = input(
                    f"No work-reg prefix for '{volume_description}'. "
                    "Enter a custom tag prefix, or press Enter to leave it unchanged: "
                ).strip()
            else:
                custom_input = (custom_tag_provider(volume_description) or "").strip()

            if custom_input:
                custom_prefix = self._rules.format_custom_work_reg_prefix(custom_input)
                if custom_prefix is None:
                    print(f"Skipping '{volume_description}' because the custom prefix was empty.")
                else:
                    custom_prefix_map[volume_description] = custom_prefix
                    return custom_prefix

        return custom_prefix_map.get(volume_description)

    @staticmethod
    def _print_summary(
        matched_rows: list[WorkRegMatch],
        missed_rows: list[WorkRegMiss],
        cli_style: bool = True,
    ) -> None:
        bullet = bullet_prefix(cli_style)
        sub_bullet = sub_bullet_prefix(cli_style)
        print("Work register summary:")

        if matched_rows:
            grouped: dict[str, list[WorkRegMatch]] = {}
            for item in matched_rows:
                grouped.setdefault(item.volume_description, []).append(item)

            print("Labeled tanks:")
            for volume_description, items in grouped.items():
                print(f"{bullet}{volume_description} ({len(items)} registers)")
                for item in items[:2]:
                    print(f"{sub_bullet}{item.register} | {item.description} -> {item.tag}")
                if len(items) > 2:
                    print(f"{sub_bullet}...")
        else:
            print("Labeled tanks: none")

        if missed_rows:
            print("Skipped tanks:")
            for item in missed_rows:
                print(f"{bullet}{item.volume_description}: {item.reason}")
        else:
            print("Skipped tanks: none")
