from __future__ import annotations

from pathlib import Path
from typing import Callable

from tank_tools.config import ProjectConfig
from tank_tools.docx_reader import read_docx_tables
from tank_tools.io import CsvRepository
from tank_tools.models import SoundDocumentMiss, SoundMatch
from tank_tools.output_format import bullet_prefix
from tank_tools.rules import TankRules


class TankSoundingService:
    def __init__(self, config: ProjectConfig, csv_repository: CsvRepository, rules: TankRules) -> None:
        self._config = config
        self._csv_repository = csv_repository
        self._rules = rules

    def sound_tanks(
        self,
        sound_folder: Path | None = None,
        input_path: Path | None = None,
        output_path: Path | None = None,
        input_rows: list[list[str]] | None = None,
        write_output: bool = True,
        cli_style: bool = True,
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[list[str]] | None:
        print("Sounding tanks....")

        if sound_folder is None:
            folder_input = input("Enter the folder path containing DOCX soundings [Files/NewSounds]: ").strip()
            sound_folder = Path(folder_input or self._config.new_sounds_dir)

        if not sound_folder.is_dir():
            print(f"Folder not found: {sound_folder}")
            return

        input_path = input_path or self._config.arrayified_csv_path
        output_path = output_path or self._config.sounded_csv_path

        if input_rows is None and not input_path.is_file():
            print(f"Template file not found: {input_path}")
            return

        if write_output and output_path.exists():
            print(f"Conflicting output file path: {output_path}")
            return

        rows = input_rows if input_rows is not None else self._csv_repository.read_rows(input_path)
        if not rows:
            print("Template file is empty. You must arrayify the input file first.")
            return

        base_rows: list[tuple[int, str]] = []
        base_register_by_description: dict[str, str] = {}
        for row_index, row in enumerate(rows[1:], start=1):
            if len(row) <= 12 or not row[0] or "[" in row[0] or not self._rules.is_register_name(row[0]):
                continue

            base_rows.append((row_index, row[2]))
            base_register_by_description[row[2]] = row[0].split("[", 1)[0]

        explicit_matches: dict[str, dict[str, object]] = {}
        unmatched_doc_tables: list[SoundDocumentMiss] = []

        for doc_path in sorted(sound_folder.glob("*.docx")) + sorted(sound_folder.glob("*.DOCX")):
            for table in read_docx_tables(doc_path):
                table_title = table.cell(0, 0).text.strip().replace("\n", " ")
                table_key = self._rules.extract_table_key(table_title)
                if not table_key:
                    continue

                volumes = self._rules.read_sounding_volumes(table)
                description = self._rules.table_key_to_description(table_key)

                if description is None:
                    unmatched_doc_tables.append(SoundDocumentMiss(doc_file=doc_path.name, doc_title=table_title))
                    continue

                if description in explicit_matches:
                    if explicit_matches[description]["volumes"] != volumes:
                        raise ValueError(f"Duplicate sounding table for {description}.")
                    continue

                explicit_matches[description] = {
                    "doc_file": doc_path.name,
                    "doc_title": table_title,
                    "table_key": table_key,
                    "volumes": volumes,
                }

        matched_metadata_by_description: dict[str, dict[str, object]] = {}
        for description, metadata in explicit_matches.items():
            row_index = self._rules.find_base_row_index(rows, description)
            if row_index is None:
                raise ValueError(f"No CSV row found for sounding table {description}.")

            self._set_block_initial_values(rows, row_index, metadata["volumes"])
            matched_metadata_by_description[description] = metadata

            if event_callback is not None:
                event_callback(
                    {
                        "type": "preview",
                        "workflow": "sound",
                        "description": description,
                        "rows": rows.copy(),
                    }
                )

        matched_rows: list[SoundMatch] = []
        for _, description in base_rows:
            metadata = matched_metadata_by_description.get(description)
            if metadata is None:
                continue

            matched_rows.append(
                SoundMatch(
                    csv_register=base_register_by_description[description],
                    csv_description=description,
                    doc_file=str(metadata["doc_file"]),
                    doc_title=str(metadata["doc_title"]),
                )
            )

        used_doc_pairs = {
            (str(metadata["doc_file"]), str(metadata["doc_title"]))
            for metadata in matched_metadata_by_description.values()
        }
        unmatched_doc_tables = [
            item for item in unmatched_doc_tables if (item.doc_file, item.doc_title) not in used_doc_pairs
        ]
        unmatched_csv_rows = [description for _, description in base_rows if description not in matched_metadata_by_description]

        self._print_sound_mapping_report(matched_rows, unmatched_doc_tables, unmatched_csv_rows, cli_style)
        if write_output:
            self._csv_repository.write_rows(output_path, rows)
            print(f"Wrote sounded CSV to {output_path}")

        if event_callback is not None:
            event_callback({"type": "completed", "workflow": "sound", "rows": rows.copy()})

        return rows

    def _set_block_initial_values(self, rows: list[list[str]], start_index: int, values: list[str]) -> None:
        base_row = rows[start_index]
        base_register = base_row[0].split("[", 1)[0]

        block_end = start_index + 1
        while block_end < len(rows):
            register_match = self._rules.register_array_name_re.match(rows[block_end][0])
            if not register_match or register_match.group(1) != base_register[1:]:
                break
            block_end += 1

        existing_length = block_end - start_index - 1
        if existing_length <= 0:
            raise ValueError(f"No array rows found for {base_row[2]}.")
        if not values:
            raise ValueError(f"No sounding values found for {base_row[2]}.")

        target_length = max(existing_length, self._rules.round_up_to_25(len(values)))
        padded_values = values + [values[-1]] * (target_length - len(values))

        if target_length > existing_length:
            last_row_template = rows[block_end - 1]
            extra_rows: list[list[str]] = []

            for index in range(existing_length, target_length):
                row = last_row_template.copy()
                row[0] = f"{base_register}[{index}]"
                row[2] = f"{base_row[2]} @ {index}"
                row[12] = padded_values[index]
                row[15] = f"%R{int(base_register[1:]) + index:05d}"
                extra_rows.append(row)

            rows[block_end:block_end] = extra_rows
            block_end += len(extra_rows)

        base_row[7] = str(target_length)
        base_row[12] = ", ".join(padded_values)

        for offset, row in enumerate(rows[start_index + 1:block_end]):
            row[12] = padded_values[offset]

    @staticmethod
    def _print_sound_mapping_report(
        matched_rows: list[SoundMatch],
        unmatched_doc_tables: list[SoundDocumentMiss],
        unmatched_csv_rows: list[str],
        cli_style: bool = True,
    ) -> None:
        bullet = bullet_prefix(cli_style)
        print("Sound mapping report:")

        if matched_rows:
            print("Matched tanks:")
            for item in matched_rows:
                print(
                    f"{bullet}{item.csv_register} | {item.csv_description} -> "
                    f"{item.doc_file} :: {item.doc_title}"
                )
        else:
            print("Matched tanks: none")

        if unmatched_doc_tables:
            print("\nDOCX tables without a CSV match:")
            for item in unmatched_doc_tables:
                print(f"{bullet}{item.doc_file} :: {item.doc_title}")
        else:
            print("DOCX tables without a CSV match: none")

        if unmatched_csv_rows:
            print("\nCSV tank rows without a DOCX table:")
            for description in unmatched_csv_rows:
                print(f"{bullet}{description}")
        else:
            print("CSV tank rows without a DOCX table: none")
