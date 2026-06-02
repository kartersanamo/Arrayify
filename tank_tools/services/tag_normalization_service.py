from __future__ import annotations

from pathlib import Path
from typing import Callable

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.models import NormalizeMatch, NormalizeMiss
from tank_tools.output_format import bullet_prefix, sub_bullet_prefix
from tank_tools.rules import TankRules


class TagNormalizationService:
    def __init__(self, config: ProjectConfig, csv_repository: CsvRepository, rules: TankRules) -> None:
        self._config = config
        self._csv_repository = csv_repository
        self._rules = rules

    def normalize_tags(
        self,
        input_path: Path | None = None,
        output_path: Path | None = None,
        input_rows: list[list[str]] | None = None,
        tag_prefix_input_path: Path | None = None,
        write_output: bool = True,
        cli_style: bool = True,
        live_preview: bool = True,
        event_callback: Callable[[dict[str, object]], None] | None = None,
        custom_tag_provider: Callable[[str], str | None] | None = None,
    ) -> list[list[str]] | None:
        print("Normalizing tags....")

        if input_rows is None:
            source_path = input_path or self._find_source_path()
            if source_path is None:
                print("No arrayified or sounded CSV found. Run arrayify first.")
                return
            rows = self._csv_repository.read_rows(source_path)
            if not rows:
                print(f"Source file is empty: {source_path}")
                return
        else:
            rows = input_rows

        output_path = output_path or self._config.normalized_csv_path
        if write_output and output_path.exists():
            print(f"Conflicting output file path: {output_path}")
            return

        if not rows:
            print("Input rows are empty.")
            return

        tag_prefix_source = tag_prefix_input_path or self._config.input_csv_path
        if not tag_prefix_source.is_file():
            print(f"Tag prefix source file not found: {tag_prefix_source}")
            return

        prefix_map = self._rules.load_tag_prefix_map(self._csv_repository.read_rows(tag_prefix_source))
        if not prefix_map:
            print(f"Tag prefix map could not be built from {tag_prefix_source}.")
            return

        renamed_rows = 0
        matched_rows: list[NormalizeMatch] = []
        unmatched_rows: list[NormalizeMiss] = []
        custom_tag_map: dict[str, str] = {}
        prompted_descriptions: set[str] = set()

        for row in rows[1:]:
            if len(row) <= 2:
                continue

            source_register = row[0].split("[", 1)[0]
            description = row[2].strip()
            if not description:
                continue

            if self._rules.is_work_reg_tag(row[0]):
                continue

            if self._rules.is_register_name(row[0]) or self._rules.register_array_name_re.match(row[0]):
                normalized_name = self._rules.normalize_tag_name(row, prefix_map, custom_tag_map)
                if normalized_name is None:
                    base_description = self._rules.extract_base_description(description)
                    if base_description not in prompted_descriptions:
                        prompted_descriptions.add(base_description)
                        if custom_tag_provider is None:
                            custom_input = input(
                                f"No tag match for '{base_description}'. Enter a custom tag prefix, or press Enter to leave it unchanged: "
                            ).strip()
                        else:
                            custom_input = (custom_tag_provider(base_description) or "").strip()

                        if custom_input:
                            custom_tag_name = self._rules.format_custom_tag_name(custom_input)
                            if custom_tag_name is None:
                                print(f"Skipping '{base_description}' because the custom tag was empty.")
                            else:
                                custom_tag_map[base_description] = custom_tag_name
                                normalized_name = self._rules.normalize_tag_name(row, prefix_map, custom_tag_map)

                    if normalized_name is None:
                        unmatched_rows.append(NormalizeMiss(register=source_register, description=description))
                        continue

                matched_rows.append(NormalizeMatch(register=source_register, description=description, tag=normalized_name))
                row[0] = normalized_name
                if len(row) > 15:
                    row[15] = ""
                renamed_rows += 1

                if event_callback is not None and live_preview:
                    event_callback(
                        {
                            "type": "preview",
                            "workflow": "normalize",
                            "register": source_register,
                            "description": description,
                            "tag": normalized_name,
                            "rows": rows.copy(),
                        }
                    )
                continue

            normalized_name = self._rules.normalize_tag_name(row, prefix_map, custom_tag_map)
            if normalized_name is None or normalized_name == row[0]:
                continue

            row[0] = normalized_name
            if len(row) > 15:
                row[15] = ""
            renamed_rows += 1

        self._print_normalize_summary(matched_rows, unmatched_rows, cli_style)
        if write_output:
            self._csv_repository.write_rows(output_path, rows)
            print(f"Normalized {renamed_rows} row names.")
            print(f"Wrote normalized CSV to {output_path}")
        else:
            print(f"Normalized {renamed_rows} row names.")

        if event_callback is not None:
            event_callback({"type": "completed", "workflow": "normalize", "rows": rows.copy()})

        return rows

    def _find_source_path(self) -> Path | None:
        candidates = [self._config.sounded_csv_path, self._config.arrayified_csv_path]
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _print_normalize_summary(
        matched_rows: list[NormalizeMatch],
        unmatched_rows: list[NormalizeMiss],
        cli_style: bool = True,
    ) -> None:
        bullet = bullet_prefix(cli_style)
        sub_bullet = sub_bullet_prefix(cli_style)
        print("Normalize summary:")

        def group_rows(rows: list[NormalizeMatch | NormalizeMiss]) -> list[dict[str, object]]:
            grouped_rows: dict[str, dict[str, object]] = {}
            for item in rows:
                key = item.description.split(" @ ", 1)[0]
                group = grouped_rows.setdefault(
                    key,
                    {
                        "description": key,
                        "tag": getattr(item, "tag", ""),
                        "rows": [],
                    },
                )
                group["rows"].append(item)
            return list(grouped_rows.values())

        def print_grouped_rows(title: str, rows: list[NormalizeMatch | NormalizeMiss], include_tag: bool) -> None:
            if not rows:
                print(f"{title} none")
                return

            print(title)
            for group in group_rows(rows):
                sample_rows = group["rows"][:2]
                count = len(group["rows"])
                if include_tag:
                    print(f"{bullet}{group['description']} -> {group['tag']} ({count} rows)")
                else:
                    print(f"{bullet}{group['description']} ({count} rows)")

                for index, item in enumerate(sample_rows):
                    end = "\n" if index == 0 else "...\n\n"
                    if include_tag:
                        print(f"{sub_bullet}{item.register} | {item.description} -> {item.tag}", end=end)
                    else:
                        print(f"{sub_bullet}{item.register} | {item.description}", end=end)

        print_grouped_rows("Renamed rows:", matched_rows, include_tag=True)
        print_grouped_rows("Rows without a tag match:", unmatched_rows, include_tag=False)
