from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tank_tools.rules import WORK_REG_TARGET_TYPE, TankRules
from tank_tools.work_reg_registry import WORK_REG_COUNT

NAME_COLUMN = 0
DATATYPE_COLUMN = 1
ARRAY_DIMENSION_COLUMN = 7
IOADDRESS_COLUMN = 15

_WORK_REG_TAG_INDEX_RE = re.compile(r"^.+_WORK_REG(?:_(\d+)|\[(\d+)\])$")

_PASS_SUFFIXES = ("FIRST", "SECOND", "THIRD", "FOURTH")
WORK_REG_PASS_LABELS = ("BYREF-FIRST", "BYNAME-SECOND")
WORK_REG_PASS_MATCH_MODES = (
    "Match by Ref Address And Data Type",
    "Match by Variable Name",
)


@dataclass(frozen=True)
class ExportPlan:
    first_pass_rows: list[list[str]]
    second_pass_rows: list[list[str]]
    third_pass_rows: list[list[str]] | None = None
    fourth_pass_rows: list[list[str]] | None = None
    pass_count: int = 1
    pass_file_labels: tuple[str, ...] | None = None
    pass_match_hints: tuple[str, ...] | None = None

    @property
    def needs_dual_export(self) -> bool:
        return self.pass_count > 1

    @property
    def modified_row_count(self) -> int:
        return max(0, len(self._final_pass_rows()) - 1)

    def pass_rows(self, pass_index: int) -> list[list[str]]:
        rows_by_pass = (
            self.first_pass_rows,
            self.second_pass_rows,
            self.third_pass_rows,
            self.fourth_pass_rows,
        )
        selected = rows_by_pass[pass_index]
        if selected is None:
            raise IndexError(f"No export pass at index {pass_index}")
        return selected

    def _final_pass_rows(self) -> list[list[str]]:
        if self.pass_count >= 4 and self.fourth_pass_rows is not None:
            return self.fourth_pass_rows
        if self.pass_count >= 3 and self.third_pass_rows is not None:
            return self.third_pass_rows
        return self.second_pass_rows

    def file_labels_for_export(self) -> tuple[str, ...]:
        if self.pass_file_labels is not None:
            return self.pass_file_labels
        return _PASS_SUFFIXES[: self.pass_count]

    @staticmethod
    def export_paths(
        selected_path: Path,
        pass_count: int = 2,
        file_labels: tuple[str, ...] | None = None,
    ) -> tuple[Path, ...]:
        labels = file_labels or _PASS_SUFFIXES[:pass_count]
        return tuple(
            selected_path.with_name(f"{selected_path.stem}-{label}{selected_path.suffix}")
            for label in labels
        )


