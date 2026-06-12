from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tank_tools.runtime import bundled_files_dir, default_project_root


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    files_folder_name: str = "Files"
    input_file_name: str = "h221Test.csv"
    input_csv: Path | None = None
    output_dir: Path | None = None
    docx_dir: Path | None = None

    @classmethod
    def default(cls) -> "ProjectConfig":
        return cls(root=default_project_root())

    @classmethod
    def from_paths(
        cls,
        input_csv: Path,
        output_dir: Path | None = None,
        docx_dir: Path | None = None,
    ) -> "ProjectConfig":
        input_csv = input_csv.resolve()
        resolved_output_dir = (output_dir or input_csv.parent).resolve()
        return cls(
            root=resolved_output_dir,
            input_csv=input_csv,
            output_dir=resolved_output_dir,
            docx_dir=docx_dir.resolve() if docx_dir else None,
        )

    @property
    def files_dir(self) -> Path:
        if self.output_dir is not None:
            return self.output_dir
        return self.root / self.files_folder_name

    @property
    def input_csv_path(self) -> Path:
        if self.input_csv is not None:
            return self.input_csv
        return self.files_dir / self.input_file_name

    @property
    def input_stem(self) -> str:
        return self.input_csv_path.stem

    @property
    def arrayified_csv_path(self) -> Path:
        return self.files_dir / f"{self.input_stem}_arrayified.csv"

    @property
    def sounded_csv_path(self) -> Path:
        return self.files_dir / f"{self.input_stem}_sounded.csv"

    @property
    def normalized_csv_path(self) -> Path:
        return self.files_dir / f"{self.input_stem}_normalized.csv"

    @property
    def work_regs_csv_path(self) -> Path:
        return self.files_dir / f"{self.input_stem}_work_regs.csv"

    @property
    def new_sounds_dir(self) -> Path:
        if self.docx_dir is not None:
            return self.docx_dir

        sibling = self.files_dir / "NewSounds"
        if sibling.is_dir():
            return sibling

        bundled = bundled_files_dir()
        if bundled is not None:
            bundled_sounds = bundled / "NewSounds"
            if bundled_sounds.is_dir():
                return bundled_sounds

        return sibling
