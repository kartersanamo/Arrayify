"""

    Author: Karter Sanamo
    Company: Edison Chouest Offshore
    Date Created: 05/21/2026
    Date Last Modified: 05/22/2026
    Description:
        Arrayify is a program written for ECO to automate conversions
        betweens spreadsheets. Beforehand, variables for tank sounding
        levels were each given their own address, but now the initial
        address is refactored into an array. There is also the option
        to resound the variables with new values given .docx files, and
        to normalize the names to tags.

    Licensing:
        All of the code belongs to the ownership of the Author ("Karter
        Sanamo") listed above and the Company ("Edison Chouest Offshore")
        listed above. No other persons or entities are allowed to use this
        software without permission.

"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from tank_tools.cli import TankCli
from tank_tools.runtime import is_frozen


def main() -> None:
    parser = argparse.ArgumentParser(description="Arrayify, sound, and normalize tank register spreadsheets.")
    parser.add_argument("--gui", action="store_true", help="Launch the Tkinter GUI instead of the CLI menu.")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force the CLI menu (development only; packaged GUI builds launch the GUI by default).",
    )
    args = parser.parse_args()

    if should_launch_gui(args.gui, args.cli):
        launch_gui()
        return

    TankCli().run()


def should_launch_gui(explicit_gui: bool, explicit_cli: bool) -> bool:
    if explicit_cli and not explicit_gui:
        return False
    if explicit_gui:
        return True
    if is_frozen():
        return True
    return False


def launch_gui() -> None:
    from tank_tools.app_identity import configure_app_identity, relaunch_via_macos_app_bundle

    configure_app_identity()
    relaunch_via_macos_app_bundle(sys.argv)

    if not is_frozen():
        gui_executable = find_tkinter_python_executable()
        if gui_executable is None:
            print("GUI mode is unavailable because no Python interpreter with Tkinter was found.")
            return

        if Path(gui_executable).resolve() != Path(sys.executable).resolve():
            os.environ.setdefault("ARRAYIFY_IN_APP", "1")
            os.execv(gui_executable, [gui_executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    try:
        import tkinter as tk
    except ImportError:
        print("GUI mode is unavailable because Tkinter is not installed in this build.")
        return

    from tank_tools.gui import TankManagerApp

    root = tk.Tk()
    TankManagerApp(root).run()


def find_tkinter_python_executable() -> str | None:
    if is_frozen():
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return None
        return sys.executable

    candidates = [
        sys.executable,
        "/usr/bin/python3",
        "/opt/homebrew/bin/python3",
        "/opt/homebrew/bin/python3.14",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        if has_tkinter(candidate):
            return candidate

    return None


def has_tkinter(python_executable: str) -> bool:
    try:
        completed = subprocess.run(
            [python_executable, "-c", "import tkinter"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False

    return completed.returncode == 0


if __name__ == "__main__":
    main()