@dataclass
class RowChangeTracker:
    baseline_rows: list[list[str]]
    rules: TankRules | None = None

    def export_plan(
        self,
        current_rows: list[list[str]],
        work_reg_bindings: dict[str, list[str]] | None = None,
        prefix_map: dict[str, str] | None = None,
        work_registers_only: bool = False,
    ) -> ExportPlan:
        if not current_rows:
            return ExportPlan(first_pass_rows=[], second_pass_rows=[], pass_count=1)

        rules = self.rules or TankRules()
        if work_registers_only and work_reg_bindings:
            return self.work_reg_export_plan(current_rows, work_reg_bindings, prefix_map or {}, rules)
        header = current_rows[0]
        first_pass_rows: list[list[str]] = []
        second_pass_rows: list[list[str]] = []
        needs_dual_export = False

        baseline_by_name = self._index_baseline_rows()
        baseline_by_io = self._index_baseline_by_io()
        baseline_by_sounding = self._index_baseline_by_sounding_key(rules)
        current_names = {self._cell(row, NAME_COLUMN) for row in current_rows[1:] if row}
        renamed_baseline_by_signature = self._index_renamed_baseline_candidates(current_names)
        used_baseline_names: set[str] = set()
        synthesized_array_bases: set[str] = set()

        for current_index, current_row in enumerate(current_rows[1:], start=1):
            if not current_row:
                continue

            baseline_row = self._resolve_baseline_row(
                current_row,
                baseline_by_name,
                baseline_by_io,
                baseline_by_sounding,
                renamed_baseline_by_signature,
                used_baseline_names,
                work_reg_bindings,
                prefix_map or {},
                rules,
            )
            if baseline_row is None:
                if work_registers_only and not self._is_work_register_export_row(
                    current_row, None, work_reg_bindings, rules
                ):
                    continue
                copied_row = self._copy_row(current_row)
                first_pass_rows.append(copied_row)
                second_pass_rows.append(self._copy_row(current_row))
                continue

            if work_registers_only and not self._is_work_register_export_row(
                current_row, baseline_row, work_reg_bindings, rules
            ):
                continue

            synthetic_parent_row = self._build_synthetic_array_parent_row(
                current_rows,
                current_index,
                current_row,
                baseline_row,
                rules,
            )

            if not self._rows_differ(current_row, baseline_row):
                continue

            current_name = self._cell(current_row, NAME_COLUMN)
            if rules.is_work_reg_tag(current_name):
                second_pass_rows.append(self._work_reg_byname_pass_row(current_row))
                if self._io_value(baseline_row):
                    first_pass_rows.append(self._work_reg_byref_pass_row(current_row, baseline_row))
                else:
                    first_pass_rows.append(self._copy_row(current_row))
                if self._rows_differ(first_pass_rows[-1], second_pass_rows[-1]):
                    needs_dual_export = True
                continue

            if synthetic_parent_row is not None:
                first_pass_rows.append(self._copy_row(synthetic_parent_row))
                second_pass_rows.append(self._copy_row(synthetic_parent_row))

            second_row = self._copy_row(current_row)
            second_pass_rows.append(second_row)

            if self._should_restore_baseline_io(baseline_row, current_row):
                first_row = self._build_first_pass_row(baseline_row, current_row)
            else:
                first_row = self._copy_row(current_row)

            first_pass_rows.append(first_row)
            if self._rows_differ(first_row, second_row):
                needs_dual_export = True

        if needs_dual_export:
            return ExportPlan(
                first_pass_rows=[header, *first_pass_rows],
                second_pass_rows=[header, *second_pass_rows],
                pass_count=2,
                pass_file_labels=WORK_REG_PASS_LABELS,
                pass_match_hints=WORK_REG_PASS_MATCH_MODES,
            )

        return ExportPlan(
            first_pass_rows=[header, *first_pass_rows],
            second_pass_rows=[header, *second_pass_rows],
            pass_count=1,
        )

    def work_reg_export_plan(
        self,
        current_rows: list[list[str]],
        work_reg_bindings: dict[str, list[str]],
        prefix_map: dict[str, str],
        rules: TankRules,
    ) -> ExportPlan:
        header = current_rows[0]
        baseline_by_name = self._index_baseline_rows()
        current_by_name = {
            self._cell(row, NAME_COLUMN): row for row in current_rows[1:] if row
        }
        byref_rows: list[list[str]] = []
        byname_rows: list[list[str]] = []
        has_ref_match = False

        for volume_description, register_names in work_reg_bindings.items():
            prefix = rules.volume_description_to_work_reg_prefix(volume_description, prefix_map)
            if prefix is None:
                continue

            for work_index, source_register in enumerate(register_names):
                current_row = self._find_work_reg_current_row(
                    current_by_name, prefix, work_index, rules
                )
                baseline_row = baseline_by_name.get(source_register)
                if current_row is None or baseline_row is None:
                    continue

                if not self._rows_differ(current_row, baseline_row):
                    continue

                byname_rows.append(self._work_reg_byname_pass_row(current_row))

                if self._io_value(baseline_row):
                    has_ref_match = True
                    byref_rows.append(self._work_reg_byref_pass_row(current_row, baseline_row))

        if not byname_rows:
            return ExportPlan(first_pass_rows=[], second_pass_rows=[], pass_count=1)

        if not has_ref_match:
            return ExportPlan(
                first_pass_rows=[header, *byname_rows],
                second_pass_rows=[header, *byname_rows],
                pass_count=1,
                pass_file_labels=("BYNAME-FIRST",),
                pass_match_hints=("Match by Variable Name",),
            )

        return ExportPlan(
            first_pass_rows=[header, *byref_rows],
            second_pass_rows=[header, *byname_rows],
            pass_count=2,
            pass_file_labels=WORK_REG_PASS_LABELS,
            pass_match_hints=WORK_REG_PASS_MATCH_MODES,
        )

    def rows_for_export(
        self,
        current_rows: list[list[str]],
        work_reg_bindings: dict[str, list[str]] | None = None,
        prefix_map: dict[str, str] | None = None,
    ) -> list[list[str]]:
        return self.export_plan(current_rows, work_reg_bindings, prefix_map).second_pass_rows

    def modified_row_count(
        self,
        current_rows: list[list[str]],
        work_reg_bindings: dict[str, list[str]] | None = None,
        prefix_map: dict[str, str] | None = None,
    ) -> int:
        return self.export_plan(current_rows, work_reg_bindings, prefix_map).modified_row_count

    def _resolve_baseline_row(
        self,
        current_row: list[str],
        baseline_by_name: dict[str, list[str]],
        baseline_by_io: dict[str, list[str]],
        baseline_by_sounding: dict[tuple[str, int], list[str]],
        renamed_baseline_by_signature: dict[tuple[str, ...], list[list[str]]],
        used_baseline_names: set[str],
        work_reg_bindings: dict[str, list[str]] | None,
        prefix_map: dict[str, str],
        rules: TankRules,
    ) -> list[str] | None:
        current_name = self._cell(current_row, NAME_COLUMN)
        baseline_row = baseline_by_name.get(current_name)
        if baseline_row is not None:
            return baseline_row

        baseline_row = self._resolve_from_work_reg_bindings(
            current_name,
            baseline_by_name,
            used_baseline_names,
            work_reg_bindings,
            prefix_map,
            rules,
        )
        if baseline_row is not None:
            return baseline_row

        baseline_row = self._resolve_from_array_register(current_name, baseline_by_name, used_baseline_names)
        if baseline_row is not None:
            return baseline_row

        baseline_row = self._resolve_from_sounding_description(
            current_row,
            baseline_by_sounding,
            used_baseline_names,
            rules,
        )
        if baseline_row is not None:
            return baseline_row

        current_io = self._io_value(current_row)
        if current_io:
            baseline_row = baseline_by_io.get(current_io)
            if baseline_row is not None:
                return baseline_row

        register_from_io = self._register_from_io(current_io)
        if register_from_io is not None:
            baseline_row = baseline_by_name.get(register_from_io)
            if baseline_row is not None and register_from_io not in used_baseline_names:
                used_baseline_names.add(register_from_io)
                return baseline_row

        current_signature = self._row_signature(current_row)
        candidates = [
            row
            for row in renamed_baseline_by_signature.get(current_signature, [])
            if self._cell(row, NAME_COLUMN) not in used_baseline_names
        ]
        if len(candidates) != 1:
            return None

        baseline_row = candidates[0]
        used_baseline_names.add(self._cell(baseline_row, NAME_COLUMN))
        return baseline_row

    @staticmethod
    def _is_work_register_export_row(
        current_row: list[str],
        baseline_row: list[str] | None,
        work_reg_bindings: dict[str, list[str]] | None,
        rules: TankRules,
    ) -> bool:
        if rules.is_work_reg_tag(RowChangeTracker._cell(current_row, NAME_COLUMN)):
            return True
        if baseline_row is None or not work_reg_bindings:
            return False

        baseline_name = RowChangeTracker._cell(baseline_row, NAME_COLUMN)
        binding_registers = {
            register for registers in work_reg_bindings.values() for register in registers
        }
        return baseline_name in binding_registers

    @staticmethod
    def _resolve_from_array_register(
        current_name: str,
        baseline_by_name: dict[str, list[str]],
        used_baseline_names: set[str],
    ) -> list[str] | None:
        match = re.match(r"^R(\d+)\[(\d+)\]$", current_name)
        if match is None:
            return None

        source_register = f"R{int(match.group(1)) + int(match.group(2))}"
        if source_register in used_baseline_names:
            return None

        baseline_row = baseline_by_name.get(source_register)
        if baseline_row is None:
            return None

        used_baseline_names.add(source_register)
        return baseline_row

    @staticmethod
    def _build_array_parent_row(
        current_rows: list[list[str]],
        current_index: int,
        current_row: list[str],
        baseline_row: list[str] | None,
        synthesized_array_bases: set[str],
    ) -> list[str] | None:
        if baseline_row is None:
            return None

        current_name = RowChangeTracker._cell(current_row, NAME_COLUMN)
        register_match = re.match(r"^(.+)\[(\d+)\]$", current_name)
        if register_match is None or register_match.group(2) != "0":
            return None

        base_register = register_match.group(1)
        if base_register in synthesized_array_bases:
            return None

        array_length = RowChangeTracker._count_array_block_length(current_rows, current_index, base_register)
        if array_length <= 1:
            return None

        synthesized_array_bases.add(base_register)

        row = RowChangeTracker._copy_row(baseline_row)
        row[NAME_COLUMN] = base_register

        row[2] = RowChangeTracker._derive_array_parent_description(current_row, baseline_row)

        if len(row) <= 12:
            row.extend([""] * (13 - len(row)))

        row[7] = str(array_length)
        row[12] = ", ".join(["0"] * array_length)
        return row

    @staticmethod
    def _resolve_from_sounding_description(
        current_row: list[str],
        baseline_by_sounding: dict[tuple[str, int], list[str]],
        used_baseline_names: set[str],
        rules: TankRules,
    ) -> list[str] | None:
        if len(current_row) <= 2:
            return None

        description_match = rules.tank_description_re.match(current_row[2])
        if description_match is None:
            return None

        sounding_key = (description_match.group(1), int(description_match.group(2)))
        baseline_row = baseline_by_sounding.get(sounding_key)
        if baseline_row is None:
            return None

        baseline_name = RowChangeTracker._cell(baseline_row, NAME_COLUMN)
        if baseline_name in used_baseline_names:
            return None

        used_baseline_names.add(baseline_name)
        return baseline_row

    @staticmethod
    def _resolve_from_work_reg_bindings(
        current_name: str,
        baseline_by_name: dict[str, list[str]],
        used_baseline_names: set[str],
        work_reg_bindings: dict[str, list[str]] | None,
        prefix_map: dict[str, str],
        rules: TankRules,
    ) -> list[str] | None:
        if not work_reg_bindings or not rules.is_work_reg_tag(current_name):
            return None

        tag_match = _WORK_REG_TAG_INDEX_RE.match(current_name)
        if tag_match is None:
            return None

        work_index = int(tag_match.group(1) or tag_match.group(2))
        for volume_description, register_names in work_reg_bindings.items():
            if work_index >= len(register_names):
                continue

            prefix = rules.volume_description_to_work_reg_prefix(volume_description, prefix_map)
            if prefix is None:
                continue

            expected_name = rules.build_work_reg_tag(prefix, work_index)
            legacy_name = f"{prefix}_WORK_REG[{work_index}]"
            if current_name not in (expected_name, legacy_name):
                continue

            source_register = register_names[work_index]
            if source_register in used_baseline_names:
                return None

            baseline_row = baseline_by_name.get(source_register)
            if baseline_row is None:
                return None

            used_baseline_names.add(source_register)
            return baseline_row

        return None

    def _index_baseline_by_sounding_key(self, rules: TankRules) -> dict[tuple[str, int], list[str]]:
        indexed: dict[tuple[str, int], list[str]] = {}
        for row in self.baseline_rows[1:]:
            if len(row) <= 2:
                continue

            description_match = rules.tank_description_re.match(row[2])
            if description_match is None:
                continue

            key = (description_match.group(1), int(description_match.group(2)))
            indexed[key] = row

        return indexed

    def _index_renamed_baseline_candidates(
        self,
        current_names: set[str],
    ) -> dict[tuple[str, ...], list[list[str]]]:
        signature_index: dict[tuple[str, ...], list[list[str]]] = {}
        for baseline_row in self.baseline_rows[1:]:
            if not baseline_row:
                continue

            baseline_name = self._cell(baseline_row, NAME_COLUMN)
            if baseline_name in current_names:
                continue

            signature_index.setdefault(self._row_signature(baseline_row), []).append(baseline_row)

        return signature_index

    def _index_baseline_by_io(self) -> dict[str, list[str]]:
        indexed: dict[str, list[str]] = {}
        for row in self.baseline_rows[1:]:
            if not row:
                continue
            io_value = self._io_value(row)
            if io_value:
                indexed[io_value] = row
        return indexed

    @staticmethod
    def _register_from_io(io_value: str) -> str | None:
        match = re.match(r"^%R0*(\d+)$", io_value.strip(), re.IGNORECASE)
        if match is None:
            return None
        return f"R{match.group(1)}"

    @staticmethod
    def _should_restore_baseline_io(baseline_row: list[str], current_row: list[str]) -> bool:
        name_changed = RowChangeTracker._cell(baseline_row, NAME_COLUMN) != RowChangeTracker._cell(
            current_row, NAME_COLUMN
        )
        io_changed = RowChangeTracker._io_value(baseline_row) != RowChangeTracker._io_value(current_row)
        if not name_changed and io_changed:
            return False
        return True

    @staticmethod
    def _build_first_pass_row(baseline_row: list[str], current_row: list[str]) -> list[str]:
        row = RowChangeTracker._copy_row(current_row)
        row[IOADDRESS_COLUMN] = RowChangeTracker._io_value(baseline_row)
        return row

    @staticmethod
    def _copy_row(row: list[str]) -> list[str]:
        copied = list(row)
        if len(copied) <= IOADDRESS_COLUMN:
            copied.extend([""] * (IOADDRESS_COLUMN + 1 - len(copied)))
        return copied

    def _index_baseline_rows(self) -> dict[str, list[str]]:
        indexed: dict[str, list[str]] = {}
        for row in self.baseline_rows[1:]:
            if not row:
                continue
            indexed[self._cell(row, NAME_COLUMN)] = row
        return indexed

    def _build_synthetic_array_parent_row(
        self,
        current_rows: list[list[str]],
        current_index: int,
        current_row: list[str],
        baseline_row: list[str] | None,
        rules: TankRules,
    ) -> list[str] | None:
        name_match = re.match(r"^(.+)\[(\d+)\]$", self._cell(current_row, NAME_COLUMN))
        if name_match is None or int(name_match.group(2)) != 0:
            return None

        if len(current_row) <= 2:
            return None

        base_name = name_match.group(1)
        if base_name.endswith("_WORK_REG"):
            return None

        base_key = self._derive_array_parent_base(current_row, baseline_row or current_row)
        base_description = base_key if base_key.endswith(" Register") else base_key + " Register"

        description_match = rules.tank_description_re.match(current_row[2])
        if description_match is not None and description_match.group(2) != "0":
            return None

        group_length = 1

        for next_row in current_rows[current_index + 1 :]:
            next_name_match = re.match(r"^(.+)\[(\d+)\]$", self._cell(next_row, NAME_COLUMN))
            if next_name_match is None or next_name_match.group(1) != base_name:
                break

            next_index = int(next_name_match.group(2))
            if next_index != group_length:
                break

            if len(next_row) <= 2:
                break

            next_description_match = rules.tank_description_re.match(next_row[2])
            if next_description_match is not None:
                if (
                    next_description_match.group(1).strip() != base_key
                    or int(next_description_match.group(2)) != next_index
                ):
                    break
            elif self._derive_array_parent_base(next_row, next_row) != base_key:
                break

            group_length += 1

        minimum_group_length = 4 if base_name.endswith("_WORK_REG") else 2
        if group_length < minimum_group_length:
            return None

        source_row = baseline_row if baseline_row is not None else current_row
        parent_row = self._copy_row(source_row)
        parent_row[NAME_COLUMN] = base_name
        parent_row[2] = base_description
        parent_row[7] = str(group_length)
        parent_row[12] = ", ".join(["0"] * group_length)
        return parent_row

    @staticmethod
    def _row_signature(row: list[str]) -> tuple[str, ...]:
        excluded = {NAME_COLUMN, 2, IOADDRESS_COLUMN}
        max_length = max(len(row), IOADDRESS_COLUMN + 1)
        return tuple(
            row[index] if index < len(row) else ""
            for index in range(max_length)
            if index not in excluded
        )

    @staticmethod
    def _count_array_block_length(current_rows: list[list[str]], start_index: int, base_register: str) -> int:
        length = 0
        expected_index = 0

        for row in current_rows[start_index:]:
            current_name = RowChangeTracker._cell(row, NAME_COLUMN)
            register_match = re.match(r"^(.+)\[(\d+)\]$", current_name)
            if register_match is None or register_match.group(1) != base_register:
                break

            current_index = int(register_match.group(2))
            if current_index != expected_index:
                break

            length += 1
            expected_index += 1

        return length

    @staticmethod
    def _derive_array_parent_base(current_row: list[str], baseline_row: list[str]) -> str:
        """Derive the common base description used to match indexed child rows.

        This returns the description without the appended 'Register' suffix so
        that child rows with "... @ N" can be matched reliably.
        """
        current_description = RowChangeTracker._cell(current_row, 2)
        description_match = re.match(r"^(.*) @ \d+$", current_description)
        if description_match is not None:
            return description_match.group(1).strip()

        for suffix in (" Input", " Total", " Increment", " Output"):
            if current_description.endswith(suffix):
                return current_description[: -len(suffix)].strip()

        baseline_description = RowChangeTracker._cell(baseline_row, 2)
        return baseline_description or current_description

    @staticmethod
    def _derive_array_parent_description(current_row: list[str], baseline_row: list[str]) -> str:
        current_description = RowChangeTracker._cell(current_row, 2)
        description_match = re.match(r"^(.*) @ \d+$", current_description)
        if description_match is not None:
            base = description_match.group(1).strip()
        else:
            base = None
            for suffix in (" Input", " Total", " Increment", " Output"):
                if current_description.endswith(suffix):
                    base = current_description[: -len(suffix)].strip()
                    break

            if base is None:
                baseline_description = RowChangeTracker._cell(baseline_row, 2)
                base = baseline_description or current_description

        base = base.strip()
        if base.endswith(" Register"):
            return base
        if base.endswith(" Tank"):
            return base + " Register"
        return base + " Register"

    @staticmethod
    def _io_value(row: list[str]) -> str:
        return row[IOADDRESS_COLUMN].strip() if len(row) > IOADDRESS_COLUMN else ""

    @staticmethod
    def _cell(row: list[str], index: int) -> str:
        return row[index].strip() if index < len(row) else ""

    @staticmethod
    def _rows_differ(left: list[str], right: list[str]) -> bool:
        max_length = max(len(left), len(right))
        for index in range(max_length):
            left_value = left[index] if index < len(left) else ""
            right_value = right[index] if index < len(right) else ""
            if left_value != right_value:
                return True
        return False

    @staticmethod
    def _find_work_reg_current_row(
        current_by_name: dict[str, list[str]],
        prefix: str,
        work_index: int,
        rules: TankRules,
    ) -> list[str] | None:
        tag = rules.build_work_reg_tag(prefix, work_index)
        row = current_by_name.get(tag)
        if row is not None:
            return row

        legacy_tag = f"{prefix}_WORK_REG[{work_index}]"
        return current_by_name.get(legacy_tag)

    @staticmethod
    def _work_reg_byref_pass_row(current_row: list[str], baseline_row: list[str]) -> list[str]:
        row = RowChangeTracker._copy_row(current_row)
        if len(row) <= DATATYPE_COLUMN:
            row.extend([""] * (DATATYPE_COLUMN + 1 - len(row)))
        row[DATATYPE_COLUMN] = RowChangeTracker._cell(baseline_row, DATATYPE_COLUMN)
        row[IOADDRESS_COLUMN] = RowChangeTracker._io_value(baseline_row)
        if len(row) <= ARRAY_DIMENSION_COLUMN:
            row.extend([""] * (ARRAY_DIMENSION_COLUMN + 1 - len(row)))
        row[ARRAY_DIMENSION_COLUMN] = "0"
        return row

    @staticmethod
    def _work_reg_byname_pass_row(current_row: list[str]) -> list[str]:
        row = RowChangeTracker._copy_row(current_row)
        if len(row) <= DATATYPE_COLUMN:
            row.extend([""] * (DATATYPE_COLUMN + 1 - len(row)))
        row[DATATYPE_COLUMN] = WORK_REG_TARGET_TYPE
        if len(row) <= ARRAY_DIMENSION_COLUMN:
            row.extend([""] * (ARRAY_DIMENSION_COLUMN + 1 - len(row)))
        row[ARRAY_DIMENSION_COLUMN] = "0"
        row[IOADDRESS_COLUMN] = ""
        return row
