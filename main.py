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

from tank_tools.cli import TankCli


def main() -> None:
    parser = argparse.ArgumentParser(description="Arrayify, sound, and normalize tank register spreadsheets.")
    parser.add_argument("--gui", action="store_true", help="Launch the Tkinter GUI instead of the CLI menu.")
    args = parser.parse_args()

    if args.gui:
        try:
            import tkinter as tk
            from tank_tools.gui import TankManagerApp
        except ModuleNotFoundError as exc:
            print(f"GUI mode is unavailable in this Python environment: {exc}")
            return

        root = tk.Tk()
        TankManagerApp(root).run()
        return

    TankCli().run()


if __name__ == "__main__":
    main()
