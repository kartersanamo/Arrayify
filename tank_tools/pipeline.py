from __future__ import annotations

from pathlib import Path
from typing import Callable

from tank_tools.change_tracker import ExportPlan, RowChangeTracker
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

WorkflowName = str
EventCallback = Callable[[dict[str, object]], None] | None
CustomTagProvider = Callable[[str], str | None] | None


class TankPipeline:
    def __init__(
        self,
        config: ProjectConfig,
        csv_repository: CsvRepository,
        rules: TankRules | None = None,
    ) -> None:
        self._config = config
        self._csv_repository = csv_repository
        self._rules = rules or TankRules()
        self._arrayify_service = ArrayifyService(config, csv_repository, self._rules)
        self._sounding_service = TankSoundingService(config, csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(config, csv_repository, self._rules)
        self._work_reg_service = TankWorkRegService(config, csv_repository, self._rules)

    @property
    def rules(self) -> TankRules:
        return self._rules

    def scan_bindings(self, rows: list[list[str]]) -> dict[str, list[str]]:
        return scan_work_register_bindings(rows, self._rules)

    def run(
        self,
        workflow: WorkflowName,
        rows: list[list[str]],
        *,
        work_reg_bindings: dict[str, list[str]] | None = None,
        sound_folder: Path | None = None,
        tag_prefix_path: Path | None = None,
        write_output: bool = False,
        cli_style: bool = True,
        event_callback: EventCallback = None,
        custom_tag_provider: CustomTagProvider = None,
        arrayify_output: Path | None = None,
        sound_output: Path | None = None,
        work_regs_output: Path | None = None,
        normalize_output: Path | None = None,
    ) -> list[list[str]] | None:
        bindings = work_reg_bindings or self.scan_bindings(rows)
        prefix_path = tag_prefix_path or self._config.input_csv_path
        sound_dir = sound_folder or self._config.new_sounds_dir

        if workflow == "arrayify":
            return self._arrayify_service.arrayify_points(
                input_rows=rows,
                output_path=arrayify_output,
                write_output=write_output,
                event_callback=event_callback,
            )

        if workflow == "sound":
            return self._sounding_service.sound_tanks(
                sound_folder=sound_dir,
                input_rows=rows,
                output_path=sound_output,
                write_output=write_output,
                cli_style=cli_style,
                event_callback=event_callback,
            )

        if workflow == "tank_registers":
            return self._work_reg_service.label_work_registers(
                bindings,
                input_rows=rows,
                output_path=work_regs_output,
                tag_prefix_input_path=prefix_path,
                write_output=write_output,
                cli_style=cli_style,
                event_callback=event_callback,
                custom_tag_provider=custom_tag_provider,
            )

        if workflow == "normalize":
            return self._normalization_service.normalize_tags(
                input_rows=rows,
                output_path=normalize_output,
                tag_prefix_input_path=prefix_path,
                write_output=write_output,
                cli_style=cli_style,
                live_preview=event_callback is not None,
                event_callback=event_callback,
                custom_tag_provider=custom_tag_provider,
            )

        if workflow == "all":
            arrayified = self._arrayify_service.arrayify_points(
                input_rows=rows,
                output_path=arrayify_output,
                write_output=write_output,
                event_callback=event_callback,
            )
            if arrayified is None:
                return None

            sounded = self._sounding_service.sound_tanks(
                sound_folder=sound_dir,
                input_rows=arrayified,
                output_path=sound_output,
                write_output=write_output,
                cli_style=cli_style,
                event_callback=event_callback,
            )
            if sounded is None:
                return None

            labeled = self._work_reg_service.label_work_registers(
                bindings,
                input_rows=sounded,
                output_path=work_regs_output,
                tag_prefix_input_path=prefix_path,
                write_output=write_output,
                cli_style=cli_style,
                event_callback=event_callback,
                custom_tag_provider=custom_tag_provider,
            )
            if labeled is None:
                return None

            return self._normalization_service.normalize_tags(
                input_rows=labeled,
                output_path=normalize_output,
                tag_prefix_input_path=prefix_path,
                write_output=write_output,
                cli_style=cli_style,
                live_preview=event_callback is not None,
                event_callback=event_callback,
                custom_tag_provider=custom_tag_provider,
            )

        raise ValueError(f"Unknown workflow: {workflow}")

    def build_export_plan(
        self,
        current_rows: list[list[str]],
        baseline_rows: list[list[str]],
        *,
        work_reg_bindings: dict[str, list[str]] | None = None,
        prefix_map: dict[str, str] | None = None,
        work_registers_only: bool = False,
    ) -> ExportPlan:
        tracker = RowChangeTracker(baseline_rows, self._rules)
        return tracker.export_plan(
            current_rows,
            work_reg_bindings=work_reg_bindings,
            prefix_map=prefix_map or {},
            work_registers_only=work_registers_only,
        )

    @staticmethod
    def write_export_plan(
        export_plan: ExportPlan,
        output_path: Path,
        csv_repository: CsvRepository,
        *,
        work_registers_only: bool = False,
    ) -> tuple[Path, ...]:
        if export_plan.modified_row_count == 0:
            raise ValueError("No modified rows to export.")

        use_labeled_export_files = (
            export_plan.needs_dual_export or export_plan.pass_file_labels is not None
        )
        if not use_labeled_export_files:
            csv_repository.write_rows(output_path, export_plan.second_pass_rows)
            return (output_path,)

        export_paths = ExportPlan.export_paths(
            output_path,
            export_plan.pass_count,
            export_plan.file_labels_for_export(),
        )
        for pass_index, export_path in enumerate(export_paths):
            csv_repository.write_rows(export_path, export_plan.pass_rows(pass_index))
        return export_paths

    @staticmethod
    def format_export_log_message(
        export_paths: tuple[Path, ...],
        export_plan: ExportPlan,
        *,
        work_registers_only: bool = False,
    ) -> str:
        if export_plan.pass_match_hints is not None:
            title = (
                "Tank register export complete."
                if work_registers_only
                else "Export complete."
            )
            lines = [f"{title} Import each file in order:\n"]
            for export_path, hint in zip(export_paths, export_plan.pass_match_hints):
                lines.append(f"- {export_path.name}: {hint}")
            return "\n".join(lines) + "\n"

        if len(export_paths) >= 2:
            first_path, second_path = export_paths[0], export_paths[1]
            return (
                "Dual export complete:\n"
                f"- {first_path.name}: import with Match by Ref Address And Data Type\n"
                f"- {second_path.name}: final live preview values\n"
            )
        return f"Exported to {export_paths[0].name}\n"
