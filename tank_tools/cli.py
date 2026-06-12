from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.pipeline import TankPipeline
from tank_tools.rules import TankRules
from tank_tools.work_reg_registry import scan_work_register_bindings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Arrayify, sound, normalize, and export tank register spreadsheets.",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        help="Input CSV path (required for subcommands unless using interactive menu).",
    )
    parser.add_argument(
        "--docx-dir",
        type=Path,
        help="Folder containing DOCX sounding tables (defaults to NewSounds near input).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated CSV outputs (defaults to input file directory).",
    )
    parser.add_argument(
        "--custom-tag",
        action="append",
        default=[],
        metavar="DESCRIPTION=PREFIX",
        help="Custom tag prefix for a tank volume description (repeatable).",
    )

    subparsers = parser.add_subparsers(dest="command")

    arrayify = subparsers.add_parser("arrayify", help="Array-ify tank sounding points.")
    arrayify.add_argument("--output", "-o", type=Path, help="Output CSV path.")

    sound = subparsers.add_parser("sound", help="Apply DOCX soundings to arrayified rows.")
    sound.add_argument("--output", "-o", type=Path, help="Output CSV path.")

    tank_regs = subparsers.add_parser("tank-registers", help="Label work registers.")
    tank_regs.add_argument("--output", "-o", type=Path, help="Output CSV path.")
    tank_regs.add_argument(
        "--tag-prefix-from",
        type=Path,
        help="CSV used to build tag prefix map (defaults to --input).",
    )

    normalize = subparsers.add_parser("normalize", help="Normalize register names to tags.")
    normalize.add_argument("--output", "-o", type=Path, help="Output CSV path.")
    normalize.add_argument(
        "--tag-prefix-from",
        type=Path,
        help="CSV used to build tag prefix map (defaults to --input).",
    )

    run_all = subparsers.add_parser(
        "run-all",
        help="Run arrayify, sound, tank-registers, and normalize in sequence.",
    )
    run_all.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Final normalized output CSV path.",
    )

    export_cmd = subparsers.add_parser("export", help="Export modified rows for Proficy import.")
    export_cmd.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Original baseline CSV before modifications.",
    )
    export_cmd.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Base path for export file(s); dual-pass exports add -BYREF-FIRST / -BYNAME-SECOND.",
    )
    export_cmd.add_argument(
        "--regs-only",
        action="store_true",
        help="Export only tank register rows.",
    )

    subparsers.add_parser("menu", help="Interactive numeric menu (legacy).")

    return parser


