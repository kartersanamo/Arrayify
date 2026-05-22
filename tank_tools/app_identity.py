from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tank_tools.runtime import is_frozen, project_root

APP_TITLE = "Arrayify"
APP_USER_MODEL_ID = "eco.edisonchouest.arrayify"


def configure_app_identity(name: str = APP_TITLE) -> None:
    if sys.platform == "darwin":
        os.environ.setdefault("CFBundleName", name)
        os.environ.setdefault("CFBundleDisplayName", name)
        _configure_macos_bundle_name(name)
        _rename_macos_process(name)
    elif sys.platform.startswith("win"):
        _configure_windows_app_id()


def macos_app_bundle_path() -> Path | None:
    if sys.platform != "darwin" or is_frozen():
        return None

    bundle = project_root() / "Arrayify.app"
    launcher = bundle / "Contents" / "MacOS" / "arrayify"
    if bundle.is_dir() and launcher.is_file():
        return bundle
    return None


def relaunch_via_macos_app_bundle(argv: list[str]) -> bool:
    if is_frozen() or sys.platform != "darwin" or os.environ.get("ARRAYIFY_IN_APP") == "1":
        return False

    bundle = macos_app_bundle_path()
    if bundle is None:
        return False

    launcher = bundle / "Contents" / "MacOS" / "arrayify"
    if not launcher.is_file():
        return False

    os.environ["ARRAYIFY_IN_APP"] = "1"
    os.execv(str(launcher), [str(launcher), *argv[1:]])


def apply_tk_window_identity(root: object, name: str = APP_TITLE) -> None:
    if sys.platform.startswith("win"):
        _configure_windows_app_id()

    if sys.platform.startswith("linux"):
        try:
            root.wm_class(name, name)  # type: ignore[attr-defined]
        except Exception:
            pass

    if sys.platform == "darwin":
        _configure_macos_bundle_name(name)
        _rename_macos_process(name)


def _configure_macos_bundle_name(name: str) -> None:
    try:
        from Foundation import NSBundle
    except ImportError:
        return

    bundle = NSBundle.mainBundle()
    if bundle is None:
        return

    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if info is None:
        return

    info["CFBundleName"] = name
    info["CFBundleDisplayName"] = name


def _rename_macos_process(name: str) -> None:
    script = f'tell application "System Events" to set name of (first process whose unix id is {os.getpid()}) to "{name}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


def _configure_windows_app_id() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass
