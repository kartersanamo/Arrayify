from __future__ import annotations

import copy
from dataclasses import dataclass

NAME_COLUMN = 0
IOADDRESS_COLUMN = 15


@dataclass(frozen=True)
class ExportPlan:
    match_pass_rows: list[list[str]]
    final_rows: list[list[str]]
    needs_dual_export: bool

    @property
    def modified_row_count(self) -> int:
        return max(0, len(self.final_rows) - 1)


@dataclass
class RowChangeTracker:
    baseline_rows: list[list[str]]

    def export_plan(self, current_rows: list[list[str]]) -> ExportPlan:
        if not current_rows:
            return ExportPlan(match_pass_rows=[], final_rows=[], needs_dual_export=False)

        header = current_rows[0]
        match_pass_rows: list[list[str]] = []
        final_rows: list[list[str]] = []
        needs_dual_export = False

        for current_row in current_rows[1:]:
            if not current_row:
                continue

            baseline_row = self._resolve_baseline_row(current_row, current_rows)
            if baseline_row is None:
                match_pass_rows.append(copy.deepcopy(current_row))
                final_rows.append(copy.deepcopy(current_row))
                continue

            if not self._rows_differ(current_row, baseline_row):
                continue

            final_row = copy.deepcopy(current_row)
            final_rows.append(final_row)

            if self._needs_dual_export_pair(baseline_row, current_row):
                needs_dual_export = True
                match_pass_rows.append(self._build_match_pass_row(baseline_row, current_row))
            else:
                match_pass_rows.append(copy.deepcopy(current_row))

        return ExportPlan(
            match_pass_rows=[header, *match_pass_rows],
            final_rows=[header, *final_rows],
            needs_dual_export=needs_dual_export,
        )

    def rows_for_export(self, current_rows: list[list[str]]) -> list[list[str]]:
        return self.export_plan(current_rows).final_rows

    def modified_row_count(self, current_rows: list[list[str]]) -> int:
        return self.export_plan(current_rows).modified_row_count

    def _resolve_baseline_row(self, current_row: list[str], current_rows: list[list[str]]) -> list[str] | None:
        baseline_by_name = self._index_baseline_rows()
        current_name = self._cell(current_row, NAME_COLUMN)
        baseline_row = baseline_by_name.get(current_name)
        if baseline_row is not None:
            return baseline_row

        return self._find_renamed_baseline_row(current_row, current_rows)

    def _find_renamed_baseline_row(self, current_row: list[str], current_rows: list[list[str]]) -> list[str] | None:
        current_names = {self._cell(row, NAME_COLUMN) for row in current_rows[1:] if row}
        current_signature = self._row_signature(current_row)
        candidates: list[list[str]] = []

        for baseline_row in self.baseline_rows[1:]:
            if not baseline_row:
                continue

            baseline_name = self._cell(baseline_row, NAME_COLUMN)
            if baseline_name in current_names:
                continue

            if self._row_signature(baseline_row) == current_signature:
                candidates.append(baseline_row)

        if len(candidates) == 1:
            return candidates[0]

        return None

    @staticmethod
    def _needs_dual_export_pair(baseline_row: list[str], current_row: list[str]) -> bool:
        name_changed = RowChangeTracker._cell(baseline_row, NAME_COLUMN) != RowChangeTracker._cell(
            current_row, NAME_COLUMN
        )
        io_changed = RowChangeTracker._io_value(baseline_row) != RowChangeTracker._io_value(current_row)
        return name_changed and io_changed

    @staticmethod
    def _build_match_pass_row(baseline_row: list[str], current_row: list[str]) -> list[str]:
        row = copy.deepcopy(current_row)
        max_length = max(len(row), IOADDRESS_COLUMN + 1, len(baseline_row))
        if len(row) < max_length:
            row.extend([""] * (max_length - len(row)))

        row[IOADDRESS_COLUMN] = RowChangeTracker._io_value(baseline_row)
        return row

    def _index_baseline_rows(self) -> dict[str, list[str]]:
        indexed: dict[str, list[str]] = {}
        for row in self.baseline_rows[1:]:
            if not row:
                continue
            indexed[self._cell(row, NAME_COLUMN)] = row
        return indexed

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