class TankCli:
    def __init__(self, config: ProjectConfig | None = None) -> None:
        self._config = config or ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._pipeline = TankPipeline(self._config, self._csv_repository, self._rules)
        self._work_reg_bindings: dict[str, list[str]] = {}
        self._custom_tag_responses: dict[str, str | None] = {}

    def run(self, args: argparse.Namespace) -> int:
        self._apply_custom_tags(args.custom_tag)

        if args.command is None:
            if sys.stdin.isatty():
                return self._run_interactive_menu(args)
            print("No subcommand specified. Use --help for available commands.", file=sys.stderr)
            return 1

        if args.command == "menu":
            return self._run_interactive_menu(args)

        return self._run_command(args)

    def _apply_custom_tags(self, custom_tags: list[str]) -> None:
        for entry in custom_tags:
            if "=" not in entry:
                print(f"Ignoring invalid --custom-tag (expected DESCRIPTION=PREFIX): {entry}", file=sys.stderr)
                continue
            description, prefix = entry.split("=", 1)
            description = description.strip()
            prefix = prefix.strip()
            if description:
                self._custom_tag_responses[description] = prefix or None

    def _custom_tag_provider(self, description: str) -> str | None:
        if description in self._custom_tag_responses:
            return self._custom_tag_responses[description]

        if not sys.stdin.isatty():
            return None

        custom_input = input(
            f"No tag match for '{description}'. Enter a custom tag prefix, or press Enter to skip: "
        ).strip()
        value = custom_input or None
        self._custom_tag_responses[description] = value
        return value

    def _resolve_config(self, args: argparse.Namespace) -> ProjectConfig | None:
        if args.input is None:
            default_input = self._config.input_csv_path
            if default_input.is_file():
                args.input = default_input
            else:
                print("--input is required.", file=sys.stderr)
                return None

        if not args.input.is_file():
            print(f"Input file not found: {args.input}", file=sys.stderr)
            return None

        config = ProjectConfig.from_paths(
            args.input,
            output_dir=args.output_dir,
            docx_dir=args.docx_dir,
        )
        self._config = config
        self._pipeline = TankPipeline(config, self._csv_repository, self._rules)
        return config

    def _load_rows(self, path: Path) -> list[list[str]] | None:
        try:
            rows = self._csv_repository.read_rows(path)
        except OSError as exc:
            print(f"Could not read CSV: {exc}", file=sys.stderr)
            return None

        if not rows:
            print(f"Input file is empty: {path}", file=sys.stderr)
            return None

        self._work_reg_bindings = scan_work_register_bindings(rows, self._rules)
        return rows

    def _run_command(self, args: argparse.Namespace) -> int:
        if args.command == "export":
            return self._run_export(args)

        config = self._resolve_config(args)
        if config is None:
            return 1

        rows = self._load_rows(config.input_csv_path)
        if rows is None:
            return 1

        tag_prefix_path = getattr(args, "tag_prefix_from", None) or config.input_csv_path
        sound_folder = args.docx_dir or config.new_sounds_dir

        if args.command in {"sound", "run-all"} and not sound_folder.is_dir():
            print(f"DOCX folder not found: {sound_folder}", file=sys.stderr)
            return 1

        workflow_map = {
            "arrayify": "arrayify",
            "sound": "sound",
            "tank-registers": "tank_registers",
            "normalize": "normalize",
            "run-all": "all",
        }
        workflow = workflow_map[args.command]

        output_kwargs = self._output_kwargs(args, config)
        result = self._pipeline.run(
            workflow,
            rows,
            work_reg_bindings=self._work_reg_bindings,
            sound_folder=sound_folder,
            tag_prefix_path=tag_prefix_path,
            write_output=True,
            cli_style=True,
            custom_tag_provider=self._custom_tag_provider,
            **output_kwargs,
        )
        if result is None:
            return 1
        return 0

    def _output_kwargs(self, args: argparse.Namespace, config: ProjectConfig) -> dict[str, Any]:
        output = getattr(args, "output", None)
        if args.command == "arrayify":
            return {"arrayify_output": output or config.arrayified_csv_path}
        if args.command == "sound":
            return {"sound_output": output or config.sounded_csv_path}
        if args.command == "tank-registers":
            return {"work_regs_output": output or config.work_regs_csv_path}
        if args.command == "normalize":
            return {"normalize_output": output or config.normalized_csv_path}
        if args.command == "run-all":
            return {
                "arrayify_output": config.arrayified_csv_path,
                "sound_output": config.sounded_csv_path,
                "work_regs_output": config.work_regs_csv_path,
                "normalize_output": output or config.normalized_csv_path,
            }
        return {}

    def _run_export(self, args: argparse.Namespace) -> int:
        if args.input is None:
            print("--input is required for export.", file=sys.stderr)
            return 1

        if not args.baseline.is_file():
            print(f"Baseline file not found: {args.baseline}", file=sys.stderr)
            return 1

        current_path = args.input or args.baseline
        if not current_path.is_file():
            print(f"Current CSV not found: {current_path}", file=sys.stderr)
            return 1

        baseline_rows = self._load_rows(args.baseline)
        current_rows = self._csv_repository.read_rows(current_path)
        if baseline_rows is None or not current_rows:
            return 1

        config = ProjectConfig.from_paths(current_path, output_dir=args.output_dir, docx_dir=args.docx_dir)
        prefix_map = self._rules.load_tag_prefix_map(
            self._csv_repository.read_rows(config.input_csv_path)
        )
        bindings = scan_work_register_bindings(baseline_rows, self._rules)

        export_plan = self._pipeline.build_export_plan(
            current_rows,
            baseline_rows,
            work_reg_bindings=bindings,
            prefix_map=prefix_map,
            work_registers_only=args.regs_only,
        )

        try:
            export_paths = self._pipeline.write_export_plan(
                export_plan,
                args.output,
                self._csv_repository,
                work_registers_only=args.regs_only,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        print(
            self._pipeline.format_export_log_message(
                export_paths,
                export_plan,
                work_registers_only=args.regs_only,
            )
        )
        return 0

    def _run_interactive_menu(self, args: argparse.Namespace) -> int:
        config = self._resolve_config(args)
        if config is None:
            return 1

        print("Program options:")
        print("- 1) Array-ify points")
        print("- 2) Sound tanks")
        print("- 3) Label tank registers")
        print("- 4) Normalize tag names")
        print("- 5) All")
        option_choice = input("Enter your choice (1, 2, 3, 4, 5): ")

        if not option_choice.isdigit() or int(option_choice) not in range(1, 6):
            print("Please enter a number 1-5.")
            return 1

        menu_map = {
            1: "arrayify",
            2: "sound",
            3: "tank-registers",
            4: "normalize",
            5: "run-all",
        }
        args.command = menu_map[int(option_choice)]
        print("")
        return self._run_command(args)
