from __future__ import annotations

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import (
    ArrayifyService,
    TagNormalizationService,
    TankSoundingService,
    TankWorkRegService,
)


class TankCli:
    def __init__(self) -> None:
        self._config = ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._arrayify_service = ArrayifyService(self._config, self._csv_repository, self._rules)
        self._sounding_service = TankSoundingService(self._config, self._csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(self._config, self._csv_repository, self._rules)
        self._work_reg_service = TankWorkRegService(self._config, self._csv_repository, self._rules)

    def run(self) -> None:
        options: dict[int, list] = {
            1: [self._run_arrayify],
            2: [self._sounding_service.sound_tanks],
            3: [self._run_normalize],
            4: [self._run_all],
        }

        print("Program options:")
        print("- 1) Array-ify points")
        print("- 2) Sound tanks")
        print("- 3) Normalize tag names")
        print("- 4) All")
        option_choice = input("Enter your choice (1, 2, 3, 4): ")

        if not option_choice.isdigit():
            print("Please enter a number.")
            return

        option_choice_int = int(option_choice)
        if option_choice_int not in options:
            print("Please enter a number 1-4.")
            return

        print("")
        for func in options[option_choice_int]:
            func()

    def _read_input_rows(self) -> list[list[str]] | None:
        if not self._config.input_csv_path.is_file():
            print(f"Input file not found: {self._config.input_csv_path}")
            return None

        rows = self._csv_repository.read_rows(self._config.input_csv_path)
        if not rows:
            print(f"Input file is empty: {self._config.input_csv_path}")
            return None

        return rows

    def _label_work_registers(self, rows: list[list[str]]) -> list[list[str]] | None:
        return self._work_reg_service.label_work_registers(
            input_rows=rows,
            tag_prefix_input_path=self._config.input_csv_path,
            write_output=False,
        )

    def _run_arrayify(self) -> None:
        rows = self._read_input_rows()
        if rows is None:
            return

        labeled_rows = self._label_work_registers(rows)
        if labeled_rows is None:
            return

        self._arrayify_service.arrayify_points(input_rows=labeled_rows)

    def _run_normalize(self) -> None:
        rows = self._read_input_rows()
        if rows is None:
            return

        labeled_rows = self._label_work_registers(rows)
        if labeled_rows is None:
            return

        self._normalization_service.normalize_tags(
            input_rows=labeled_rows,
            tag_prefix_input_path=self._config.input_csv_path,
        )

    def _run_all(self) -> None:
        rows = self._read_input_rows()
        if rows is None:
            return

        labeled_rows = self._label_work_registers(rows)
        if labeled_rows is None:
            return

        arrayified_rows = self._arrayify_service.arrayify_points(input_rows=labeled_rows, write_output=False)
        if arrayified_rows is None:
            return

        sounded_rows = self._sounding_service.sound_tanks(input_rows=arrayified_rows, write_output=False)
        if sounded_rows is None:
            return

        self._normalization_service.normalize_tags(
            input_rows=sounded_rows,
            tag_prefix_input_path=self._config.input_csv_path,
        )
