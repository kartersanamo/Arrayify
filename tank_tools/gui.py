from __future__ import annotations

import csv
import copy
import queue
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from contextlib import redirect_stderr, redirect_stdout

try:
    import tkinter as tk
    from tkinter import (
        END,
        HORIZONTAL,
        LEFT,
        RIGHT,
        BOTH,
        VERTICAL,
        X,
        Y,
        BooleanVar,
        filedialog,
        messagebox,
        simpledialog,
        StringVar,
        Text,
        Tk,
    )
    from tkinter import ttk
except ModuleNotFoundError:  # pragma: no cover - handled at runtime in environments without Tk
    tk = None
    END = HORIZONTAL = LEFT = RIGHT = BOTH = VERTICAL = X = Y = None
    filedialog = messagebox = simpledialog = None
    BooleanVar = StringVar = Text = Tk = object
    ttk = None

from tank_tools.app_identity import APP_TITLE, apply_tk_window_identity, configure_app_identity
from tank_tools.change_tracker import RowChangeTracker
from tank_tools.config import ProjectConfig
from tank_tools.work_reg_registry import scan_work_register_bindings
from tank_tools.io import CsvRepository
from tank_tools.rules import TankRules
from tank_tools.services import (
    ArrayifyService,
    TagNormalizationService,
    TankSoundingService,
    TankWorkRegService,
)

from tank_tools.runtime import resource_path

APP_ICON_PATH = resource_path("assets", "arrayify_icon.png")


