from __future__ import annotations

from pathlib import Path
from typing import Callable

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
        work_reg_bindings: dict[str, list[str]],
        input_path: Path | None = None,
        output_path: Path | None = None,
        input_rows: list[list[str]] | None = None,
        tag_prefix_input_path: Path | None = None,
        write_output: bool = True,
        cli_style: bool = True,
        event_callback: Callable[[dict[str, object]], None] | None = None,
        custom_tag_provider: Callable[[str], str | None] | None = None,
    ) -> list[list[str]] | None:
        print("Labeling work registers....")

        if not work_reg_bindings:
            print("No work register bindings to apply.")
            return input_rows

        if input_rows is None:
            source_path = input_path or self._find_source_path()
            if source_path is None or not source_path.is_file():
                print("No arrayified or sounded CSV found. Run arrayify first.")
                return None
            rows = self._csv_repository.read_rows(source_path)
            if not rows:
                print(f"Source file is empty: {source_path}")
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

        register_lookup = self._build_register_lookup(work_reg_bindings)

        for row in rows[1:]:
            if len(row) <= 2:
                continue

            source_register = row[0].split("[", 1)[0]
            binding = register_lookup.get(source_register)
            if binding is None:
                continue

            volume_description, work_index = binding
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
                continue

            tank_label = self._rules.tank_label_from_volume_description(volume_description)
            tag = self._rules.build_work_reg_tag(prefix, work_index)
            work_description = self._rules.build_work_reg_description(tank_label, work_index)
            row[0] = tag
            row[2] = work_description
            if len(row) > 15:
                row[15] = ""
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

    @staticmethod
    def _build_register_lookup(
        work_reg_bindings: dict[str, list[str]],
    ) -> dict[str, tuple[str, int]]:
        lookup: dict[str, tuple[str, int]] = {}
        for volume_description, register_names in work_reg_bindings.items():
            for index, register_name in enumerate(register_names):
                lookup[register_name] = (volume_description, index)
        return lookup

    def _find_source_path(self) -> Path | None:
        candidates = [self._config.sounded_csv_path, self._config.arrayified_csv_path]
        return next((path for path in candidates if path.is_file()), None)

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
