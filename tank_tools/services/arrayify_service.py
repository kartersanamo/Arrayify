from __future__ import annotations

from pathlib import Path
from typing import Callable

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.models import ArrayifySummaryRow
from tank_tools.rules import TankRules
from tank_tools.work_reg_registry import (
    WORK_REG_COUNT,
    _collect_empty_work_register_names,
    _find_sounding_block_end,
)


class ArrayifyService:
    def __init__(self, config: ProjectConfig, csv_repository: CsvRepository, rules: TankRules) -> None:
        self._config = config
        self._csv_repository = csv_repository
        self._rules = rules

    def arrayify_points(
        self,
        input_path: Path | None = None,
        output_path: Path | None = None,
        input_rows: list[list[str]] | None = None,
        write_output: bool = True,
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[list[str]] | None:
        print("Array-ify-ing...")

        input_path = input_path or self._config.input_csv_path
        output_path = output_path or self._config.arrayified_csv_path

        if event_callback is not None:
            event_callback({"type": "status", "message": "Starting arrayify workflow."})

        if input_rows is None and not input_path.is_file():
            print(f"Input file not found: {input_path}")
            return

        if write_output and output_path.exists():
            print(f"Conflicting output file path: {output_path}")
            return

        rows = input_rows if input_rows is not None else self._csv_repository.read_rows(input_path)
        if not rows:
            print("Input file is empty.")
            return

        output_rows: list[list[str]] = [rows[0]]
        summary_rows: list[ArrayifySummaryRow] = []
        row_index = 1

        while row_index < len(rows):
            row = rows[row_index]
            if len(row) <= 15 or not self._rules.is_register_name(row[0]):
                output_rows.append(row.copy())
                row_index += 1
                continue

            if self._rules.is_work_reg_tag(row[0]):
                output_rows.append(row.copy())
                row_index += 1
                continue

            description_match = self._rules.tank_description_re.match(row[2])
            if not description_match or description_match.group(2) != "0":
                output_rows.append(row.copy())
                row_index += 1
                continue

            base_description = description_match.group(1)
            base_register = int(row[0][1:])
            backward_affiliates = self._collect_backward_affiliate_rows(rows, row_index, base_description)
            forward_affiliates = (
                None
                if backward_affiliates is not None
                else self._collect_forward_affiliate_rows(rows, row_index, base_description)
            )

            block_rows: list[list[str]] = []
            expected_index = 0
            scan_index = row_index

            while scan_index < len(rows):
                current_row = rows[scan_index]
                if len(current_row) <= 15 or not self._rules.is_register_name(current_row[0]):
                    break

                current_description_match = self._rules.tank_description_re.match(current_row[2])
                if not current_description_match:
                    break

                current_register = int(current_row[0][1:])
                current_description_index = int(current_description_match.group(2))

                if (
                    current_description_match.group(1) != base_description
                    or current_description_index != expected_index
                    or current_register != base_register + expected_index
                ):
                    break

                block_rows.append(current_row)
                expected_index += 1
                scan_index += 1

            if len(block_rows) <= 1:
                output_rows.append(row.copy())
                row_index += 1
                continue

            target_length = self._rules.round_up_to_25(len(block_rows))
            last_real_initial_value = block_rows[-1][12]

            summary_rows.append(
                ArrayifySummaryRow(
                    register=row[0],
                    description=base_description,
                    points_found=len(block_rows),
                    points_allocated=target_length,
                )
            )

            if backward_affiliates is not None:
                for affiliate_row in backward_affiliates:
                    output_rows.append(affiliate_row)

            output_rows.append(self._build_base_row(block_rows[0], base_description, target_length))

            if event_callback is not None:
                event_callback(
                    {
                        "type": "preview",
                        "workflow": "arrayify",
                        "register": row[0],
                        "description": base_description,
                        "rows": output_rows.copy(),
                    }
                )

            for index in range(target_length):
                source_row = block_rows[index] if index < len(block_rows) else block_rows[-1]
                output_rows.append(
                    self._build_array_row(
                        source_row=source_row,
                        base_register=base_register,
                        base_description=base_description,
                        index=index,
                        is_padded=index >= len(block_rows),
                        padded_initial_value=last_real_initial_value,
                    )
                )

            if forward_affiliates is not None:
                for work_row in forward_affiliates[1:]:
                    output_rows.append(work_row)
                row_index = scan_index + WORK_REG_COUNT
            else:
                row_index = scan_index

        self._print_summary(summary_rows)
        if write_output:
            self._csv_repository.write_rows(output_path, output_rows)
            print(f"Wrote {len(output_rows) - 1} modified rows to {output_path}")

        if event_callback is not None:
            event_callback({"type": "completed", "workflow": "arrayify", "rows": output_rows.copy()})

        return output_rows

    def _collect_backward_affiliate_rows(
        self,
        rows: list[list[str]],
        at_index: int,
        base_description: str,
    ) -> list[list[str]] | None:
        tank_label = self._rules.tank_label_from_volume_description(base_description)
        work_rows: list[list[str]] = []
        scan_index = at_index - 1

        while scan_index >= 1 and len(work_rows) < WORK_REG_COUNT:
            current_row = rows[scan_index]
            if not self._is_affiliate_work_row(current_row, tank_label):
                break

            work_rows.insert(0, current_row.copy())
            scan_index -= 1

        if len(work_rows) != WORK_REG_COUNT:
            return None

        volume_index = scan_index
        if volume_index < 1:
            return None

        volume_row = rows[volume_index]
        if len(volume_row) <= 2 or volume_row[2].strip() != base_description:
            return None

        if not self._rules.is_register_name(volume_row[0]) or "[" in volume_row[0]:
            return None

        return [volume_row.copy(), *work_rows]

    def _collect_forward_affiliate_rows(
        self,
        rows: list[list[str]],
        at_index: int,
        base_description: str,
    ) -> list[list[str]] | None:
        block_end = _find_sounding_block_end(rows, at_index, base_description, self._rules)
        if block_end is None:
            return None

        register_names = _collect_empty_work_register_names(rows, block_end, self._rules)
        if register_names is None:
            return None

        volume_row = self._find_volume_row_before_block(rows, at_index, base_description)
        if volume_row is None:
            return None

        work_rows = [rows[block_end + offset].copy() for offset in range(WORK_REG_COUNT)]
        return [volume_row.copy(), *work_rows]

    def _find_volume_row_before_block(
        self,
        rows: list[list[str]],
        block_start: int,
        base_description: str,
    ) -> list[str] | None:
        for row_index in range(block_start - 1, 0, -1):
            row = rows[row_index]
            if len(row) <= 2 or not self._rules.is_register_name(row[0]) or "[" in row[0]:
                continue

            if row[2].strip() != base_description:
                continue

            return row

        return None

    def _is_affiliate_work_row(self, row: list[str], tank_label: str) -> bool:
        if len(row) <= 2:
            return False

        name = row[0]
        description = row[2].strip()

        if self._rules.is_work_reg_tag(name):
            return True

        if not self._rules.is_register_name(name) or "[" in name:
            return False

        if not description:
            return True

        return description.startswith(f"{tank_label} Tank ")

    def _build_array_row(
        self,
        source_row: list[str],
        base_register: int,
        base_description: str,
        index: int,
        is_padded: bool,
        padded_initial_value: str | None = None,
    ) -> list[str]:
        row = source_row.copy()
        row[0] = f"R{base_register}[{index}]"
        row[2] = f"{base_description} @ {index}"
        row[15] = f"%R{base_register:05d}"

        if is_padded:
            row[12] = padded_initial_value if padded_initial_value is not None else self._rules.default_initial_value(row[1])

        return row

    @staticmethod
    def _build_base_row(source_row: list[str], base_description: str, target_length: int) -> list[str]:
        row = source_row.copy()
        row[0] = row[0].split("[", 1)[0]
        row[2] = base_description
        row[7] = str(target_length)
        row[12] = ", ".join(["0"] * target_length)
        return row

    @staticmethod
    def _print_summary(summary_rows: list[ArrayifySummaryRow]) -> None:
        print("Arrayify summary:")
        print(f"Total tanks found: {len(summary_rows)}")

        total_points_found = 0
        total_points_allocated = 0

        for item in summary_rows:
            total_points_found += item.points_found
            total_points_allocated += item.points_allocated
            print(
                f"- {item.register} | {item.description} | "
                f"found {item.points_found} -> allocated {item.points_allocated} "
                f"(+{item.points_allocated - item.points_found})"
            )

        print(f"Total points found: {total_points_found}")
        print(f"Total points allocated: {total_points_allocated}")
        print(f"Total padding added: {total_points_allocated - total_points_found}")