@dataclass
class GuiPaths:
    input_file: Path | None = None
    docx_folder: Path | None = None


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
        configure_app_identity(APP_TITLE)
        self._root.title(APP_TITLE)
        self._root.geometry("1200x780")
        self._icon_image: tk.PhotoImage | None = None
        self._apply_window_icon()
        apply_tk_window_identity(self._root, APP_TITLE)
        self._root.after(250, lambda: apply_tk_window_identity(self._root, APP_TITLE))

        self._config = ProjectConfig.default()
        self._csv_repository = CsvRepository()
        self._rules = TankRules()
        self._arrayify_service = ArrayifyService(self._config, self._csv_repository, self._rules)
        self._sounding_service = TankSoundingService(self._config, self._csv_repository, self._rules)
        self._normalization_service = TagNormalizationService(self._config, self._csv_repository, self._rules)
        self._work_reg_service = TankWorkRegService(self._config, self._csv_repository, self._rules)

        self._paths = GuiPaths()
        self._event_queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._latest_rows: list[list[str]] = []
        self._baseline_rows: list[list[str]] = []
        self._change_tracker: RowChangeTracker | None = None
        self._work_reg_bindings: dict[str, list[str]] = {}
        self._worker: threading.Thread | None = None
        self._input_loaded = False
        self._docx_valid = False

        self.workflow_var = StringVar(value="")
        self.input_var = StringVar(value="")
        self.docx_folder_var = StringVar(value="")
        self.status_var = StringVar(value="Choose an input CSV to begin.")

        self._build_layout()
        self.workflow_var.trace_add("write", self._on_workflow_changed)
        self._update_control_states()
        self._root.after(100, self._process_events)

    def run(self) -> None:
        self._root.mainloop()

    def _apply_window_icon(self) -> None:
        if not APP_ICON_PATH.is_file():
            return

        try:
            self._icon_image = tk.PhotoImage(file=str(APP_ICON_PATH))
            self._root.iconphoto(True, self._icon_image)
        except tk.TclError:
            if sys.platform.startswith("win"):
                ico_path = APP_ICON_PATH.with_suffix(".ico")
                if ico_path.is_file():
                    self._root.iconbitmap(str(ico_path))

    def _build_layout(self) -> None:
        outer = ttk.Frame(self._root, padding=12)
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Label(outer, text="Tank Workflow Manager", font=("Helvetica", 18, "bold"))
        header.pack(anchor="w", pady=(0, 6))

        input_box = ttk.LabelFrame(outer, text="Input CSV (required first)")
        input_box.pack(fill=X, pady=(0, 10))
        self._add_path_row(input_box, "Input CSV", self.input_var, self._choose_input_file)

        action_bar = ttk.Frame(outer)
        action_bar.pack(fill=X, pady=(0, 10))

        button_cluster = ttk.Frame(action_bar)
        button_cluster.pack(side=LEFT)

        self.run_button = ttk.Button(button_cluster, text="Run Workflow", command=self._start_workflow, state="disabled")
        self.run_button.pack(side=LEFT, padx=(0, 8))

        self.export_button = ttk.Button(button_cluster, text="Export", command=self._export_current_preview, state="disabled")
        self.export_button.pack(side=LEFT, padx=(0, 8))

        ttk.Button(button_cluster, text="Clear Logs", command=self._clear_logs).pack(side=LEFT)

        workflow_box = ttk.LabelFrame(action_bar, text="Workflow")
        workflow_box.pack(side=RIGHT, fill=Y)
        workflow_row = ttk.Frame(workflow_box)
        workflow_row.pack(padx=8, pady=6)
        self._workflow_radios: list[ttk.Radiobutton] = []
        for label, value in (
            ("Normalize", "normalize"),
            ("Arrayify", "arrayify"),
            ("Sound", "sound"),
            ("All", "all"),
        ):
            radio = ttk.Radiobutton(
                workflow_row,
                text=label,
                value=value,
                variable=self.workflow_var,
                state="disabled",
            )
            radio.pack(side=LEFT, padx=(0, 12))
            self._workflow_radios.append(radio)

        self.docx_box = ttk.LabelFrame(outer, text="DOCX Folder (required for Sound)")
        self._add_path_row(self.docx_box, "DOCX Folder", self.docx_folder_var, self._choose_docx_folder)
        self.docx_box.pack_forget()

        status_bar = ttk.Label(outer, textvariable=self.status_var)
        status_bar.pack(fill=X, pady=(0, 8))

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=BOTH, expand=True)

        log_frame = ttk.Labelframe(body, text="Console")
        preview_frame = ttk.Labelframe(body, text="Live Row Preview")
        body.add(log_frame, weight=1)
        body.add(preview_frame, weight=2)

        console_font = self._console_font()
        self.log_text = Text(
            log_frame,
            wrap="word",
            height=24,
            bg="#0c0c0c",
            fg="#cccccc",
            insertbackground="#cccccc",
            selectbackground="#264f78",
            selectforeground="#ffffff",
            font=console_font,
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
            cursor="arrow",
        )
        self._configure_console_tags()
        self._bind_console_readonly()
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.configure(state="disabled")
        self._append_log("Application started.", level="muted")

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
        row.pack(fill=X, pady=3, padx=6)
        ttk.Label(row, text=label, width=12).pack(side=LEFT)
        entry = ttk.Entry(row, textvariable=text_var)
        entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        ttk.Button(row, text="Browse", command=chooser).pack(side=LEFT)

    def _choose_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select input CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return

        path = Path(selected)
        try:
            rows = self._csv_repository.read_rows(path)
        except OSError as exc:
            messagebox.showerror("Input error", f"Could not read CSV: {exc}")
            return

        if not rows:
            messagebox.showerror("Input error", "The selected CSV file is empty.")
            return

        self.input_var.set(str(path))
        self._paths.input_file = path
        self._input_loaded = True
        self._baseline_rows = copy.deepcopy(rows)
        self._change_tracker = RowChangeTracker(self._baseline_rows)
        self._work_reg_bindings = scan_work_register_bindings(rows, self._rules)
        self._latest_rows = rows
        self._refresh_preview(rows)
        self.workflow_var.set("")
        self._append_log(f"Loaded input CSV: {path}\n")
        self.status_var.set(f"Loaded {len(rows) - 1} data rows from {path.name}. Choose a workflow.")
        self._update_control_states()

    def _choose_docx_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select DOCX folder")
        if not selected:
            return

        path = Path(selected)
        self.docx_folder_var.set(str(path))
        self._paths.docx_folder = path
        self._docx_valid = self._validate_docx_folder(path)
        if self._docx_valid:
            self.status_var.set(f"DOCX folder ready: {path}")
        else:
            self.status_var.set("DOCX folder must exist and contain at least one .docx file.")
        self._update_control_states()

    def _validate_docx_folder(self, folder: Path) -> bool:
        if not folder.is_dir():
            return False
        docx_files = list(folder.glob("*.docx")) + list(folder.glob("*.DOCX"))
        return len(docx_files) > 0

    def _on_workflow_changed(self, *_args: object) -> None:
        workflow = self.workflow_var.get()
        if workflow in {"sound", "all"}:
            self.docx_box.pack(fill=X, pady=(0, 10))
            if self._paths.docx_folder is not None:
                self._docx_valid = self._validate_docx_folder(self._paths.docx_folder)
        else:
            self.docx_box.pack_forget()
        self._update_control_states()

    def _update_control_states(self) -> None:
        workflow_state = "normal" if self._input_loaded else "disabled"
        for radio in self._workflow_radios:
            radio.configure(state=workflow_state)

        can_run = self._can_run_workflow()
        self.run_button.configure(state="normal" if can_run else "disabled")
        self.export_button.configure(state="normal" if self._latest_rows else "disabled")

    def _can_run_workflow(self) -> bool:
        if not self._input_loaded or not self._latest_rows:
            return False

        workflow = self.workflow_var.get()
        if workflow not in {"normalize", "arrayify", "sound", "all"}:
            return False

        if workflow in {"sound", "all"}:
            folder = self._paths.docx_folder
            if folder is None:
                return False
            return self._validate_docx_folder(folder)

        return True

    def _start_workflow(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showinfo("Workflow running", "A workflow is already running.")
            return

        if not self._can_run_workflow():
            messagebox.showinfo("Not ready", "Choose an input CSV, select a workflow, and complete any required options.")
            return

        self.status_var.set("Working...")
        self.run_button.configure(state="disabled")

        self._worker = threading.Thread(target=self._run_selected_workflow, daemon=True)
        self._worker.start()

    def _run_selected_workflow(self) -> None:
        log_writer = _QueueWriter(self._event_queue)
        try:
            with redirect_stdout(log_writer), redirect_stderr(log_writer):
                workflow = self.workflow_var.get()
                preview_rows = copy.deepcopy(self._latest_rows)
                sound_folder = self._paths.docx_folder
                tag_prefix_path = self._paths.input_file

                if workflow == "arrayify":
                    rows = self._arrayify_service.arrayify_points(
                        input_rows=preview_rows,
                        write_output=False,
                        event_callback=self._enqueue_event,
                    )
                elif workflow == "sound":
                    rows = self._sounding_service.sound_tanks(
                        sound_folder=sound_folder,
                        input_rows=preview_rows,
                        write_output=False,
                        cli_style=False,
                        event_callback=self._enqueue_event,
                    )
                elif workflow == "all":
                    arrayified = self._arrayify_service.arrayify_points(
                        input_rows=preview_rows,
                        write_output=False,
                        event_callback=self._enqueue_event,
                    )
                    if arrayified is None:
                        rows = None
                    else:
                        sounded = self._sounding_service.sound_tanks(
                            sound_folder=sound_folder,
                            input_rows=arrayified,
                            write_output=False,
                            cli_style=False,
                            event_callback=self._enqueue_event,
                        )
                        if sounded is None:
                            rows = None
                        else:
                            rows = self._run_normalize_workflow(sounded, tag_prefix_path)
                else:
                    rows = self._run_normalize_workflow(preview_rows, tag_prefix_path)

                if rows is not None:
                    self._event_queue.put({"type": "rows", "rows": rows})
                self._event_queue.put({"type": "status", "message": "Workflow finished."})
        except Exception as exc:  # pragma: no cover - surfaced in GUI
            self._event_queue.put({"type": "error", "message": str(exc)})
        finally:
            self._event_queue.put({"type": "done"})

    def _enqueue_event(self, event: dict[str, object]) -> None:
        self._event_queue.put(event)

    def _run_normalize_workflow(
        self,
        rows: list[list[str]],
        tag_prefix_path: Path | None,
    ) -> list[list[str]] | None:
        labeled_rows = self._work_reg_service.label_work_registers(
            self._work_reg_bindings,
            input_rows=rows,
            tag_prefix_input_path=tag_prefix_path,
            write_output=False,
            cli_style=False,
            event_callback=self._enqueue_event,
            custom_tag_provider=self._prompt_for_custom_tag,
        )
        if labeled_rows is None:
            return None

        return self._normalization_service.normalize_tags(
            input_rows=labeled_rows,
            tag_prefix_input_path=tag_prefix_path,
            write_output=False,
            cli_style=False,
            live_preview=False,
            event_callback=self._enqueue_event,
            custom_tag_provider=self._prompt_for_custom_tag,
        )

    def _prompt_for_custom_tag(self, description: str) -> str | None:
        result: dict[str, str | None] = {"value": None}
        done = threading.Event()

        def show_dialog() -> None:
            try:
                result["value"] = simpledialog.askstring(
                    "Custom tag needed",
                    f"No tag match for '{description}'. Enter a custom tag prefix, or leave blank to skip:",
                    parent=self._root,
                )
            finally:
                done.set()

        self._root.after(0, show_dialog)
        done.wait()
        return result["value"]

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
                    description = event.get("description")
                    if description:
                        self.status_var.set(f"Updated: {description}")
                elif event_type == "rows":
                    rows = event.get("rows")
                    if isinstance(rows, list):
                        self._latest_rows = rows
                        self._refresh_preview(rows)
                elif event_type == "error":
                    error_message = str(event.get("message", "Unknown error"))
                    self._append_log(error_message, level="error")
                    messagebox.showerror("Workflow error", error_message)
                elif event_type == "done":
                    self._update_control_states()
        except queue.Empty:
            pass

        self._root.after(100, self._process_events)

    @staticmethod
    def _console_font() -> tuple[str, int]:
        if sys.platform == "darwin":
            return ("Menlo", 8)
        if sys.platform.startswith("win"):
            return ("Consolas", 8)
        return ("DejaVu Sans Mono", 8)

    def _configure_console_tags(self) -> None:
        tag_styles = {
            "timestamp": {"foreground": "#6a9955"},
            "info": {"foreground": "#cccccc"},
            "muted": {"foreground": "#808080"},
            "header": {"foreground": "#4fc1ff"},
            "success": {"foreground": "#4ec9b0"},
            "detail": {"foreground": "#9cdcfe"},
            "warning": {"foreground": "#dcdcaa"},
            "error": {"foreground": "#f48771"},
        }
        for tag_name, style in tag_styles.items():
            self.log_text.tag_configure(tag_name, **style)

    def _bind_console_readonly(self) -> None:
        def block_edit(_event: tk.Event) -> str:
            return "break"

        def allow_navigation_or_copy(event: tk.Event) -> str | None:
            key = event.keysym
            if key in {
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Prior",
                "Next",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Meta_L",
                "Meta_R",
                "Alt_L",
                "Alt_R",
                "Command",
            }:
                return None
            if (event.state & 0x4 or event.state & 0x8 or event.state & 0x80) and key.lower() in {"c", "a"}:
                return None
            return "break"

        self.log_text.bind("<Key>", allow_navigation_or_copy)
        for sequence in ("<Button-2>", "<Button-3>", "<<Paste>>", "<<Cut>>"):
            self.log_text.bind(sequence, block_edit)

    @staticmethod
    def _log_tag_for_line(line: str) -> str:
        lowered = line.lower()
        if any(
            token in lowered
            for token in (
                "not found",
                "conflicting",
                "empty",
                "error",
                "skipping",
                "could not",
                "no arrayified",
                "no csv row",
                "duplicate",
            )
        ):
            return "error"
        if any(token in lowered for token in ("without", "unmatched", "none", "warning")):
            return "warning"
        if any(
            token in lowered
            for token in (
                "wrote",
                "finished",
                "normalized",
                "matched tanks:",
                "loaded input",
                "ready",
                "exported to",
            )
        ) or ("->" in line and "|" in line):
            return "success"
        if line.startswith("  ") and "|" in line:
            return "detail"
        if line.startswith("- ") or line.startswith("  - "):
            return "detail"
        if any(
            token in lowered
            for token in (
                "array-ify",
                "sounding tanks",
                "normalizing tags",
                "summary",
                "report",
                "starting",
                "total tanks",
                "total points",
                "renamed rows",
            )
        ):
            return "header"
        return "info"

    def _append_log(self, message: str, level: str | None = None) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        lines = message.splitlines() or [message]

        self.log_text.configure(state="normal")
        for line in lines:
            stripped = line.strip()
            if not stripped and len(lines) > 1:
                continue

            tag = level or self._log_tag_for_line(line)
            self.log_text.insert(END, f"[{timestamp}] ", "timestamp")
            self.log_text.insert(END, line.rstrip("\n") + "\n", tag)

        self.log_text.configure(state="disabled")
        self.log_text.see(END)

    def _refresh_preview(self, rows: list[list[str]]) -> None:
        children = self.preview_tree.get_children()
        if children:
            self.preview_tree.delete(*children)

        for index, row in enumerate(rows, start=1):
            name = row[0] if len(row) > 0 else ""
            description = row[2] if len(row) > 2 else ""
            initial_value = row[12] if len(row) > 12 else ""
            ioaddress = row[15] if len(row) > 15 else ""
            self.preview_tree.insert("", END, values=(index, name, description, initial_value, ioaddress))

        self._update_control_states()

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")
        self._append_log("Console cleared.", level="muted")

    def _export_current_preview(self) -> None:
        if not self._latest_rows:
            messagebox.showinfo("Nothing to export", "Load a CSV or run a workflow so there is something to export.")
            return

        if self._change_tracker is None:
            messagebox.showinfo("Nothing to export", "Load a CSV before exporting modified rows.")
            return

        export_rows = self._change_tracker.rows_for_export(self._latest_rows)
        modified_count = max(0, len(export_rows) - 1)
        if modified_count == 0:
            messagebox.showinfo("Nothing to export", "No rows were modified from the loaded CSV.")
            return

        selected = filedialog.asksaveasfilename(
            title="Export modified rows",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return

        export_path = Path(selected)
        with export_path.open("w", newline="") as output_file:
            writer = csv.writer(output_file, dialect="excel")
            writer.writerows(export_rows)

        self.status_var.set(f"Exported {modified_count} modified rows to {export_path}")
