from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


class CsvRepository:
    def read_rows(self, path: Path) -> list[list[str]]:
        with path.open(newline="") as input_file:
            return list(csv.reader(input_file, dialect="excel"))

    def write_rows(self, path: Path, rows: Iterable[list[str]]) -> None:
        with path.open("w", newline="") as output_file:
            writer = csv.writer(output_file, dialect="excel")
            writer.writerows(rows)
