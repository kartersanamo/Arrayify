from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    files_folder_name: str = "Files"
    input_file_name: str = "h221Test.csv"

    @classmethod
    def default(cls) -> "ProjectConfig":
        return cls(root=Path(__file__).resolve().parents[1])

    @property
    def files_dir(self) -> Path:
        return self.root / self.files_folder_name

    @property
    def input_csv_path(self) -> Path:
        return self.files_dir / self.input_file_name

    @property
    def input_stem(self) -> str:
        return Path(self.input_file_name).stem

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
    def new_sounds_dir(self) -> Path:
        return self.files_dir / "NewSounds"
