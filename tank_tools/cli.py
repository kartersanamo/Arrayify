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
from tank_tools.work_reg_registry import scan_work_register_bindings


class TankCli:
    def __init__(self) -> None:
        self._config = ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._arrayify_service = ArrayifyService(self._config, self._csv_repository, self._rules)
        self._sounding_service = TankSoundingService(self._config, self._csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(self._config, self._csv_repository, self._rules)
        self._work_reg_service = TankWorkRegService(self._config, self._csv_repository, self._rules)
        self._work_reg_bindings: dict[str, list[str]] = {}
        self._custom_tag_responses: dict[str, str | None] = {}

    def _custom_tag_provider(self, description: str) -> str | None:
        if description in self._custom_tag_responses:
            return self._custom_tag_responses[description]

        custom_input = input(
            f"No tag match for '{description}'. Enter a custom tag prefix, or press Enter to skip: "
        ).strip()
        value = custom_input or None
        self._custom_tag_responses[description] = value
        return value

    def _reset_custom_tag_responses(self) -> None:
        self._custom_tag_responses = {}

    def run(self) -> None:
        options: dict[int, list] = {
            1: [self._run_arrayify],
            2: [self._sounding_service.sound_tanks],
            3: [self._run_tank_registers],
            4: [self._run_normalize],
            5: [self._run_all],
        }

        print("Program options:")
        print("- 1) Array-ify points")
        print("- 2) Sound tanks")
        print("- 3) Label tank registers")
        print("- 4) Normalize tag names")
        print("- 5) All")
        option_choice = input("Enter your choice (1, 2, 3, 4, 5): ")

        if not option_choice.isdigit():
            print("Please enter a number.")
            return

        option_choice_int = int(option_choice)
        if option_choice_int not in options:
            print("Please enter a number 1-5.")
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

        self._work_reg_bindings = scan_work_register_bindings(rows, self._rules)
        self._reset_custom_tag_responses()
        return rows

    def _load_bindings_from_input(self) -> bool:
        if self._work_reg_bindings:
            return True

        rows = self._read_input_rows()
        return rows is not None

    def _load_processed_rows(self) -> list[list[str]] | None:
        source_path = self._config.sounded_csv_path
        if not source_path.is_file():
            source_path = self._config.arrayified_csv_path
        if not source_path.is_file():
            print("No arrayified or sounded CSV found. Run arrayify first.")
            return None

        rows = self._csv_repository.read_rows(source_path)
        if not rows:
            print(f"Source file is empty: {source_path}")
            return None

        return rows

    def _run_tank_registers_on_rows(self, rows: list[list[str]], *, write_output: bool) -> list[list[str]] | None:
        return self._work_reg_service.label_work_registers(
            self._work_reg_bindings,
            input_rows=rows,
            tag_prefix_input_path=self._config.input_csv_path,
            write_output=write_output,
            custom_tag_provider=self._custom_tag_provider,
        )

    def _run_normalize_on_rows(self, rows: list[list[str]], *, write_output: bool) -> list[list[str]] | None:
        return self._normalization_service.normalize_tags(
            input_rows=rows,
            tag_prefix_input_path=self._config.input_csv_path,
            write_output=write_output,
            custom_tag_provider=self._custom_tag_provider,
        )

    def _run_arrayify(self) -> None:
        rows = self._read_input_rows()
        if rows is None:
            return

        self._arrayify_service.arrayify_points(input_rows=rows)

    def _run_tank_registers(self) -> None:
        if not self._load_bindings_from_input():
            return

        processed_rows = self._load_processed_rows()
        if processed_rows is None:
            return

        self._run_tank_registers_on_rows(processed_rows, write_output=True)

    def _run_normalize(self) -> None:
        if not self._load_bindings_from_input():
            return

        processed_rows = self._load_processed_rows()
        if processed_rows is None:
            return

        self._run_normalize_on_rows(processed_rows, write_output=True)

    def _run_all(self) -> None:
        rows = self._read_input_rows()
        if rows is None:
            return

        arrayified_rows = self._arrayify_service.arrayify_points(input_rows=rows, write_output=False)
        if arrayified_rows is None:
            return

        sounded_rows = self._sounding_service.sound_tanks(input_rows=arrayified_rows, write_output=False)
        if sounded_rows is None:
            return

        labeled_rows = self._run_tank_registers_on_rows(sounded_rows, write_output=False)
        if labeled_rows is None:
            return

        self._run_normalize_on_rows(labeled_rows, write_output=True)
