# Arrayify and Sound Tanks

This project converts tank register spreadsheets into array-based rows, applies soundings from `.docx` tables, and normalizes register names to tank tag names.

## Structure

- `main.py` is a thin CLI entrypoint.
- `tank_tools/config.py` holds project paths.
- `tank_tools/io.py` handles CSV I/O.
- `tank_tools/rules.py` contains naming and sounding rules.
- `tank_tools/services.py` contains the workflow classes.
- `tank_tools/cli.py` wires the services together.

## Usage

Install dependencies and run the entrypoint:

```bash
pip install -r requirements.txt
python main.py
```

Choose one workflow from the menu:

- Array-ify points
- Sound tanks
- Normalize tag names
- Run all three in sequence
