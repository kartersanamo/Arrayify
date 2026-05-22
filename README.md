# Arrayify and Sound Tanks

This project converts tank register spreadsheets into array-based rows, applies soundings from `.docx` tables, and normalizes register names to tank tag names.

The runtime code only uses the Python standard library. The GUI will automatically relaunch itself with a Tk-capable Python interpreter if the current one was built without Tkinter.

## Structure

- `main.py` is the entrypoint and supports both CLI and GUI launch.
- `tank_tools/config.py` holds project paths.
- `tank_tools/io.py` handles CSV I/O.
- `tank_tools/rules.py` contains naming and sounding rules.
- `tank_tools/services.py` contains the workflow classes.
- `tank_tools/cli.py` wires the CLI menu.
- `tank_tools/gui.py` provides the lightweight Tkinter interface.

## Run Through CLI

Install the dependencies first:

```bash
pip install -r requirements.txt
```

There are no mandatory third-party runtime packages right now, so this step is mostly useful if you later add packaging or build tooling.

Then run the CLI menu:

```bash
python main.py
```

The CLI menu lets you run:

- Array-ify points
- Sound tanks
- Normalize tag names
- Run all three in sequence

## Run Through GUI

Launch the Tkinter interface with:

```bash
python main.py --gui
```

In the GUI, pick the input CSV inside the app, choose the DOCX folder if you need sounding, watch the live log and row preview update, and export the current result whenever you want.

If the Python you launched does not include Tkinter, the app automatically relaunches with another local Python that does.

## Package With PyInstaller

Install PyInstaller in the environment you will build from:

```bash
pip install pyinstaller
```

PyInstaller builds on the current operating system, so create the `.exe` on Windows and build the macOS/Linux binary on macOS/Linux.

For a GUI build:

```bash
pyinstaller --onefile --windowed --name ArrayifySoundTanks main.py
```

For a CLI build:

```bash
pyinstaller --onefile --console --name ArrayifySoundTanksCLI main.py
```

If you want the `Files` folder bundled with the executable, add it like this:

```bash
# Windows
pyinstaller --onefile --windowed --add-data "Files;Files" --name ArrayifySoundTanks main.py

# macOS and Linux
pyinstaller --onefile --windowed --add-data "Files:Files" --name ArrayifySoundTanks main.py
```

The GUI build is the best choice for end users. The CLI build is useful for automation and batch runs.

When you package the app, remember that PyInstaller freezes the interpreter you build with. If that build Python has Tkinter, the GUI executable will include it.
