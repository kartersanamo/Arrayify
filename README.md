# Arrayify and Sound Tanks

This project converts tank register spreadsheets into array-based rows, applies soundings from `.docx` tables, and normalizes register names to tank tag names.

The runtime code only uses the Python standard library. The GUI will automatically relaunch itself with a Tk-capable Python interpreter if the current one was built without Tkinter.

## Structure

- `main.py` is the entrypoint and supports both CLI and GUI launch.
- `tank_tools/config.py` holds project paths.
- `tank_tools/io.py` handles CSV I/O.
- `tank_tools/rules.py` contains naming and sounding rules.
- `tank_tools/services/` contains one workflow class per file (`ArrayifyService`, `TankSoundingService`, `TagNormalizationService`).
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

PyInstaller builds for the OS you run it on. Build the Windows `.exe` on Windows, and build the macOS `.app` on a Mac.

Install PyInstaller in the same environment you use to build:

```bash
# Windows / Linux (venv recommended)
pip install pyinstaller

# macOS (Homebrew is also fine)
pip install pyinstaller
# or: brew install pyinstaller
```

Use a Python build that includes **Tkinter** (required for the GUI). On macOS, the Homebrew `python@3.14` formula often needs the Tk extra:

```bash
brew install python@3.14 python-tk@3.14
python3 -c "import tkinter"
```

If that import fails, the packaged app will not be able to open the GUI.

### GUI build (all platforms)

Base command:

```bash
pyinstaller --onefile --windowed --name Arrayify main.py
```

- `--windowed` hides the console window and builds a GUI-first app (no terminal).
- `--onefile` bundles into a single executable (on macOS this still produces a `.app` wrapper in `dist/`).

Packaged builds **open the GUI automatically** when you double-click the app. You do not need `--gui`. Use `--cli` only if you built a console binary and want the text menu.

### macOS GUI build

From the project root on a Mac:

```bash
cd /path/to/ArrayifyAndSoundTanks

# Build a windowed .app with icon and bundled data
pyinstaller --onefile --windowed --name Arrayify \
  --icon assets/arrayify.icns \
  --add-data "assets/arrayify_icon.png:assets" \
  main.py

# Build a console .app with icon and bundled data
pyinstaller --onefile --console --name Arrayify \
  --icon assets/arrayify.icns \
  --add-data "assets/arrayify_icon.png:assets" \
  main.py
```

After the build finishes, open the app from Finder or Terminal:

```bash
open dist/Arrayify.app
```

**macOS notes:**

- Output appears under `dist/Arrayify.app` (Finder app bundle).
- `--icon assets/arrayify.icns` sets the Dock / Finder icon (generate `assets/arrayify.icns` from `assets/arrayify_icon.png` with `iconutil` if needed).
- If macOS blocks the app (“unidentified developer”), right-click the app → **Open**, or sign it with your Apple Developer ID for distribution.
- The repo also includes `Arrayify.app` for running from source with the correct Dock name; PyInstaller produces a separate distributable in `dist/`.

Optional: rebuild from the checked-in spec (produces `dist/Arrayify.app`):

```bash
pyinstaller Arrayify.spec
open dist/Arrayify.app
```

### CLI build

```bash
pyinstaller --onefile --console --name ArrayifyCLI main.py
```

### Bundle the sample `Files` folder (Windows / Linux)

```bash
# Windows
pyinstaller --onefile --windowed --add-data "Files;Files" --name Arrayify main.py

# Linux
pyinstaller --onefile --windowed --add-data "Files:Files" --name Arrayify main.py
```

The GUI build is the best choice for end users. The CLI build is useful for automation and batch runs.

When you package the app, PyInstaller freezes the interpreter you build with. That interpreter must have Tkinter available at build time for the GUI executable to work.