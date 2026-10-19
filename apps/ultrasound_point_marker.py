import csv
import json
import math
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

BASE_COLUMNS = [
    "Project",
    "SourceFolder",
    "Trial",
    "MeasurementID",
    "Measurement",
    "RecordTime",
    "StartFrameIndex",
    "StartFilename",
    "StartX_px",
    "StartY_px",
    "EndFrameIndex",
    "EndFilename",
    "EndX_px",
    "EndY_px",
    "DeltaX_px",
    "DeltaY_px",
    "Distance_px",
    "SpacingX_mm_per_px",
    "SpacingY_mm_per_px",
    "Distance_mm",
]


def natural_key(value):
    """Sort frame_2 before frame_10."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(value))
    ]


def new_measurement(name="Structure A"):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "start": None,
        "end": None,
    }


def atomic_write(path, write_function):
    """Write beside the destination, then replace it after a successful write."""
    path = Path(path)
    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            write_function(handle)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class UltrasoundPointMarker:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Cross-frame Point Marker")

        self.projects_dir = (
            Path(__file__).resolve().parent / "point_marker_projects"
        )
        self.projects_dir.mkdir(exist_ok=True)

        self.project = None
        self.project_path = None

        self.in_main = False
        self.loading_form = False
        self.trial_paths = []
        self.trial_key = None
        self.frames = []
        self.frame_index = -1

        self.image = None
        self.photo = None
        self.transform = None

        self.measurement_index = 0
        self.armed_endpoint = None
        self.play_job = None
        self.save_job = None

        self.custom_vars = {}

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<KeyPress>", self.handle_key)
        self.show_menu()

    # ------------------------------------------------------------------
    # Project persistence
    # ------------------------------------------------------------------

    @property
    def trial(self):
        if self.project is None or self.trial_key is None:
            return None
        return self.project["trials"].get(self.trial_key)

    @property
    def measurement(self):
        if self.trial is None:
            return None

        measurements = self.trial["measurements"]
        if 0 <= self.measurement_index < len(measurements):
            return measurements[self.measurement_index]

        return None

    def cancel_pending_save(self):
        if self.save_job is not None:
            self.root.after_cancel(self.save_job)
            self.save_job = None

    def capture_form(self):
        if not self.in_main or self.trial is None:
            return

        self.trial["remarks"] = self.remarks_var.get()
        self.trial.setdefault("custom", {}).update({
            name: variable.get()
            for name, variable in self.custom_vars.items()
        })

        if 0 <= self.frame_index < len(self.frames):
            self.trial["last_frame"] = self.frames[self.frame_index]

    def save_project(self):
        self.cancel_pending_save()

        if self.project is None or self.project_path is None:
            return True

        self.capture_form()

        try:
            atomic_write(
                self.project_path,
                lambda handle: json.dump(
                    self.project,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                ),
            )
            return True

        except Exception as exc:
            messagebox.showerror(
                "Save failed",
                f"Project data could not be saved:\n{exc}",
                parent=self.root,
            )
            return False

    def save_soon(self):
        if self.project is None:
            return

        self.cancel_pending_save()
        self.save_job = self.root.after(700, self.save_project)

    def form_changed(self, *_):
        if self.loading_form or self.trial is None:
            return

        self.trial["status"] = "draft"
        self.update_trial_status()
        self.save_soon()

    def annotation_changed(self):
        if self.trial is not None:
            self.trial["status"] = "draft"

        self.update_measurement_panel()
        self.update_trial_status()
        self.draw()
        self.save_project()

    def clear_window(self):
        self.stop_playback()
        self.in_main = False

        for widget in self.root.winfo_children():
            widget.destroy()

    def show_menu(self):
        self.clear_window()
        self.root.geometry("640x430")
        self.root.minsize(540, 380)

        body = ttk.Frame(self.root, padding=30)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="WorkSmart | Point Marker",
            font=("Arial", 20, "bold"),
        ).pack(pady=(15, 25))

        create_box = ttk.LabelFrame(
            body,
            text="Create project",
            padding=12,
        )
        create_box.pack(fill="x", pady=8)

        self.new_project_var = tk.StringVar()

        ttk.Entry(
            create_box,
            textvariable=self.new_project_var,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 10),
        )

        ttk.Button(
            create_box,
            text="Create",
            command=self.create_project,
        ).pack(side="right")

        load_box = ttk.LabelFrame(
            body,
            text="Load project",
            padding=12,
        )
        load_box.pack(fill="x", pady=8)

        projects = sorted(
            [path.stem for path in self.projects_dir.glob("*.json")],
            key=natural_key,
        )

        self.project_combo = ttk.Combobox(
            load_box,
            values=projects,
            state="readonly",
        )
        self.project_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 10),
        )

        if projects:
            self.project_combo.current(0)

        ttk.Button(
            load_box,
            text="Launch",
            command=self.load_project,
        ).pack(side="right")

        ttk.Label(
            body,
            text=(
                "Projects and draft annotations are saved in:\n"
                f"{self.projects_dir}"
            ),
            wraplength=540,
        ).pack(pady=20)

    def create_project(self):
        name = self.new_project_var.get().strip()

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", name):
            messagebox.showerror(
                "Project name",
                "Use letters, numbers, spaces, underscores, or hyphens.\n"
                "Start with a letter or number; maximum 80 characters.",
            )
            return

        path = self.projects_dir / f"{name}.json"

        if path.exists():
            messagebox.showerror(
                "Project exists",
                "Choose another name.",
            )
            return

        self.project_path = path
        self.project = {
            "application": "WorkSmartPointMarker",
            "version": 1,
            "name": name,
            "parent_folder": "",
            "csv_path": "",
            "fps": 30.0,
            "show_references": True,
            "custom_fields": [],
            "current_trial": None,
            "trials": {},
        }
        self.trial_key = None

        if self.save_project():
            self.setup_main_ui()
            self.refresh_trials()

    def load_project(self):
        name = self.project_combo.get()

        if not name:
            return

        path = self.projects_dir / f"{name}.json"

        try:
            with path.open(encoding="utf-8") as handle:
                project = json.load(handle)

            if (
                project.get("application") != "WorkSmartPointMarker"
                or project.get("version") != 1
            ):
                raise ValueError("Not a supported point-marker project.")

            self.project = project
            self.project_path = path
            self.trial_key = None

            self.setup_main_ui()
            self.refresh_trials()

        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))

    def return_to_menu(self):
        self.stop_playback()

        if self.save_project():
            self.show_menu()

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def setup_main_ui(self):
        self.clear_window()
        self.root.geometry("1250x850")
        self.root.minsize(950, 650)

        self.trial_key = None
        self.frames = []
        self.frame_index = -1
        self.image = None
        self.transform = None
        self.armed_endpoint = None

        header = ttk.Frame(self.root, padding=8)
        header.pack(fill="x")

        ttk.Label(
            header,
            text=f"PROJECT: {self.project['name']}",
            font=("Arial", 11, "bold"),
        ).pack(side="left")

        ttk.Button(
            header,
            text="Config",
            command=self.settings,
        ).pack(side="left", padx=12)

        ttk.Button(
            header,
            text="Menu",
            command=self.return_to_menu,
        ).pack(side="right")

        ttk.Button(
            header,
            text="Save Project",
            command=self.save_project,
        ).pack(side="right", padx=8)

        self.paths_var = tk.StringVar()

        ttk.Label(
            self.root,
            textvariable=self.paths_var,
            padding=(8, 2),
            wraplength=1100,
        ).pack(fill="x")

        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)

        left = ttk.Frame(container)
        left.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(
            left,
            background="black",
            highlightthickness=0,
        )
        self.canvas.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<Button-1>", self.canvas_click)

        nav = ttk.Frame(left, padding=8)
        nav.pack(fill="x")

        self.play_button = ttk.Button(
            nav,
            text="Play",
            command=self.toggle_playback,
            width=7,
        )
        self.play_button.pack(side="left")

        ttk.Button(
            nav,
            text="<",
            width=3,
            command=lambda: self.step(-1),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            nav,
            text=">",
            width=3,
            command=lambda: self.step(1),
        ).pack(side="left")

        self.slider = tk.Scale(
            nav,
            from_=1,
            to=1,
            orient="horizontal",
            showvalue=False,
            resolution=1,
            command=self.slider_changed,
        )
        self.slider.pack(
            side="left",
            fill="x",
            expand=True,
            padx=8,
        )

        self.goto_var = tk.StringVar(value="1")

        ttk.Entry(
            nav,
            textvariable=self.goto_var,
            width=7,
        ).pack(side="left")

        ttk.Button(
            nav,
            text="Go",
            command=self.go_to_number,
        ).pack(side="left", padx=4)

        self.frame_var = tk.StringVar(value="No frame loaded")

        ttk.Label(
            left,
            textvariable=self.frame_var,
            padding=(8, 0),
        ).pack(fill="x")

        self.message_var = tk.StringVar(
            value="Select a parent folder to begin."
        )

        ttk.Label(
            left,
            textvariable=self.message_var,
            padding=8,
            wraplength=650,
        ).pack(fill="x")

        # Scrollable sidebar.
        side_outer = ttk.Frame(container, width=350)
        side_outer.pack(side="right", fill="y")
        side_outer.pack_propagate(False)

        side_canvas = tk.Canvas(
            side_outer,
            highlightthickness=0,
        )
        side_scroll = ttk.Scrollbar(
            side_outer,
            orient="vertical",
            command=side_canvas.yview,
        )
        side_canvas.configure(yscrollcommand=side_scroll.set)

        side_scroll.pack(side="right", fill="y")
        side_canvas.pack(side="left", fill="both", expand=True)

        side = ttk.Frame(side_canvas, padding=10)
        side_window = side_canvas.create_window(
            (0, 0),
            window=side,
            anchor="nw",
        )

        side.bind(
            "<Configure>",
            lambda event: side_canvas.configure(
                scrollregion=side_canvas.bbox("all")
            ),
        )
        side_canvas.bind(
            "<Configure>",
            lambda event: side_canvas.itemconfigure(
                side_window,
                width=event.width,
            ),
        )

        ttk.Button(
            side,
            text="Select Parent Folder",
            command=self.select_parent,
        ).pack(fill="x", pady=3)

        ttk.Button(
            side,
            text="Select Output CSV",
            command=self.select_csv,
        ).pack(fill="x", pady=3)

        ttk.Label(
            side,
            text="Trial:",
        ).pack(anchor="w", pady=(12, 2))

        self.trial_combo = ttk.Combobox(side, state="readonly")
        self.trial_combo.pack(fill="x")
        self.trial_combo.bind(
            "<<ComboboxSelected>>",
            self.trial_selected,
        )

        self.trial_status_var = tk.StringVar()

        ttk.Label(
            side,
            textvariable=self.trial_status_var,
        ).pack(anchor="w", pady=5)

        measure_box = ttk.LabelFrame(
            side,
            text="Measurements",
            padding=8,
        )
        measure_box.pack(fill="x", pady=8)

        self.measurement_combo = ttk.Combobox(
            measure_box,
            state="readonly",
        )
        self.measurement_combo.pack(fill="x")
        self.measurement_combo.bind(
            "<<ComboboxSelected>>",
            self.measurement_selected,
        )

        buttons = ttk.Frame(measure_box)
        buttons.pack(fill="x", pady=6)

        for text, callback in [
            ("Add", self.add_measurement),
            ("Rename", self.rename_measurement),
            ("Delete", self.delete_measurement),
        ]:
            ttk.Button(
                buttons,
                text=text,
                command=callback,
            ).pack(side="left", fill="x", expand=True)

        self.point_vars = {}

        for endpoint in ("start", "end"):
            box = ttk.LabelFrame(
                measure_box,
                text=endpoint.title(),
                padding=6,
            )
            box.pack(fill="x", pady=4)

            variable = tk.StringVar(value="Not marked")
            self.point_vars[endpoint] = variable

            ttk.Label(
                box,
                textvariable=variable,
                wraplength=270,
            ).pack(anchor="w")

            row = ttk.Frame(box)
            row.pack(fill="x", pady=(5, 0))

            ttk.Button(
                row,
                text="Set",
                command=lambda e=endpoint: self.arm(e),
            ).pack(side="left", fill="x", expand=True)

            ttk.Button(
                row,
                text="Go to",
                command=lambda e=endpoint: self.go_to_endpoint(e),
            ).pack(side="left", fill="x", expand=True)

            ttk.Button(
                row,
                text="Clear",
                command=lambda e=endpoint: self.clear_endpoint(e),
            ).pack(side="left", fill="x", expand=True)

        self.reference_var = tk.BooleanVar(
            value=self.project["show_references"]
        )

        ttk.Checkbutton(
            measure_box,
            text="Show reference points from other frames",
            variable=self.reference_var,
            command=self.reference_changed,
        ).pack(anchor="w", pady=8)

        self.result_var = tk.StringVar(value="Displacement: —")

        ttk.Label(
            measure_box,
            textvariable=self.result_var,
            font=("Arial", 11, "bold"),
            wraplength=285,
        ).pack(anchor="w", pady=5)

        self.calibration_var = tk.StringVar()

        ttk.Label(
            measure_box,
            textvariable=self.calibration_var,
            wraplength=285,
        ).pack(anchor="w")

        self.custom_box = ttk.LabelFrame(
            side,
            text="Custom Variables",
            padding=8,
        )
        self.custom_box.pack(fill="x", pady=8)

        self.custom_vars = {}
        self.rebuild_custom_fields()

        ttk.Label(
            side,
            text="Observations:",
        ).pack(anchor="w")

        self.remarks_var = tk.StringVar()
        self.remarks_var.trace_add("write", self.form_changed)

        ttk.Entry(
            side,
            textvariable=self.remarks_var,
        ).pack(fill="x", pady=5)

        ttk.Button(
            side,
            text="SKIP — keep draft",
            command=self.skip_trial,
        ).pack(fill="x", pady=(12, 5))

        ttk.Button(
            side,
            text="SUBMIT & NEXT",
            command=self.submit,
        ).pack(fill="x", pady=5)

        ttk.Label(
            side,
            text=(
                "S: set start    E: set end\n"
                "Left/Right: step frame\n"
                "Space: play/pause\n"
                "Escape: cancel marking\n"
                "Enter: submit\n\n"
                "Solid +: current frame\n"
                "Dashed +: another frame\n"
                "Dashed connecting line: endpoint displacement"
            ),
            wraplength=290,
        ).pack(anchor="w", pady=15)

        self.in_main = True
        self.update_paths()

    def update_paths(self):
        self.paths_var.set(
            f"Source: {self.project['parent_folder'] or '(not selected)'}\n"
            f"CSV: {self.project['csv_path'] or '(not selected)'}"
        )

    def rebuild_custom_fields(self):
        for widget in self.custom_box.winfo_children():
            widget.destroy()

        values = self.trial.get("custom", {}) if self.trial else {}
        self.custom_vars = {}

        for name in self.project["custom_fields"]:
            ttk.Label(
                self.custom_box,
                text=name,
            ).pack(anchor="w")

            variable = tk.StringVar(value=values.get(name, ""))
            variable.trace_add("write", self.form_changed)

            ttk.Entry(
                self.custom_box,
                textvariable=variable,
            ).pack(fill="x", pady=(0, 5))

            self.custom_vars[name] = variable

    # ------------------------------------------------------------------
    # Dataset and frame navigation
    # ------------------------------------------------------------------

    def select_parent(self):
        folder = filedialog.askdirectory(parent=self.root)

        if not folder:
            return

        self.stop_playback()

        if not self.save_project():
            return

        self.project["parent_folder"] = str(Path(folder).resolve())
        self.project["current_trial"] = None

        self.update_paths()
        self.refresh_trials()
        self.save_project()

    def select_csv(self):
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )

        if filename:
            self.project["csv_path"] = str(Path(filename).resolve())
            self.update_paths()
            self.save_project()

    def image_names(self, folder):
        return sorted(
            [
                path.name
                for path in Path(folder).iterdir()
                if path.is_file()
                and path.suffix.lower() in IMAGE_EXTENSIONS
                and not path.name.startswith((".", "~"))
            ],
            key=natural_key,
        )

    def refresh_trials(self):
        self.stop_playback()
        self.trial_key = None
        self.frames = []
        self.frame_index = -1
        self.image = None
        self.trial_paths = []

        folder = self.project["parent_folder"]

        if folder and Path(folder).is_dir():
            try:
                candidates = sorted(
                    [
                        path
                        for path in Path(folder).iterdir()
                        if path.is_dir()
                    ],
                    key=lambda path: natural_key(path.name),
                )

                self.trial_paths = [
                    str(path.resolve())
                    for path in candidates
                    if self.image_names(path)
                ]

            except OSError as exc:
                messagebox.showerror("Folder error", str(exc))

        self.trial_combo["values"] = [
            Path(path).name for path in self.trial_paths
        ]

        if self.trial_paths:
            current = self.project.get("current_trial")
            index = (
                self.trial_paths.index(current)
                if current in self.trial_paths
                else 0
            )
            self.load_trial(index)

        else:
            self.trial_combo.set("")

            self.loading_form = True
            self.remarks_var.set("")
            self.rebuild_custom_fields()
            self.loading_form = False

            self.refresh_measurements()
            self.frame_var.set("No frame loaded")
            self.trial_status_var.set("No trials loaded")
            self.message_var.set(
                "Choose a parent folder containing trial subfolders "
                "with image files."
            )
            self.draw()

    def trial_selected(self, _event=None):
        index = self.trial_combo.current()

        if index >= 0:
            self.load_trial(index)

    def load_trial(self, index):
        self.stop_playback()

        if self.trial is not None and not self.save_project():
            self.trial_combo.current(
                self.trial_paths.index(self.trial_key)
            )
            return

        key = self.trial_paths[index]
        self.trial_key = key
        self.project["current_trial"] = key

        self.project["trials"].setdefault(key, {
            "measurements": [new_measurement()],
            "custom": {},
            "remarks": "",
            "last_frame": None,
            "spacing_x": None,
            "spacing_y": None,
            "status": "draft",
        })

        self.frames = self.image_names(key)
        self.frame_index = -1
        self.image = None
        self.armed_endpoint = None
        self.measurement_index = 0
        self.trial_combo.current(index)

        self.loading_form = True
        self.remarks_var.set(self.trial.get("remarks", ""))
        self.rebuild_custom_fields()
        self.loading_form = False

        self.slider.configure(to=max(1, len(self.frames)))
        self.refresh_measurements()
        self.update_trial_status()

        previous = self.trial.get("last_frame")
        frame_index = (
            self.frames.index(previous)
            if previous in self.frames
            else 0
        )

        if self.frames:
            self.show_frame(frame_index)

        self.message_var.set("Choose Set Start or Set End, then click.")
        self.save_project()

    def update_trial_status(self):
        if self.trial is None:
            return

        index = self.trial_paths.index(self.trial_key)
        self.trial_status_var.set(
            f"Trial {index + 1}/{len(self.trial_paths)}"
            f"   |   {self.trial.get('status', 'draft')}"
        )

    def show_frame(self, index):
        if not self.frames:
            return

        index = max(0, min(len(self.frames) - 1, index))

        if index == self.frame_index:
            return

        self.frame_index = index
        self.image = None

        try:
            with Image.open(
                Path(self.trial_key) / self.frames[index]
            ) as source:
                self.image = source.convert("RGB")

        except Exception as exc:
            self.stop_playback()
            self.message_var.set(
                f"Cannot open {self.frames[index]}: {exc}"
            )

        self.slider.set(index + 1)
        self.goto_var.set(str(index + 1))
        self.frame_var.set(
            f"Frame {index + 1}/{len(self.frames)}"
            f"   |   {self.frames[index]}"
        )
        self.trial["last_frame"] = self.frames[index]

        self.draw()
        self.save_soon()

    def slider_changed(self, value):
        if not self.in_main or not self.frames:
            return

        index = int(float(value)) - 1

        if index != self.frame_index:
            self.stop_playback()
            self.show_frame(index)

    def step(self, amount):
        self.stop_playback()
        self.show_frame(self.frame_index + amount)

    def go_to_number(self):
        if not self.frames:
            return

        try:
            number = int(self.goto_var.get())

            if not 1 <= number <= len(self.frames):
                raise ValueError

        except ValueError:
            messagebox.showerror(
                "Frame number",
                f"Enter a number from 1 to {len(self.frames)}.",
            )
            return

        self.stop_playback()
        self.show_frame(number - 1)
        self.canvas.focus_set()

    def stop_playback(self):
        if self.play_job is not None:
            self.root.after_cancel(self.play_job)
            self.play_job = None

        if self.in_main and hasattr(self, "play_button"):
            self.play_button.configure(text="Play")

    def toggle_playback(self):
        if not self.frames:
            return

        if self.play_job is not None:
            self.stop_playback()
            return

        self.armed_endpoint = None
        self.canvas.configure(cursor="")

        if self.frame_index >= len(self.frames) - 1:
            self.show_frame(0)

        self.play_button.configure(text="Pause")
        self.play_job = self.root.after(
            max(1, round(1000 / self.project["fps"])),
            self.play_tick,
        )

    def play_tick(self):
        self.play_job = None

        if self.frame_index >= len(self.frames) - 1:
            self.stop_playback()
            return

        self.show_frame(self.frame_index + 1)

        if self.image is None:
            self.stop_playback()
            return

        self.play_job = self.root.after(
            max(1, round(1000 / self.project["fps"])),
            self.play_tick,
        )

    # ------------------------------------------------------------------
    # Measurement management
    # ------------------------------------------------------------------

    def refresh_measurements(self):
        measurements = self.trial["measurements"] if self.trial else []

        self.measurement_combo["values"] = [
            measurement["name"]
            for measurement in measurements
        ]

        if measurements:
            self.measurement_index = min(
                self.measurement_index,
                len(measurements) - 1,
            )
            self.measurement_combo.current(self.measurement_index)

        else:
            self.measurement_combo.set("")

        self.update_measurement_panel()
        self.draw()

    def measurement_selected(self, _event=None):
        self.measurement_index = self.measurement_combo.current()
        self.armed_endpoint = None
        self.canvas.configure(cursor="")

        self.update_measurement_panel()
        self.draw()

    def request_measurement_name(self, initial=""):
        name = simpledialog.askstring(
            "Measurement",
            "Measurement name:",
            initialvalue=initial,
            parent=self.root,
        )

        if name is None:
            return None

        name = name.strip()

        if not name:
            return None

        others = {
            measurement["name"]
            for measurement in self.trial["measurements"]
            if measurement is not self.measurement or not initial
        }

        if name in others:
            messagebox.showerror(
                "Duplicate name",
                "Use a unique measurement name.",
            )
            return None

        return name

    def add_measurement(self):
        if self.trial is None:
            return

        name = self.request_measurement_name()

        if name:
            self.trial["measurements"].append(new_measurement(name))
            self.measurement_index = len(self.trial["measurements"]) - 1
            self.armed_endpoint = None

            self.refresh_measurements()
            self.annotation_changed()

    def rename_measurement(self):
        if self.measurement is None:
            return

        name = self.request_measurement_name(self.measurement["name"])

        if name:
            self.measurement["name"] = name
            self.refresh_measurements()
            self.annotation_changed()

    def delete_measurement(self):
        if self.measurement is None:
            return

        if messagebox.askyesno(
            "Delete measurement",
            f"Delete '{self.measurement['name']}' and both points?",
        ):
            self.trial["measurements"].pop(self.measurement_index)
            self.measurement_index = 0
            self.armed_endpoint = None

            self.refresh_measurements()
            self.annotation_changed()

    def arm(self, endpoint):
        if self.measurement is None or self.image is None:
            return

        self.stop_playback()
        self.armed_endpoint = endpoint
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()

        self.message_var.set(
            f"Click to set {endpoint.upper()} for "
            f"'{self.measurement['name']}'. Escape cancels."
        )

    def canvas_click(self, event):
        self.canvas.focus_set()

        if (
            self.armed_endpoint is None
            or self.measurement is None
            or self.image is None
            or self.transform is None
        ):
            return

        ox, oy, sx, sy = self.transform
        x = (event.x - ox) / sx
        y = (event.y - oy) / sy
        width, height = self.image.size

        # Ignore letterbox / black-border clicks.
        if not (0 <= x < width and 0 <= y < height):
            return

        endpoint = self.armed_endpoint

        self.measurement[endpoint] = {
            "filename": self.frames[self.frame_index],
            "frame_index": self.frame_index + 1,
            "x": float(x),
            "y": float(y),
            "width": width,
            "height": height,
        }

        # One click per explicit Set action prevents accidental replacement.
        self.armed_endpoint = None
        self.canvas.configure(cursor="")

        self.message_var.set(
            f"{endpoint.title()} saved on frame {self.frame_index + 1}. "
            "Navigate to another frame or choose another point."
        )

        self.annotation_changed()

    def clear_endpoint(self, endpoint):
        if self.measurement is None:
            return

        if self.measurement[endpoint] is None:
            return

        if messagebox.askyesno(
            "Clear point",
            f"Clear the {endpoint} point?",
        ):
            self.measurement[endpoint] = None
            self.armed_endpoint = None
            self.canvas.configure(cursor="")

            self.annotation_changed()

    def go_to_endpoint(self, endpoint):
        if self.measurement is None:
            return

        point = self.measurement[endpoint]

        if point is None:
            return

        filename = point["filename"]

        if filename not in self.frames:
            messagebox.showerror(
                "Missing frame",
                f"Frame is missing:\n{filename}",
            )
            return

        self.stop_playback()
        self.show_frame(self.frames.index(filename))

    def reference_changed(self):
        self.project["show_references"] = self.reference_var.get()
        self.draw()
        self.save_project()

    def distance(self, measurement):
        start = measurement["start"]
        end = measurement["end"]

        if start is None or end is None:
            return None

        if (
            start["width"], start["height"]
        ) != (
            end["width"], end["height"]
        ):
            return None

        dx = end["x"] - start["x"]
        dy = end["y"] - start["y"]
        pixels = math.hypot(dx, dy)

        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        millimeters = (
            math.hypot(dx * sx, dy * sy)
            if sx is not None and sy is not None
            else None
        )

        return dx, dy, pixels, millimeters

    def update_measurement_panel(self):
        measurement = self.measurement

        for endpoint, variable in self.point_vars.items():
            point = measurement[endpoint] if measurement else None

            if point is None:
                variable.set("Not marked")

            else:
                filename = point["filename"]
                index = (
                    self.frames.index(filename) + 1
                    if filename in self.frames
                    else "missing"
                )

                variable.set(
                    f"Frame {index} | {filename}\n"
                    f"x={point['x']:.2f}, y={point['y']:.2f} px"
                )

        result = self.distance(measurement) if measurement else None

        if result is not None:
            dx, dy, pixels, millimeters = result
            text = (
                f"Displacement: {pixels:.3f} px\n"
                f"Δx: {dx:.3f}   Δy: {dy:.3f} px"
            )

            if millimeters is not None:
                text += f"\nDisplacement: {millimeters:.3f} mm"

            self.result_var.set(text)

        elif (
            measurement
            and measurement["start"]
            and measurement["end"]
        ):
            self.result_var.set(
                "Cannot measure: image dimensions differ."
            )

        else:
            self.result_var.set("Displacement: mark both endpoints")

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None

        self.calibration_var.set(
            f"Calibration: X={sx:g}, Y={sy:g} mm/px"
            if sx is not None and sy is not None
            else "Pixels only. Add this trial's calibration in Config."
        )

    # ------------------------------------------------------------------
    # Canvas rendering
    # ------------------------------------------------------------------

    def draw(self):
        if not self.in_main:
            return

        self.canvas.delete("all")
        self.transform = None
        self.canvas.configure(
            cursor="crosshair" if self.armed_endpoint else ""
        )

        if self.image is None:
            self.canvas.create_text(
                max(1, self.canvas.winfo_width()) / 2,
                max(1, self.canvas.winfo_height()) / 2,
                text="No image loaded",
                fill="white",
            )
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        width, height = self.image.size

        scale = min(
            canvas_width / width,
            canvas_height / height,
        )
        display_width = max(1, round(width * scale))
        display_height = max(1, round(height * scale))

        ox = (canvas_width - display_width) / 2
        oy = (canvas_height - display_height) / 2

        # Use actual rendered dimensions, including rounding.
        sx = display_width / width
        sy = display_height / height
        self.transform = (ox, oy, sx, sy)

        resized = self.image.resize(
            (display_width, display_height),
            Image.Resampling.LANCZOS,
        )
        self.photo = ImageTk.PhotoImage(resized)

        self.canvas.create_image(
            ox,
            oy,
            image=self.photo,
            anchor="nw",
        )

        current_filename = self.frames[self.frame_index]
        show_references = self.reference_var.get()

        def visible(point):
            if point is None:
                return False

            if (point["width"], point["height"]) != (width, height):
                return False

            if point["filename"] not in self.frames:
                return False

            return (
                point["filename"] == current_filename
                or show_references
            )

        def position(point):
            return (
                ox + point["x"] * sx,
                oy + point["y"] * sy,
            )

        selected = self.measurement

        # Draw the displacement line behind the markers.
        if (
            selected
            and visible(selected["start"])
            and visible(selected["end"])
        ):
            x1, y1 = position(selected["start"])
            x2, y2 = position(selected["end"])

            self.canvas.create_line(
                x1,
                y1,
                x2,
                y2,
                fill="#ffff66",
                width=2,
                dash=(5, 4),
            )

        for measurement in self.trial["measurements"]:
            for endpoint, color in [
                ("start", "#30e0ff"),
                ("end", "#ff8c42"),
            ]:
                point = measurement[endpoint]

                if not visible(point):
                    continue

                x, y = position(point)
                is_current = point["filename"] == current_filename
                is_selected = measurement is selected

                # Draw a + centered exactly on the saved coordinate.
                # Marker size stays constant in screen pixels.
                arm_length = 8 if is_selected else 6
                line_width = 2 if is_selected else 1

                marker_style = {
                    "fill": color,
                    "width": line_width,
                    "capstyle": tk.BUTT,
                }

                # Current-frame markers are solid.
                # Reference markers from other frames are dashed.
                if not is_current:
                    marker_style["dash"] = (3, 2)

                # Horizontal stroke of the +.
                self.canvas.create_line(
                    x - arm_length,
                    y,
                    x + arm_length,
                    y,
                    **marker_style,
                )

                # Vertical stroke of the +.
                self.canvas.create_line(
                    x,
                    y - arm_length,
                    x,
                    y + arm_length,
                    **marker_style,
                )

                frame_number = (
                    self.frames.index(point["filename"]) + 1
                )
                label = (
                    f"{measurement['name']} "
                    f"{endpoint[0].upper()} | F{frame_number}"
                )

                if not is_current:
                    label += " [ref]"

                # Offset start and end labels in opposite directions.
                label_y = y - 11 if endpoint == "start" else y + 11

                self.canvas.create_text(
                    x + 10,
                    label_y,
                    text=label,
                    fill=color,
                    anchor="w",
                    font=(
                        "Arial",
                        10,
                        "bold" if is_selected else "normal",
                    ),
                )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def settings(self):
        self.stop_playback()
        self.capture_form()

        dialog = tk.Toplevel(self.root)
        dialog.title("Configuration")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=18)
        body.pack(fill="both", expand=True)

        fps_var = tk.StringVar(
            value=str(self.project["fps"])
        )
        fields_var = tk.StringVar(
            value=", ".join(self.project["custom_fields"])
        )

        def entry_row(label, variable):
            ttk.Label(
                body,
                text=label,
            ).pack(anchor="w", pady=(8, 2))

            ttk.Entry(
                body,
                textvariable=variable,
                width=48,
            ).pack(fill="x")

        entry_row("Playback FPS:", fps_var)
        entry_row(
            "Custom variable names, comma-separated:",
            fields_var,
        )

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None

        sx_var = tk.StringVar(
            value="" if sx is None else str(sx)
        )
        sy_var = tk.StringVar(
            value="" if sy is None else str(sy)
        )

        if self.trial is not None:
            entry_row(
                "Current trial: horizontal spacing (mm/pixel):",
                sx_var,
            )
            entry_row(
                "Current trial: vertical spacing (mm/pixel):",
                sy_var,
            )

            ttk.Label(
                body,
                text=(
                    "Leave BOTH spacing fields empty for pixels only.\n"
                    "Calibration applies to all pairs in this trial."
                ),
            ).pack(anchor="w", pady=8)

        def apply():
            try:
                fps = float(fps_var.get())

                if not math.isfinite(fps) or not 0 < fps <= 1000:
                    raise ValueError(
                        "FPS must be greater than 0 and ≤ 1000."
                    )

                fields = [
                    name.strip()
                    for name in fields_var.get().split(",")
                    if name.strip()
                ]

                if len(fields) != len(set(fields)):
                    raise ValueError(
                        "Custom variable names must be unique."
                    )

                if set(fields) & set(BASE_COLUMNS + ["Remarks"]):
                    raise ValueError(
                        "A custom variable conflicts with a CSV column name."
                    )

                spacing_x = spacing_y = None

                if self.trial is not None:
                    x_text = sx_var.get().strip()
                    y_text = sy_var.get().strip()

                    if bool(x_text) != bool(y_text):
                        raise ValueError(
                            "Provide both calibration values, "
                            "or leave both blank."
                        )

                    if x_text:
                        spacing_x = float(x_text)
                        spacing_y = float(y_text)

                        if not all(
                            math.isfinite(value) and value > 0
                            for value in (spacing_x, spacing_y)
                        ):
                            raise ValueError(
                                "Calibration values must be "
                                "positive finite numbers."
                            )

            except ValueError as exc:
                messagebox.showerror(
                    "Invalid configuration",
                    str(exc),
                    parent=dialog,
                )
                return

            self.project["fps"] = fps
            self.project["custom_fields"] = fields

            if self.trial is not None:
                self.trial["spacing_x"] = spacing_x
                self.trial["spacing_y"] = spacing_y
                self.trial["status"] = "draft"

            self.rebuild_custom_fields()
            self.update_measurement_panel()
            self.update_trial_status()
            self.save_project()
            dialog.destroy()

        ttk.Button(
            body,
            text="Apply",
            command=apply,
        ).pack(fill="x", pady=(15, 0))

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def validate_measurement(self, measurement):
        if not measurement["start"] or not measurement["end"]:
            raise ValueError(
                f"'{measurement['name']}' needs both endpoints.\n"
                "Finish it or delete it before submitting."
            )

        for endpoint in ("start", "end"):
            point = measurement[endpoint]
            filename = point["filename"]

            if filename not in self.frames:
                raise ValueError(
                    f"Missing source frame: {filename}"
                )

            with Image.open(
                Path(self.trial_key) / filename
            ) as source:
                if source.size != (point["width"], point["height"]):
                    raise ValueError(
                        f"Source image dimensions changed: {filename}\n"
                        "Please re-mark this endpoint."
                    )

        if self.distance(measurement) is None:
            raise ValueError(
                f"'{measurement['name']}': start/end dimensions differ.\n"
                "Use frames with the same coordinate system."
            )

    def export_rows(self):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        rows = []

        for measurement in self.trial["measurements"]:
            self.validate_measurement(measurement)

            start = measurement["start"]
            end = measurement["end"]
            dx, dy, pixels, millimeters = self.distance(measurement)

            row = {
                "Project": self.project["name"],
                "SourceFolder": self.trial_key,
                "Trial": Path(self.trial_key).name,
                "MeasurementID": measurement["id"],
                "Measurement": measurement["name"],
                "RecordTime": now,
                "StartFrameIndex": (
                    self.frames.index(start["filename"]) + 1
                ),
                "StartFilename": start["filename"],
                "StartX_px": start["x"],
                "StartY_px": start["y"],
                "EndFrameIndex": (
                    self.frames.index(end["filename"]) + 1
                ),
                "EndFilename": end["filename"],
                "EndX_px": end["x"],
                "EndY_px": end["y"],
                "DeltaX_px": dx,
                "DeltaY_px": dy,
                "Distance_px": pixels,
                "SpacingX_mm_per_px": self.trial.get("spacing_x"),
                "SpacingY_mm_per_px": self.trial.get("spacing_y"),
                "Distance_mm": millimeters,
                "Remarks": self.trial.get("remarks", ""),
            }

            for field in self.project["custom_fields"]:
                row[field] = self.trial.get("custom", {}).get(
                    field,
                    "",
                )

            rows.append(row)

        return rows

    def submit(self):
        self.stop_playback()

        if self.trial is None:
            return

        if not self.trial["measurements"]:
            messagebox.showerror(
                "No measurements",
                "Add at least one measurement.",
            )
            return

        if not self.project["csv_path"]:
            self.select_csv()

            if not self.project["csv_path"]:
                return

        if not self.save_project():
            return

        path = Path(self.project["csv_path"])
        columns = (
            BASE_COLUMNS
            + self.project["custom_fields"]
            + ["Remarks"]
        )

        try:
            new_rows = self.export_rows()
            previous_rows = []

            if path.exists() and path.stat().st_size:
                with path.open(
                    "r",
                    encoding="utf-8-sig",
                    newline="",
                ) as handle:
                    reader = csv.DictReader(handle)

                    if reader.fieldnames != columns:
                        raise ValueError(
                            "Existing CSV columns do not match this project.\n"
                            "Select a new output CSV, especially after changing "
                            "custom variable names."
                        )

                    previous_rows = list(reader)

            # Replace all previously submitted rows for this project/trial.
            previous_rows = [
                row
                for row in previous_rows
                if not (
                    row["Project"] == self.project["name"]
                    and row["SourceFolder"] == self.trial_key
                )
            ]

            def write_csv(handle):
                writer = csv.DictWriter(
                    handle,
                    fieldnames=columns,
                )
                writer.writeheader()
                writer.writerows(previous_rows)
                writer.writerows(new_rows)

            atomic_write(path, write_csv)

        except Exception as exc:
            messagebox.showerror("Submit failed", str(exc))
            return

        self.trial["status"] = "submitted"
        self.update_trial_status()

        if self.save_project():
            self.advance_trial()

    def skip_trial(self):
        if self.trial is None:
            return

        self.stop_playback()

        if messagebox.askyesno(
            "Skip trial",
            "Go to the next trial without exporting?\n"
            "Your draft annotations will remain saved.",
        ):
            if self.save_project():
                self.advance_trial()

    def advance_trial(self):
        index = self.trial_paths.index(self.trial_key)

        if index + 1 < len(self.trial_paths):
            self.load_trial(index + 1)

        else:
            messagebox.showinfo(
                "End of trials",
                "You have reached the final trial.\n"
                "Use the trial selector to revisit any trial.",
            )

    # ------------------------------------------------------------------
    # Keyboard and close
    # ------------------------------------------------------------------

    def handle_key(self, event):
        if not self.in_main:
            return

        # Do not run main-window shortcuts while a modal dialog is open.
        if self.root.grab_current() is not None:
            return

        focus = self.root.focus_get()

        if isinstance(
            focus,
            (
                tk.Entry,
                ttk.Entry,
                tk.Text,
                ttk.Combobox,
                tk.Spinbox,
                ttk.Spinbox,
            ),
        ):
            return

        # Preserve standard Ctrl/Alt shortcuts.
        if event.state & 0x0004 or event.state & 0x0008:
            return

        key = event.keysym.lower()

        actions = {
            "left": lambda: self.step(-1),
            "right": lambda: self.step(1),
            "space": self.toggle_playback,
            "s": lambda: self.arm("start"),
            "e": lambda: self.arm("end"),
            "return": self.submit,
        }

        if key == "escape":
            self.armed_endpoint = None
            self.canvas.configure(cursor="")
            self.message_var.set("Marking canceled.")
            return "break"

        if key in actions:
            actions[key]()
            return "break"

    def close(self):
        self.stop_playback()

        if self.save_project():
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = UltrasoundPointMarker(root)
    root.mainloop()