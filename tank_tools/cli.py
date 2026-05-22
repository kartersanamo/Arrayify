from __future__ import annotations

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import ArrayifyService, TagNormalizationService, TankSoundingService


class TankCli:
    def __init__(self) -> None:
        self._config = ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._arrayify_service = ArrayifyService(self._config, self._csv_repository, self._rules)
        self._sounding_service = TankSoundingService(self._config, self._csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(self._config, self._csv_repository, self._rules)

    def run(self) -> None:
        options: dict[int, list] = {
            1: [self._arrayify_service.arrayify_points],
            2: [self._sounding_service.sound_tanks],
            3: [self._normalization_service.normalize_tags],
            4: [
                self._arrayify_service.arrayify_points,
                self._sounding_service.sound_tanks,
                self._normalization_service.normalize_tags,
            ],
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
