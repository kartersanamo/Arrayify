# Arrayify

Proficy tank register tooling for Edison Chouest Offshore. Converts CSV exports, applies soundings, labels work registers, and produces dual-pass import files.

## Features

- **Arrayify** — expand parent tank rows into child array elements
- **Resound** — apply `.docx` sounding tables to tank registers
- **Tank registers** — label work-register rows as `{prefix}_WORK_REG_{n}` (e.g. `FO_2P_WORK_REG_0`)
- **Normalize** — standardize variable names to tank tag names
- **Run all** — full pipeline in order (arrayify → resound → tank registers → normalize)
- **Export** — dual Proficy import files: `{stem}-BYREF-FIRST.csv` and `{stem}-BYNAME-SECOND.csv`
- **GUI + CLI** — same workflows in a Tkinter window or from the terminal

Bundled sample data: `Files/h221Test.csv` and `Files/NewSounds/*.DOCX`.

---

## Download and run (pre-built)

### macOS

1. Download **`Arrayify-Mac.zip`**
2. Unzip and open **`Arrayify.app`**

**GUI (default):** double-click `Arrayify.app`, or:

```bash
open Arrayify.app
```

**CLI:**

```bash
./Arrayify.app/Contents/MacOS/Arrayify run-all --input ./JuneThird.csv --docx-dir ./Files/NewSounds
./Arrayify.app/Contents/MacOS/Arrayify --help
```

### Windows

1. Download **`Arrayify.exe`** (built on Windows)
2. Place your CSV and DOCX folder next to it, or pass full paths

**GUI:** double-click `Arrayify.exe`

**CLI:**

```cmd
Arrayify.exe run-all --input JuneThird.csv --docx-dir Files\NewSounds
Arrayify.exe --help
```

---

## Run from source

Requires Python 3 with **Tkinter** (for GUI).

```bash
git clone <repo-url>
cd Arraify
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt   # no runtime deps; stdlib only
```

**GUI:**

```bash
python main.py --gui
```

**CLI:**

```bash
python main.py --cli run-all --input ./Files/h221Test.csv --docx-dir ./Files/NewSounds
python main.py --cli --help
```

Subcommands: `arrayify`, `sound`, `tank-registers`, `normalize`, `run-all`, `export`, `menu`.

Common flags: `--output-dir`, `--output`, `--custom-tag "Description=PREFIX"`.

If your Python lacks Tkinter, the app tries to relaunch with a Tk-capable interpreter (macOS).

---

## Build from source

Install PyInstaller in the same environment you use to build. The build Python must include Tkinter for the GUI to work.

```bash
pip install pyinstaller
python3 -c "import tkinter"      # must succeed
```

**macOS (.app + zip):**

```bash
pyinstaller --noconfirm Arrayify.spec
cd dist && zip -r Arrayify-Mac.zip Arrayify.app
```

Upload **`dist/Arrayify-Mac.zip`** for macOS users.

**Windows (.exe):**

```cmd
pyinstaller --noconfirm Arrayify.spec
```

Upload **`dist/Arrayify.exe`** for Windows users.

If macOS blocks the app (“unidentified developer”), right-click → **Open**.
