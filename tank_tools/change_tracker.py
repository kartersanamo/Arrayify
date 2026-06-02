from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RowChangeTracker:
    baseline_rows: list[list[str]]

    def rows_for_export(self, current_rows: list[list[str]]) -> list[list[str]]:
        if not current_rows:
            return []

        baseline_by_name = self._index_baseline_rows()
        header = current_rows[0]
        modified: list[list[str]] = []

        for row in current_rows[1:]:
            if not row:
                continue

            name = row[0] if len(row) > 0 else ""
            baseline_row = baseline_by_name.get(name)
            if baseline_row is None or self._rows_differ(row, baseline_row):
                modified.append(row)

        return [header, *modified]

    def modified_row_count(self, current_rows: list[list[str]]) -> int:
        export_rows = self.rows_for_export(current_rows)
        return max(0, len(export_rows) - 1)

    def _index_baseline_rows(self) -> dict[str, list[str]]:
        indexed: dict[str, list[str]] = {}
        for row in self.baseline_rows[1:]:
            if not row:
                continue
            indexed[row[0]] = row
        return indexed

    @staticmethod
    def _rows_differ(left: list[str], right: list[str]) -> bool:
        max_length = max(len(left), len(right))
        for index in range(max_length):
            left_value = left[index] if index < len(left) else ""
            right_value = right[index] if index < len(right) else ""
            if left_value != right_value:
                return True
        return False
