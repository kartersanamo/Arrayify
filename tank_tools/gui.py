from __future__ import annotations

import csv
import queue
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from contextlib import redirect_stderr, redirect_stdout

try:
    import tkinter as tk
    from tkinter import END, LEFT, RIGHT, BOTH, X, Y, filedialog, messagebox, simpledialog, StringVar, Text, Tk
    from tkinter import ttk
except ModuleNotFoundError:  # pragma: no cover - handled at runtime in environments without Tk
    tk = None
    END = LEFT = RIGHT = BOTH = X = Y = None
    filedialog = messagebox = simpledialog = None
    StringVar = Text = Tk = object
    ttk = None

from tank_tools.config import ProjectConfig
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import ArrayifyService, TagNormalizationService, TankSoundingService


@dataclass
class GuiPaths:
    input_file: Path | None = None
    docx_folder: Path | None = None
    export_file: Path | None = None


class _QueueWriter:
    def __init__(self, event_queue: queue.Queue[dict[str, object]]) -> None:
        self._event_queue = event_queue
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._event_queue.put({"type": "log", "message": line + "\n"})
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._event_queue.put({"type": "log", "message": self._buffer})
        self._buffer = ""


class TankManagerApp:
    def __init__(self, root: Tk) -> None:
        if tk is None or ttk is None:
            raise RuntimeError("Tkinter is not available in this Python environment.")

        self._root = root
        self._root.title("Arrayify and Sound Tanks")
        self._root.geometry("1200x780")

        self._config = ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._arrayify_service = ArrayifyService(self._config, self._csv_repository, self._rules)
        self._sounding_service = TankSoundingService(self._config, self._csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(self._config, self._csv_repository, self._rules)

        self._paths = GuiPaths()
        self._event_queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._latest_rows: list[list[str]] = []
        self._worker: threading.Thread | None = None
        self._waiting_prompt: dict[str, object] | None = None

        self.workflow_var = StringVar(value="normalize")
        self.input_var = StringVar(value="")
        self.docx_folder_var = StringVar(value=str(self._config.new_sounds_dir))
        self.export_var = StringVar(value="")
        self.status_var = StringVar(value="Ready")

        self._build_layout()
        self._root.after(100, self._process_events)

    def run(self) -> None:
        self._root.mainloop()

    def _build_layout(self) -> None:
        outer = ttk.Frame(self._root, padding=12)
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Label(outer, text="Tank Workflow Manager", font=("Helvetica", 18, "bold"))
        header.pack(anchor="w", pady=(0, 10))

        controls = ttk.Frame(outer)
        controls.pack(fill=X, pady=(0, 10))

        workflow_box = ttk.LabelFrame(controls, text="Workflow")
        workflow_box.pack(side=LEFT, fill=Y, padx=(0, 10))
        for label, value in (
            ("Normalize", "normalize"),
            ("Arrayify", "arrayify"),
            ("Sound", "sound"),
            ("All", "all"),
        ):
            ttk.Radiobutton(workflow_box, text=label, value=value, variable=self.workflow_var).pack(anchor="w", padx=10, pady=2)

        path_box = ttk.Frame(controls)
        path_box.pack(side=LEFT, fill=BOTH, expand=True)

        self._add_path_row(path_box, "Input CSV", self.input_var, self._choose_input_file)
        self._add_path_row(path_box, "DOCX Folder", self.docx_folder_var, self._choose_docx_folder)
        self._add_path_row(path_box, "Export CSV", self.export_var, self._choose_export_file)

        button_bar = ttk.Frame(outer)
        button_bar.pack(fill=X, pady=(0, 10))

        self.run_button = ttk.Button(button_bar, text="Run Workflow", command=self._start_workflow)
        self.run_button.pack(side=LEFT, padx=(0, 8))

        ttk.Button(button_bar, text="Export Current Preview", command=self._export_current_preview).pack(side=LEFT, padx=(0, 8))
        ttk.Button(button_bar, text="Clear Preview", command=self._clear_preview).pack(side=LEFT)

        status_bar = ttk.Label(outer, textvariable=self.status_var)
        status_bar.pack(fill=X, pady=(0, 8))

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=BOTH, expand=True)

        log_frame = ttk.Labelframe(body, text="Live Log")
        preview_frame = ttk.Labelframe(body, text="Live Row Preview")
        body.add(log_frame, weight=1)
        body.add(preview_frame, weight=2)

        self.log_text = Text(log_frame, wrap="word", height=24)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        log_scroll.pack(side=RIGHT, fill=Y)

        preview_columns = ("index", "name", "description", "initial", "ioaddress")
        self.preview_tree = ttk.Treeview(preview_frame, columns=preview_columns, show="headings", height=24)
        for column, heading, width in (
            ("index", "#", 70),
            ("name", "Name", 240),
            ("description", "Description", 360),
            ("initial", "Initial Value", 140),
            ("ioaddress", "IOAddress", 130),
        ):
            self.preview_tree.heading(column, text=heading)
            self.preview_tree.column(column, width=width, anchor="w")

        preview_scroll = ttk.Scrollbar(preview_frame, command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=preview_scroll.set)
        self.preview_tree.pack(side=LEFT, fill=BOTH, expand=True)
        preview_scroll.pack(side=RIGHT, fill=Y)

    def _add_path_row(self, parent: ttk.Frame, label: str, text_var: StringVar, chooser: Callable[[], None]) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=3)
        ttk.Label(row, text=label, width=12).pack(side=LEFT)
        entry = ttk.Entry(row, textvariable=text_var)
        entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        ttk.Button(row, text="Browse", command=chooser).pack(side=LEFT)

    def _choose_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select input CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected:
            path = Path(selected)
            self.input_var.set(str(path))
            self._paths.input_file = path

    def _choose_docx_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select DOCX folder")
        if selected:
            path = Path(selected)
            self.docx_folder_var.set(str(path))
            self._paths.docx_folder = path

    def _choose_export_file(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Choose export CSV path",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected:
            path = Path(selected)
            self.export_var.set(str(path))
            self._paths.export_file = path

    def _start_workflow(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showinfo("Workflow running", "A workflow is already running.")
            return

        self._clear_preview()
        self.status_var.set("Working...")
        self.run_button.configure(state="disabled")

        self._worker = threading.Thread(target=self._run_selected_workflow, daemon=True)
        self._worker.start()

    def _run_selected_workflow(self) -> None:
        log_writer = _QueueWriter(self._event_queue)
        try:
            with redirect_stdout(log_writer), redirect_stderr(log_writer):
                workflow = self.workflow_var.get()
                input_path = Path(self.input_var.get()).expanduser() if self.input_var.get().strip() else None
                export_path = Path(self.export_var.get()).expanduser() if self.export_var.get().strip() else None
                sound_folder = Path(self.docx_folder_var.get()).expanduser() if self.docx_folder_var.get().strip() else None

                if workflow == "arrayify":
                    rows = self._arrayify_service.arrayify_points(
                        input_path=input_path,
                        output_path=export_path or self._temp_path("arrayified.csv"),
                        event_callback=self._enqueue_event,
                    )
                elif workflow == "sound":
                    rows = self._sounding_service.sound_tanks(
                        sound_folder=sound_folder,
                        input_path=input_path,
                        output_path=export_path or self._temp_path("sounded.csv"),
                        event_callback=self._enqueue_event,
                    )
                elif workflow == "all":
                    temp_arrayified = self._temp_path("arrayified.csv")
                    temp_sounded = self._temp_path("sounded.csv")
                    self._arrayify_service.arrayify_points(
                        input_path=input_path,
                        output_path=temp_arrayified,
                        event_callback=self._enqueue_event,
                    )
                    self._sounding_service.sound_tanks(
                        sound_folder=sound_folder,
                        input_path=temp_arrayified,
                        output_path=temp_sounded,
                        event_callback=self._enqueue_event,
                    )
                    rows = self._normalization_service.normalize_tags(
                        input_path=temp_sounded,
                        output_path=export_path or self._temp_path("normalized.csv"),
                        event_callback=self._enqueue_event,
                        custom_tag_provider=self._prompt_for_custom_tag,
                    )
                else:
                    rows = self._normalization_service.normalize_tags(
                        input_path=input_path,
                        output_path=export_path or self._temp_path("normalized.csv"),
                        event_callback=self._enqueue_event,
                        custom_tag_provider=self._prompt_for_custom_tag,
                    )

                if rows is not None:
                    self._event_queue.put({"type": "rows", "rows": rows})
                self._event_queue.put({"type": "status", "message": "Workflow finished."})
        except Exception as exc:  # pragma: no cover - surfaced in GUI
            self._event_queue.put({"type": "error", "message": str(exc)})
        finally:
            self._event_queue.put({"type": "done"})

    def _temp_path(self, suffix: str) -> Path:
        return Path(tempfile.gettempdir()) / f"arrayify_sound_tanks_{suffix}"

    def _enqueue_event(self, event: dict[str, object]) -> None:
        self._event_queue.put(event)

    def _prompt_for_custom_tag(self, description: str) -> str | None:
        response_box: dict[str, object] = {"event": threading.Event(), "value": None}
        self._event_queue.put({"type": "prompt", "description": description, "box": response_box})
        response_box["event"].wait()  # type: ignore[union-attr]
        return response_box["value"]  # type: ignore[return-value]

    def _process_events(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                event_type = event.get("type")

                if event_type == "log":
                    self._append_log(str(event.get("message", "")))
                elif event_type == "status":
                    self.status_var.set(str(event.get("message", "Ready")))
                elif event_type == "preview":
                    rows = event.get("rows")
                    if isinstance(rows, list):
                        self._latest_rows = rows
                        self._refresh_preview(rows)
                    description = event.get("description")
                    if description:
                        self.status_var.set(f"Updated: {description}")
                elif event_type == "rows":
                    rows = event.get("rows")
                    if isinstance(rows, list):
                        self._latest_rows = rows
                        self._refresh_preview(rows)
                elif event_type == "prompt":
                    self._handle_prompt(event)
                elif event_type == "error":
                    messagebox.showerror("Workflow error", str(event.get("message", "Unknown error")))
                elif event_type == "done":
                    self.run_button.configure(state="normal")
        except queue.Empty:
            pass

        self._root.after(100, self._process_events)

    def _handle_prompt(self, event: dict[str, object]) -> None:
        box = event.get("box")
        description = str(event.get("description", ""))
        if not isinstance(box, dict):
            return

        response = simpledialog.askstring(
            "Custom tag needed",
            f"No tag match for '{description}'. Enter a custom tag prefix, or leave blank to skip:",
            parent=self._root,
        )
        box["value"] = response
        prompt_event = box.get("event")
        if isinstance(prompt_event, threading.Event):
            prompt_event.set()

    def _append_log(self, message: str) -> None:
        self.log_text.insert(END, message)
        self.log_text.see(END)

    def _refresh_preview(self, rows: list[list[str]]) -> None:
        for item_id in self.preview_tree.get_children():
            self.preview_tree.delete(item_id)

        display_rows = rows[:250]
        for index, row in enumerate(display_rows, start=1):
            name = row[0] if len(row) > 0 else ""
            description = row[2] if len(row) > 2 else ""
            initial_value = row[12] if len(row) > 12 else ""
            ioaddress = row[15] if len(row) > 15 else ""
            self.preview_tree.insert("", END, values=(index, name, description, initial_value, ioaddress))

    def _clear_preview(self) -> None:
        self.log_text.delete("1.0", END)
        self._latest_rows = []
        self._refresh_preview([])
        self.status_var.set("Ready")

    def _export_current_preview(self) -> None:
        if not self._latest_rows:
            messagebox.showinfo("Nothing to export", "Run a workflow first so there is something to export.")
            return

        selected = filedialog.asksaveasfilename(
            title="Export current preview",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return

        export_path = Path(selected)
        with export_path.open("w", newline="") as output_file:
            writer = csv.writer(output_file, dialect="excel")
            writer.writerows(self._latest_rows)

        self.status_var.set(f"Exported to {export_path}")
