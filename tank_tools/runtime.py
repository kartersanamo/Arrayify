from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def project_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def executable_dir() -> Path:
    return Path(sys.executable).resolve().parent


def resource_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def bundled_files_dir() -> Path | None:
    candidate = resource_path("Files")
    if candidate.is_dir():
        return candidate
    return None


def default_project_root() -> Path:
    if is_frozen():
        bundled = bundled_files_dir()
        if bundled is not None:
            return bundled.parent
        return executable_dir()
    return Path(__file__).resolve().parent.parent
