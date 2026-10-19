import csv
import json
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk


APP_ID = "WorkSmartCombinedAnnotator"
APP_VERSION = 2

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"
}

ROW_KEYS = [
    list("1234567890"),
    list("qwertyuiop"),
    list("asdfghjkl"),
    list("zxcvbnm"),
]

RESERVED_COLUMNS = {
    "Trial",
    "RecordTime",
    "Remarks",
    "Project",
    "SourceFolder",
    "SpacingX_mm_per_px",
    "SpacingY_mm_per_px",
}

COLUMN_PREFIXES = ("Timestamp::", "Point::", "Comparison::")

MANUAL_FRAME_LABEL = "Manual — current frame"


# ----------------------------------------------------------------------
# General helpers
# ----------------------------------------------------------------------

def natural_key(value):
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(value))
    ]


def atomic_write(path, writer):
    """Write to a temporary sibling file, then replace the destination."""
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
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def backup_once(path, suffix):
    path = Path(path)
    backup = Path(str(path) + suffix)

    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)


def new_structure(name):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "start": None,
        "end": None,
    }


def new_comparison(name, structure_a_id, structure_b_id):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "a_id": structure_a_id,
        "b_id": structure_b_id,
    }


def new_trial():
    a = new_structure("Structure A")
    b = new_structure("Structure B")

    return {
        "measurements": [a, b],
        "comparisons": [
            new_comparison("A-B", a["id"], b["id"])
        ],
        "marks": {},
        "frame_links": {"start": "", "end": ""},
        "custom": {},
        "remarks": "",
        "last_frame": None,
        "spacing_x": None,
        "spacing_y": None,
        "status": "draft",
    }


def new_project(name):
    return {
        "application": APP_ID,
        "version": APP_VERSION,
        "name": name,
        "parent_folder": "",
        "csv_path": "",
        "last_trial_idx": 0,
        "current_trial": None,
        "fps": 30.0,
        "mark_rows": [["On", "Max", "Off"], [], [], []],
        "custom_fields": [],
        "show_references": True,

        # Keep Timestamper's original filename ordering by default.
        # Natural sorting is available in Config.
        "frame_sort": "lexicographic",

        "trials": {},
    }


def validate_field_names(mark_rows, custom_fields):
    if len(mark_rows) != 4:
        raise ValueError("Exactly four timestamp category rows are required.")

    for index, names in enumerate(mark_rows):
        capacity = len(ROW_KEYS[index])
        if len(names) > capacity:
            raise ValueError(
                f"Timestamp row {index + 1} supports at most "
                f"{capacity} categories."
            )

    names = [
        name for row in mark_rows for name in row
    ] + list(custom_fields)

    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("Field names must be nonempty text.")

    if len(names) != len(set(names)):
        raise ValueError(
            "Timestamp and custom-variable names must be unique."
        )

    for name in names:
        if name in RESERVED_COLUMNS or name.startswith(COLUMN_PREFIXES):
            raise ValueError(
                f"'{name}' conflicts with a reserved CSV column name."
            )

        if "\n" in name or "\r" in name:
            raise ValueError("Field names cannot contain line breaks.")


def normalize_project(raw, name):
    """Accept integrated projects and both supplied legacy formats."""
    if not isinstance(raw, dict):
        raise ValueError("The project file must contain a JSON object.")

    application = raw.get("application")

    if application not in (None, APP_ID, "WorkSmartPointMarker"):
        raise ValueError("Unsupported project format.")

    if application == APP_ID and raw.get("version") != APP_VERSION:
        raise ValueError("Unsupported integrated project version.")

    if application == "WorkSmartPointMarker" and raw.get("version") != 1:
        raise ValueError("Unsupported point-marker project version.")

    project = new_project(name)
    project.update(json.loads(json.dumps(raw)))

    project["application"] = APP_ID
    project["version"] = APP_VERSION
    project["name"] = name

    if application == "WorkSmartPointMarker":
        project.setdefault("mark_rows", [["On", "Max", "Off"], [], [], []])
        project["frame_sort"] = raw.get("frame_sort", "natural")

    rows = project.get("mark_rows", [])
    if not isinstance(rows, list) or len(rows) > 4:
        raise ValueError("Invalid timestamp category rows.")

    rows = rows + [[] for _ in range(4 - len(rows))]
    project["mark_rows"] = rows

    validate_field_names(rows, project.get("custom_fields", []))

    fps = float(project.get("fps", 30))
    if not math.isfinite(fps) or not 0 < fps <= 1000:
        raise ValueError("FPS must be greater than 0 and at most 1000.")
    project["fps"] = fps

    if project.get("frame_sort") not in ("lexicographic", "natural"):
        project["frame_sort"] = "lexicographic"

    trials = project.get("trials", {})
    if not isinstance(trials, dict):
        raise ValueError("Invalid trial data.")

    normalized_trials = {}

    for key, trial in trials.items():
        if not isinstance(trial, dict):
            raise ValueError("Invalid trial record.")

        key = str(Path(key).resolve())

        trial.setdefault("measurements", [])
        trial.setdefault("comparisons", [])
        trial.setdefault("marks", {})
        trial.setdefault("frame_links", {"start": "", "end": ""})
        trial["frame_links"].setdefault("start", "")
        trial["frame_links"].setdefault("end", "")
        trial.setdefault("custom", {})
        trial.setdefault("remarks", "")
        trial.setdefault("last_frame", None)
        trial.setdefault("spacing_x", None)
        trial.setdefault("spacing_y", None)
        trial.setdefault("status", "draft")

        structure_ids = set()
        structure_names = set()

        for structure in trial["measurements"]:
            structure.setdefault("id", uuid.uuid4().hex)
            structure.setdefault("start", None)
            structure.setdefault("end", None)

            if not structure.get("name"):
                raise ValueError("A saved structure has no name.")

            if (
                structure["id"] in structure_ids
                or structure["name"] in structure_names
            ):
                raise ValueError("Duplicate saved structure name or ID.")

            structure_ids.add(structure["id"])
            structure_names.add(structure["name"])

        comparison_names = set()
        comparison_ids = set()

        for comparison in trial["comparisons"]:
            comparison.setdefault("id", uuid.uuid4().hex)

            if not comparison.get("name"):
                raise ValueError("A saved comparison has no name.")

            if (
                comparison["name"] in comparison_names
                or comparison["id"] in comparison_ids
            ):
                raise ValueError("Duplicate saved comparison name or ID.")

            comparison_names.add(comparison["name"])
            comparison_ids.add(comparison["id"])

        normalized_trials[key] = trial

    project["trials"] = normalized_trials

    if project.get("current_trial"):
        project["current_trial"] = str(
            Path(project["current_trial"]).resolve()
        )

    return project


def fmt(value, digits=3):
    return "undefined" if value is None else f"{value:.{digits}f}"


# ----------------------------------------------------------------------
# Geometry: independent of the GUI
# ----------------------------------------------------------------------

def line_geometry(vector_1, vector_2):
    """
    Vectors use Cartesian orientation:
        +X right
        +Y up

    Returns lengths, signed orientations, smaller included angle,
    signed rotation, and endpoint distance after aligning the origins.
    """
    x1, y1 = vector_1
    x2, y2 = vector_2

    if not all(
        math.isfinite(value)
        for value in (x1, y1, x2, y2)
    ):
        raise ValueError("Geometry contains a nonfinite coordinate.")

    length_1 = math.hypot(x1, y1)
    length_2 = math.hypot(x2, y2)

    angle_a = (
        math.degrees(math.atan2(y1, x1))
        if length_1 > 0 else None
    )
    angle_b = (
        math.degrees(math.atan2(y2, x2))
        if length_2 > 0 else None
    )

    signed_rotation = None
    angle_c = None

    if length_1 > 0 and length_2 > 0:
        # Normalize first to avoid unnecessarily large dot/cross products.
        ux1, uy1 = x1 / length_1, y1 / length_1
        ux2, uy2 = x2 / length_2, y2 / length_2

        cross = ux1 * uy2 - uy1 * ux2
        dot = ux1 * ux2 + uy1 * uy2

        signed_rotation = math.degrees(math.atan2(cross, dot))
        angle_c = abs(signed_rotation)

    # Equivalent to:
    # sqrt(L1**2 + L2**2 - 2*L1*L2*cos(c))
    #
    # Vector subtraction is more numerically stable for nearly equal lines.
    opposite_side = math.hypot(x2 - x1, y2 - y1)

    return {
        "L1": length_1,
        "L2": length_2,
        "AngleA": angle_a,
        "AngleB": angle_b,
        "AngleC": angle_c,
        "SignedRotation": signed_rotation,
        "OppositeSide": opposite_side,
        "vector_1": vector_1,
        "vector_2": vector_2,
    }


def geometry_from_points(a1, b1, a2, b2, spacing_x=1.0, spacing_y=1.0):
    # Stored image coordinates have positive Y downward.
    # Negate Y for Cartesian angle calculations.
    vector_1 = (
        (b1["x"] - a1["x"]) * spacing_x,
        -(b1["y"] - a1["y"]) * spacing_y,
    )
    vector_2 = (
        (b2["x"] - a2["x"]) * spacing_x,
        -(b2["y"] - a2["y"]) * spacing_y,
    )

    return line_geometry(vector_1, vector_2)


def run_geometry_self_tests():
    result = line_geometry((10.0, 0.0), (0.0, 10.0))

    assert math.isclose(result["L1"], 10.0)
    assert math.isclose(result["L2"], 10.0)
    assert math.isclose(result["AngleA"], 0.0)
    assert math.isclose(result["AngleB"], 90.0)
    assert math.isclose(result["AngleC"], 90.0)
    assert math.isclose(result["OppositeSide"], math.sqrt(200.0))

    # Identical vectors, regardless of their original positions.
    result = line_geometry((3.0, 4.0), (3.0, 4.0))
    assert math.isclose(result["AngleC"], 0.0, abs_tol=1e-12)
    assert math.isclose(result["OppositeSide"], 0.0, abs_tol=1e-12)

    # Wrapped orientation difference: 170 degrees to -170 degrees = +20.
    def vector(angle):
        radians = math.radians(angle)
        return math.cos(radians), math.sin(radians)

    result = line_geometry(vector(170), vector(-170))
    assert math.isclose(result["AngleC"], 20.0, abs_tol=1e-10)
    assert math.isclose(result["SignedRotation"], 20.0, abs_tol=1e-10)

    # Zero-length lines have undefined orientation.
    result = line_geometry((0.0, 0.0), (3.0, 4.0))
    assert result["AngleA"] is None
    assert result["AngleC"] is None
    assert math.isclose(result["OppositeSide"], 5.0)

    # Translation of A is removed by aligning the line origins.
    a1 = {"x": 10.0, "y": 10.0}
    b1 = {"x": 20.0, "y": 10.0}
    a2 = {"x": 100.0, "y": 100.0}
    b2 = {"x": 110.0, "y": 100.0}
    result = geometry_from_points(a1, b1, a2, b2)
    assert math.isclose(result["OppositeSide"], 0.0, abs_tol=1e-12)

    # Unequal pixel spacings change calibrated angles.
    a = {"x": 0.0, "y": 0.0}
    b = {"x": 1.0, "y": -1.0}
    result = geometry_from_points(a, b, a, b, 2.0, 1.0)
    assert math.isclose(
        result["AngleA"],
        math.degrees(math.atan2(1.0, 2.0)),
    )

    print("Geometry self-tests passed.")


# ----------------------------------------------------------------------
# Integrated GUI
# ----------------------------------------------------------------------

class UltrasoundAnnotator:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Timestamps + Point Marker")

        self.script_dir = Path(__file__).resolve().parent
        self.projects_dir = self.script_dir / "projects"
        self.projects_dir.mkdir(exist_ok=True)

        self.project = None
        self.project_path = None

        self.in_main = False
        self.loading_form = False

        self.trial_paths = []
        self.trial_key = None
        self.frames = []
        self.frame_index = -1

        self.measurement_index = 0
        self.comparison_index = 0
        self.armed_endpoint = None

        self.image = None
        self.photo = None
        self.transform = None
        self.render_key = None

        self.play_job = None
        self.save_job = None

        self.custom_vars = {}
        self.mark_labels = {}

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<KeyPress>", self.handle_key)
        self.root.bind("<MouseWheel>", self.sidebar_mousewheel)
        self.root.bind("<Button-4>", self.sidebar_mousewheel)
        self.root.bind("<Button-5>", self.sidebar_mousewheel)

        self.show_menu()

    # ------------------------------------------------------------------
    # State and persistence
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

        items = self.trial["measurements"]
        if 0 <= self.measurement_index < len(items):
            return items[self.measurement_index]
        return None

    @property
    def comparison(self):
        if self.trial is None:
            return None

        items = self.trial["comparisons"]
        if 0 <= self.comparison_index < len(items):
            return items[self.comparison_index]
        return None

    def timestamp_names(self):
        return [
            name
            for row in self.project["mark_rows"]
            for name in row
        ]

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

    def cancel_pending_save(self):
        if self.save_job is not None:
            self.root.after_cancel(self.save_job)
            self.save_job = None

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
                    allow_nan=False,
                ),
            )
            return True

        except Exception as exc:
            messagebox.showerror(
                "Save failed",
                f"The project could not be saved:\n{exc}",
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
        self.update_progress()
        self.save_soon()

    def changed(self):
        if self.trial is not None:
            self.trial["status"] = "draft"

        self.refresh_panels()
        self.draw()
        self.save_project()

    def clear_ui(self):
        self.stop_playback()
        self.cancel_pending_save()
        self.in_main = False

        for widget in self.root.winfo_children():
            widget.destroy()

        self.trial_key = None
        self.frames = []
        self.frame_index = -1
        self.image = None
        self.photo = None
        self.transform = None
        self.render_key = None
        self.armed_endpoint = None

    # ------------------------------------------------------------------
    # Project menu and migration
    # ------------------------------------------------------------------

    def show_menu(self):
        self.clear_ui()

        self.root.minsize(540, 380)
        self.root.geometry("680x470")
        self.root.resizable(True, True)

        body = ttk.Frame(self.root, padding=28)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="WorkSmart",
            font=("Arial", 23, "bold"),
        ).pack(pady=(5, 5))

        ttk.Label(
            body,
            text="Timestamping + Ultrasound Point Marking",
            font=("Arial", 12),
        ).pack(pady=(0, 20))

        box = ttk.LabelFrame(body, text="Create project", padding=12)
        box.pack(fill="x", pady=6)

        self.new_project_var = tk.StringVar()

        ttk.Entry(
            box,
            textvariable=self.new_project_var,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ttk.Button(
            box,
            text="Create",
            command=self.create_project,
        ).pack(side="right")

        box = ttk.LabelFrame(body, text="Load project", padding=12)
        box.pack(fill="x", pady=6)

        names = sorted(
            [path.stem for path in self.projects_dir.glob("*.json")],
            key=natural_key,
        )

        self.project_combo = ttk.Combobox(
            box,
            values=names,
            state="readonly",
        )
        self.project_combo.pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )

        if names:
            self.project_combo.current(0)

        ttk.Button(
            box,
            text="Launch",
            command=self.load_project,
        ).pack(side="right")

        ttk.Button(
            body,
            text="Import a Timestamper / Point Marker project JSON",
            command=self.import_project,
        ).pack(fill="x", pady=12)

        ttk.Label(
            body,
            text=(
                f"Projects: {self.projects_dir}\n"
                "Legacy project files are backed up before conversion."
            ),
            wraplength=610,
        ).pack(anchor="w", pady=8)

    def valid_project_name(self, name):
        return bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", name)
        )

    def create_project(self):
        name = self.new_project_var.get().strip()

        if not self.valid_project_name(name):
            messagebox.showerror(
                "Project name",
                "Use letters, numbers, spaces, underscores, or hyphens.\n"
                "Start with a letter or number. Maximum 80 characters.",
            )
            return

        path = self.projects_dir / f"{name}.json"

        if path.exists():
            messagebox.showerror("Project exists", "Choose another name.")
            return

        self.project = new_project(name)
        self.project_path = path

        if self.save_project():
            self.setup_main_ui()
            self.refresh_trials()

    def load_project(self):
        name = self.project_combo.get()
        if not name:
            return

        path = self.projects_dir / f"{name}.json"

        try:
            with path.open(encoding="utf-8-sig") as handle:
                raw = json.load(handle)

            project = normalize_project(raw, name)

            if raw.get("application") != APP_ID:
                backup_once(path, ".premerge.bak")

                # A legacy point-marker CSV has a different row layout.
                if raw.get("application") == "WorkSmartPointMarker":
                    project["csv_path"] = ""

            self.project = project
            self.project_path = path

            self.setup_main_ui()
            self.refresh_trials()

        except Exception as exc:
            messagebox.showerror(
                "Load failed",
                str(exc),
                parent=self.root,
            )

    def import_project(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Import project JSON",
            initialdir=str(self.script_dir),
            filetypes=[("JSON project", "*.json")],
        )

        if not filename:
            return

        source = Path(filename)

        try:
            with source.open(encoding="utf-8-sig") as handle:
                raw = json.load(handle)

            suggested = re.sub(
                r"[^A-Za-z0-9 _-]",
                "_",
                source.stem,
            ).strip()

            if not suggested or not suggested[0].isalnum():
                suggested = "ImportedProject"

            suggested = suggested[:65] + "_merged"

            name = simpledialog.askstring(
                "Imported project name",
                "Save the imported project under this new name:",
                initialvalue=suggested,
                parent=self.root,
            )

            if name is None:
                return

            name = name.strip()

            if not self.valid_project_name(name):
                raise ValueError("Invalid project name.")

            destination = self.projects_dir / f"{name}.json"

            if destination.exists():
                raise ValueError(
                    "A project with this name already exists."
                )

            project = normalize_project(raw, name)

            if raw.get("application") == "WorkSmartPointMarker":
                project["csv_path"] = ""

            atomic_write(
                destination,
                lambda handle: json.dump(
                    project,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            )

            self.project = project
            self.project_path = destination

            self.setup_main_ui()
            self.refresh_trials()

            if raw.get("application") == "WorkSmartPointMarker":
                messagebox.showinfo(
                    "Point-marker project imported",
                    "Your structures and point annotations were copied.\n"
                    "The original project was not modified.\n\n"
                    "Select a combined output CSV and add the comparisons "
                    "you want in the Point Marking tab.",
                )

        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))

    def return_to_menu(self):
        self.stop_playback()
        if self.save_project():
            self.show_menu()

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def button_row(self, parent, buttons):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)

        for text, command in buttons:
            ttk.Button(
                row,
                text=text,
                command=command,
            ).pack(side="left", fill="x", expand=True, padx=1)

        return row

    def setup_main_ui(self):
        self.clear_ui()
        self.loading_form = True

        self.root.resizable(True, True)
        self.root.minsize(1000, 650)
        self.root.geometry("1380x900")

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
            wraplength=1250,
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
            fill="both", expand=True, padx=8, pady=8
        )
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<Button-1>", self.canvas_click)

        navigation = ttk.Frame(left, padding=8)
        navigation.pack(fill="x")

        self.play_button = ttk.Button(
            navigation,
            text="Play",
            width=7,
            command=self.toggle_playback,
        )
        self.play_button.pack(side="left")

        ttk.Button(
            navigation,
            text="<",
            width=3,
            command=lambda: self.step(-1),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            navigation,
            text=">",
            width=3,
            command=lambda: self.step(1),
        ).pack(side="left")

        self.slider = tk.Scale(
            navigation,
            from_=1,
            to=1,
            orient="horizontal",
            showvalue=False,
            resolution=1,
            command=self.slider_changed,
        )
        self.slider.pack(
            side="left", fill="x", expand=True, padx=8
        )

        self.goto_var = tk.StringVar(value="1")

        ttk.Entry(
            navigation,
            width=6,
            textvariable=self.goto_var,
        ).pack(side="left")

        ttk.Button(
            navigation,
            text="Go",
            command=self.go_to_number,
        ).pack(side="left", padx=4)

        self.frame_var = tk.StringVar(value="No frame loaded")
        self.message_var = tk.StringVar(value="Select a parent folder.")

        ttk.Label(
            left,
            textvariable=self.frame_var,
            padding=(8, 0),
        ).pack(fill="x")

        ttk.Label(
            left,
            textvariable=self.message_var,
            padding=8,
            wraplength=800,
        ).pack(fill="x")

        # Scrollable sidebar.
        outer = ttk.Frame(container, width=420)
        outer.pack(side="right", fill="y")
        outer.pack_propagate(False)

        self.sidebar_canvas = tk.Canvas(
            outer,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=self.sidebar_canvas.yview,
        )

        self.sidebar_canvas.configure(
            yscrollcommand=scrollbar.set
        )
        scrollbar.pack(side="right", fill="y")
        self.sidebar_canvas.pack(
            side="left", fill="both", expand=True
        )

        self.sidebar = ttk.Frame(
            self.sidebar_canvas,
            padding=10,
        )
        window = self.sidebar_canvas.create_window(
            (0, 0),
            window=self.sidebar,
            anchor="nw",
        )

        self.sidebar.bind(
            "<Configure>",
            lambda event: self.sidebar_canvas.configure(
                scrollregion=self.sidebar_canvas.bbox("all")
            ),
        )
        self.sidebar_canvas.bind(
            "<Configure>",
            lambda event: self.sidebar_canvas.itemconfigure(
                window,
                width=event.width,
            ),
        )

        self.button_row(
            self.sidebar,
            [
                ("Parent Folder", self.select_parent),
                ("Output CSV", self.select_csv),
            ],
        )

        ttk.Label(self.sidebar, text="Trial:").pack(anchor="w")

        self.trial_combo = ttk.Combobox(
            self.sidebar,
            state="readonly",
        )
        self.trial_combo.pack(fill="x")
        self.trial_combo.bind(
            "<<ComboboxSelected>>",
            self.trial_selected,
        )

        self.progress_var = tk.StringVar(value="No trials loaded")
        ttk.Label(
            self.sidebar,
            textvariable=self.progress_var,
        ).pack(anchor="w", pady=5)

        self.notebook = ttk.Notebook(self.sidebar)
        self.notebook.pack(fill="x", pady=8)

        self.timestamp_tab = ttk.Frame(self.notebook, padding=8)
        self.point_tab = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(
            self.timestamp_tab,
            text="Timestamps",
        )
        self.notebook.add(
            self.point_tab,
            text="Point Marking",
        )
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self.tab_changed,
        )

        self.timestamp_container = ttk.Frame(self.timestamp_tab)
        self.timestamp_container.pack(fill="x")

        self.build_timestamp_ui()
        self.build_point_ui()

        self.custom_box = ttk.LabelFrame(
            self.sidebar,
            text="Custom Variables",
            padding=8,
        )
        self.custom_box.pack(fill="x", pady=8)

        self.rebuild_custom_fields()

        ttk.Label(
            self.sidebar,
            text="Observations:",
        ).pack(anchor="w")

        self.remarks_var = tk.StringVar()
        self.remarks_var.trace_add("write", self.form_changed)

        ttk.Entry(
            self.sidebar,
            textvariable=self.remarks_var,
        ).pack(fill="x", pady=5)

        self.button_row(
            self.sidebar,
            [
                ("SKIP — keep draft", self.skip_trial),
                ("SUBMIT & NEXT", self.submit),
            ],
        )

        ttk.Label(
            self.sidebar,
            text=(
                "Timestamps tab: configured category hotkeys\n"
                "Point Marking tab: S = start, E = end\n"
                "Space = play/pause   Left/Right = step\n"
                "Enter = submit   Escape = cancel marking\n\n"
                "Solid +: current frame\n"
                "Dashed +: reference from another frame\n\n"
                "CSV: one appended row per submission."
            ),
            wraplength=370,
        ).pack(anchor="w", pady=10)

        self.loading_form = False
        self.in_main = True

        self.update_paths()
        self.refresh_panels()

    def build_timestamp_ui(self):
        for widget in self.timestamp_container.winfo_children():
            widget.destroy()

        self.mark_labels = {}

        for row_index, names in enumerate(self.project["mark_rows"]):
            if not names:
                continue

            ttk.Label(
                self.timestamp_container,
                text=f"Category {row_index + 1}",
                font=("Arial", 10, "bold"),
            ).pack(anchor="w", pady=(8, 3))

            for column_index, name in enumerate(names):
                key = ROW_KEYS[row_index][column_index]

                row = ttk.Frame(self.timestamp_container)
                row.pack(fill="x", pady=2)

                ttk.Button(
                    row,
                    text=f"({key.upper()}) {name}",
                    command=lambda n=name: self.set_mark(n),
                ).pack(side="left", fill="x", expand=True)

                label = ttk.Label(row, text="-", width=12)
                label.pack(side="left", padx=4)
                self.mark_labels[name] = label

                ttk.Button(
                    row,
                    text="Go",
                    width=3,
                    command=lambda n=name: self.go_to_mark(n),
                ).pack(side="left")

                ttk.Button(
                    row,
                    text="×",
                    width=3,
                    command=lambda n=name: self.clear_mark(n),
                ).pack(side="left", padx=(2, 0))

        ttk.Label(
            self.timestamp_container,
            text=(
                "A timestamp stores the current filename without its "
                "extension, as in the original Timestamper.\n\n"
                "Use the Point Marking tab to link Start/End to these "
                "categories or to mark manually selected frames."
            ),
            wraplength=350,
        ).pack(anchor="w", pady=12)

    def build_point_ui(self):
        link_box = ttk.LabelFrame(
            self.point_tab,
            text="Point frame selection — this trial",
            padding=7,
        )
        link_box.pack(fill="x", pady=4)

        self.link_combos = {}

        for endpoint, label in [
            ("start", "Start / frame 1:"),
            ("end", "End / frame 2:"),
        ]:
            ttk.Label(link_box, text=label).pack(anchor="w")

            combo = ttk.Combobox(link_box, state="readonly")
            combo.pack(fill="x", pady=(0, 5))
            combo.bind(
                "<<ComboboxSelected>>",
                lambda event, e=endpoint: self.link_changed(e),
            )
            self.link_combos[endpoint] = combo

        ttk.Label(
            link_box,
            text=(
                "Links apply to all structures in this trial. "
                "Set automatically opens the linked timestamp frame."
            ),
            wraplength=340,
        ).pack(anchor="w")

        structure_box = ttk.LabelFrame(
            self.point_tab,
            text="Structures",
            padding=7,
        )
        structure_box.pack(fill="x", pady=5)

        self.measurement_combo = ttk.Combobox(
            structure_box,
            state="readonly",
        )
        self.measurement_combo.pack(fill="x")
        self.measurement_combo.bind(
            "<<ComboboxSelected>>",
            self.measurement_selected,
        )

        self.button_row(
            structure_box,
            [
                ("Add", self.add_structure),
                ("Rename", self.rename_structure),
                ("Delete", self.delete_structure),
            ],
        )

        self.point_vars = {}

        for endpoint, label in [
            ("start", "Start point — A1 / B1"),
            ("end", "End point — A2 / B2"),
        ]:
            box = ttk.LabelFrame(
                structure_box,
                text=label,
                padding=5,
            )
            box.pack(fill="x", pady=3)

            variable = tk.StringVar(value="Not marked")
            self.point_vars[endpoint] = variable

            ttk.Label(
                box,
                textvariable=variable,
                wraplength=320,
            ).pack(anchor="w")

            self.button_row(
                box,
                [
                    ("Set", lambda e=endpoint: self.arm(e)),
                    ("Go to", lambda e=endpoint: self.go_to_endpoint(e)),
                    ("Clear", lambda e=endpoint: self.clear_endpoint(e)),
                ],
            )

        self.displacement_var = tk.StringVar()

        ttk.Label(
            structure_box,
            textvariable=self.displacement_var,
            wraplength=335,
        ).pack(anchor="w", pady=5)

        self.reference_var = tk.BooleanVar(
            value=self.project["show_references"]
        )

        ttk.Checkbutton(
            structure_box,
            text="Show reference points from other frames",
            variable=self.reference_var,
            command=self.reference_changed,
        ).pack(anchor="w", pady=4)

        comparison_box = ttk.LabelFrame(
            self.point_tab,
            text="Line comparisons",
            padding=7,
        )
        comparison_box.pack(fill="x", pady=5)

        self.comparison_combo = ttk.Combobox(
            comparison_box,
            state="readonly",
        )
        self.comparison_combo.pack(fill="x")
        self.comparison_combo.bind(
            "<<ComboboxSelected>>",
            self.comparison_selected,
        )

        self.button_row(
            comparison_box,
            [
                ("Add", self.add_comparison),
                ("Edit", self.edit_comparison),
                ("Delete", self.delete_comparison),
            ],
        )

        self.geometry_var = tk.StringVar()

        ttk.Label(
            comparison_box,
            textvariable=self.geometry_var,
            wraplength=335,
            justify="left",
        ).pack(anchor="w", pady=5)

        ttk.Button(
            comparison_box,
            text="View aligned triangle",
            command=self.show_triangle,
        ).pack(fill="x", pady=4)

        self.calibration_var = tk.StringVar()

        ttk.Label(
            self.point_tab,
            textvariable=self.calibration_var,
            wraplength=345,
        ).pack(anchor="w", pady=6)

    def rebuild_custom_fields(self):
        previous_loading = self.loading_form
        self.loading_form = True

        for widget in self.custom_box.winfo_children():
            widget.destroy()

        self.custom_vars = {}
        values = self.trial.get("custom", {}) if self.trial else {}

        for name in self.project["custom_fields"]:
            ttk.Label(self.custom_box, text=name).pack(anchor="w")

            variable = tk.StringVar(value=values.get(name, ""))
            variable.trace_add("write", self.form_changed)

            ttk.Entry(
                self.custom_box,
                textvariable=variable,
            ).pack(fill="x", pady=(0, 5))

            self.custom_vars[name] = variable

        self.loading_form = previous_loading

    def sidebar_mousewheel(self, event):
        if not self.in_main:
            return

        widget = self.root.winfo_containing(event.x_root, event.y_root)
        inside = False

        while widget is not None:
            if widget == self.sidebar_canvas:
                inside = True
                break
            widget = getattr(widget, "master", None)

        if not inside:
            return

        if getattr(event, "num", None) == 4:
            amount = -1
        elif getattr(event, "num", None) == 5:
            amount = 1
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return
            amount = -int(delta / 120)
            if amount == 0:
                amount = -1 if delta > 0 else 1

        self.sidebar_canvas.yview_scroll(amount, "units")
        return "break"

    def tab_changed(self, _event=None):
        if not self.in_main:
            return

        self.cancel_marking()

        if self.point_tab_active():
            self.message_var.set(
                "Point Marking: S sets Start, E sets End. "
                "Choose a structure, then click Set."
            )
        else:
            self.message_var.set(
                "Timestamps: category hotkeys mark the current frame."
            )

    def point_tab_active(self):
        return self.notebook.select() == str(self.point_tab)

    def update_paths(self):
        self.paths_var.set(
            f"Source: {self.project['parent_folder'] or '(not selected)'}\n"
            f"CSV: {self.project['csv_path'] or '(not selected)'}"
        )

    # ------------------------------------------------------------------
    # Trial/frame navigation
    # ------------------------------------------------------------------

    def image_names(self, folder):
        names = [
            path.name
            for path in Path(folder).iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and not path.name.startswith((".", "~"))
        ]

        if self.project["frame_sort"] == "natural":
            return sorted(names, key=natural_key)

        return sorted(names)

    def select_parent(self):
        folder = filedialog.askdirectory(parent=self.root)
        if not folder:
            return

        self.stop_playback()

        if not self.save_project():
            return

        self.project["parent_folder"] = str(Path(folder).resolve())
        self.project["current_trial"] = None
        self.project["last_trial_idx"] = 0

        self.update_paths()
        self.refresh_trials()
        self.save_project()

    def select_csv(self):
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            title="Select combined output CSV",
        )

        if filename:
            self.project["csv_path"] = str(Path(filename).resolve())
            self.update_paths()
            self.save_project()

    def refresh_trials(self):
        self.stop_playback()
        self.cancel_pending_save()
        self.trial_key = None
        self.trial_paths = []
        self.frames = []
        self.frame_index = -1
        self.image = None
        self.render_key = None

        folder = self.project["parent_folder"]

        if folder and Path(folder).is_dir():
            try:
                candidates = [
                    path
                    for path in Path(folder).iterdir()
                    if path.is_dir()
                ]

                key = (
                    (lambda path: natural_key(path.name))
                    if self.project["frame_sort"] == "natural"
                    else (lambda path: path.name)
                )

                for path in sorted(candidates, key=key):
                    if self.image_names(path):
                        self.trial_paths.append(str(path.resolve()))

            except OSError as exc:
                messagebox.showerror("Folder error", str(exc))

        self.trial_combo["values"] = [
            Path(path).name for path in self.trial_paths
        ]

        if self.trial_paths:
            current = self.project.get("current_trial")

            if current in self.trial_paths:
                index = self.trial_paths.index(current)
            else:
                index = int(self.project.get("last_trial_idx", 0))
                index = max(0, min(index, len(self.trial_paths) - 1))

            self.load_trial(index, save_previous=False)

        else:
            self.trial_combo.set("")
            self.loading_form = True
            self.remarks_var.set("")

            for variable in self.custom_vars.values():
                variable.set("")

            self.loading_form = False
            self.frame_var.set("No frame loaded")
            self.message_var.set(
                "Choose a parent folder containing trial subfolders "
                "with image files."
            )
            self.refresh_panels()
            self.draw()

    def trial_selected(self, _event=None):
        index = self.trial_combo.current()
        if index >= 0:
            self.load_trial(index)

    def load_trial(self, index, save_previous=True):
        self.stop_playback()

        if not 0 <= index < len(self.trial_paths):
            return

        if save_previous and self.trial is not None:
            if not self.save_project():
                if self.trial_key in self.trial_paths:
                    self.trial_combo.current(
                        self.trial_paths.index(self.trial_key)
                    )
                return

        key = self.trial_paths[index]

        try:
            frames = self.image_names(key)
            if not frames:
                raise ValueError("This trial no longer contains image files.")

        except Exception as exc:
            messagebox.showerror("Trial error", str(exc))
            return

        self.cancel_pending_save()
        self.cancel_marking()

        self.trial_key = key
        self.project["current_trial"] = key
        self.project["last_trial_idx"] = index

        if key not in self.project["trials"]:
            self.project["trials"][key] = new_trial()

        self.frames = frames
        self.frame_index = -1
        self.image = None
        self.render_key = None
        self.measurement_index = 0
        self.comparison_index = 0

        self.trial_combo.current(index)

        # Compatibility for any older marks stored as filename stems.
        for name, mark in list(self.trial["marks"].items()):
            if isinstance(mark, str):
                matches = [
                    filename
                    for filename in self.frames
                    if Path(filename).stem == mark
                ]

                self.trial["marks"][name] = (
                    {
                        "filename": matches[0],
                        "value": mark,
                    }
                    if len(matches) == 1 else None
                )

        self.loading_form = True
        self.remarks_var.set(self.trial.get("remarks", ""))

        for name, variable in self.custom_vars.items():
            variable.set(self.trial.get("custom", {}).get(name, ""))

        self.loading_form = False

        self.slider.configure(to=max(1, len(self.frames)))

        previous = self.trial.get("last_frame")
        frame_index = (
            self.frames.index(previous)
            if previous in self.frames else 0
        )

        self.show_frame(frame_index)
        self.refresh_panels()

        self.message_var.set(
            "Use Timestamps to mark key frames, or Point Marking "
            "to place structure points."
        )
        self.save_project()

    def update_progress(self):
        if self.trial is None:
            self.progress_var.set("No trials loaded")
            return

        index = self.trial_paths.index(self.trial_key)

        self.progress_var.set(
            f"Trial {index + 1}/{len(self.trial_paths)}"
            f"   |   {self.trial.get('status', 'draft')}"
        )

    def show_frame(self, index):
        if not self.frames:
            return

        index = max(0, min(index, len(self.frames) - 1))

        if index == self.frame_index:
            return

        self.cancel_marking()
        self.frame_index = index
        self.image = None
        self.render_key = None

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
        if self.frames:
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

    def go_to_filename(self, filename):
        if filename not in self.frames:
            messagebox.showerror(
                "Missing frame",
                f"Source frame is unavailable:\n{filename}",
            )
            return False

        self.stop_playback()
        self.show_frame(self.frames.index(filename))
        return self.image is not None

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

        self.cancel_marking()

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
    # Timestamps and frame links
    # ------------------------------------------------------------------

    def timestamp_filename(self, name):
        if self.trial is None:
            return None

        mark = self.trial["marks"].get(name)
        return mark.get("filename") if isinstance(mark, dict) else None

    def confirm_linked_point_changes(self, endpoints, filename):
        affected = []

        for structure in self.trial["measurements"]:
            for endpoint in endpoints:
                point = structure.get(endpoint)

                if point and point["filename"] != filename:
                    affected.append((structure, endpoint))

        if affected:
            if not messagebox.askyesno(
                "Linked frame changed",
                "This changes the frame used by existing linked points.\n\n"
                f"{len(affected)} point(s) must be cleared and marked again.\n"
                "Continue?",
                parent=self.root,
            ):
                return False

            for structure, endpoint in affected:
                structure[endpoint] = None

        return True

    def set_mark(self, name):
        if self.trial is None or self.image is None:
            return

        self.stop_playback()
        filename = self.frames[self.frame_index]

        endpoints = [
            endpoint
            for endpoint, linked_name in self.trial["frame_links"].items()
            if linked_name == name
        ]

        if not self.confirm_linked_point_changes(endpoints, filename):
            return

        self.trial["marks"][name] = {
            "filename": filename,
            "frame_index": self.frame_index + 1,
            "value": Path(filename).stem,
        }

        self.message_var.set(
            f"Timestamp '{name}' set to {Path(filename).stem}."
        )
        self.changed()

    def clear_mark(self, name):
        if self.trial is None or not self.trial["marks"].get(name):
            return

        if not messagebox.askyesno(
            "Clear timestamp",
            f"Clear '{name}'?",
            parent=self.root,
        ):
            return

        endpoints = [
            endpoint
            for endpoint, linked_name in self.trial["frame_links"].items()
            if linked_name == name
        ]

        if not self.confirm_linked_point_changes(endpoints, None):
            return

        self.trial["marks"][name] = None
        self.cancel_marking()
        self.changed()

    def go_to_mark(self, name):
        filename = self.timestamp_filename(name)

        if filename is None:
            messagebox.showinfo(
                "Timestamp not marked",
                f"Mark '{name}' first.",
            )
            return

        self.go_to_filename(filename)

    def refresh_link_combos(self):
        names = self.timestamp_names()
        values = [MANUAL_FRAME_LABEL] + [
            f"Timestamp: {name}" for name in names
        ]

        for endpoint, combo in self.link_combos.items():
            combo["values"] = values

            linked_name = (
                self.trial["frame_links"].get(endpoint, "")
                if self.trial else ""
            )

            if linked_name in names:
                combo.current(names.index(linked_name) + 1)
            else:
                combo.current(0)

    def link_changed(self, endpoint):
        if self.trial is None:
            self.refresh_link_combos()
            return

        self.stop_playback()
        names = self.timestamp_names()
        index = self.link_combos[endpoint].current()

        linked_name = names[index - 1] if index > 0 else ""
        previous = self.trial["frame_links"].get(endpoint, "")

        if linked_name == previous:
            return

        if linked_name:
            filename = self.timestamp_filename(linked_name)

            if not self.confirm_linked_point_changes(
                [endpoint],
                filename,
            ):
                self.refresh_link_combos()
                return

        # Switching to Manual retains the existing points.
        self.trial["frame_links"][endpoint] = linked_name
        self.cancel_marking()
        self.changed()

    # ------------------------------------------------------------------
    # Structure management and marking
    # ------------------------------------------------------------------

    def request_name(self, title, initial, existing):
        name = simpledialog.askstring(
            title,
            "Name:",
            initialvalue=initial,
            parent=self.root,
        )

        if name is None:
            return None

        name = name.strip()

        if (
            not name
            or len(name) > 80
            or "::" in name
            or "\n" in name
            or "\r" in name
        ):
            messagebox.showerror(
                "Invalid name",
                "Use 1–80 characters, without line breaks or '::'.",
            )
            return None

        if name in existing:
            messagebox.showerror("Duplicate name", "Use a unique name.")
            return None

        return name

    def add_structure(self):
        if self.trial is None:
            return

        name = self.request_name(
            "Add structure",
            "",
            {item["name"] for item in self.trial["measurements"]},
        )

        if name:
            self.trial["measurements"].append(new_structure(name))
            self.measurement_index = len(self.trial["measurements"]) - 1
            self.cancel_marking()
            self.changed()

    def rename_structure(self):
        structure = self.measurement
        if structure is None:
            return

        name = self.request_name(
            "Rename structure",
            structure["name"],
            {
                item["name"]
                for item in self.trial["measurements"]
                if item["id"] != structure["id"]
            },
        )

        if name:
            structure["name"] = name
            self.changed()

    def delete_structure(self):
        structure = self.measurement
        if structure is None:
            return

        dependent = [
            comparison
            for comparison in self.trial["comparisons"]
            if structure["id"] in (
                comparison["a_id"],
                comparison["b_id"],
            )
        ]

        text = f"Delete '{structure['name']}' and its points?"

        if dependent:
            text += (
                "\n\nThe following comparisons will also be deleted:\n"
                + "\n".join(item["name"] for item in dependent)
            )

        if not messagebox.askyesno("Delete structure", text):
            return

        self.trial["measurements"].remove(structure)
        self.trial["comparisons"] = [
            item
            for item in self.trial["comparisons"]
            if item not in dependent
        ]

        self.measurement_index = 0
        self.comparison_index = 0
        self.cancel_marking()
        self.changed()

    def measurement_selected(self, _event=None):
        self.measurement_index = self.measurement_combo.current()
        self.cancel_marking()
        self.refresh_panels()
        self.draw()

    def cancel_marking(self):
        self.armed_endpoint = None

        if self.in_main and hasattr(self, "canvas"):
            self.canvas.configure(cursor="")

    def arm(self, endpoint):
        if self.measurement is None or not self.frames:
            return

        self.stop_playback()

        linked_name = self.trial["frame_links"].get(endpoint, "")

        if linked_name:
            filename = self.timestamp_filename(linked_name)

            if filename is None:
                messagebox.showinfo(
                    "Timestamp required",
                    f"Mark timestamp '{linked_name}' first.",
                )
                return

            if not self.go_to_filename(filename):
                return

        if self.image is None:
            return

        self.armed_endpoint = endpoint
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()

        self.message_var.set(
            f"Click to set {endpoint.upper()} for "
            f"'{self.measurement['name']}' on "
            f"{self.frames[self.frame_index]}. Escape cancels."
        )

    def canvas_click(self, event):
        self.canvas.focus_set()

        if (
            not self.point_tab_active()
            or self.armed_endpoint is None
            or self.measurement is None
            or self.image is None
            or self.transform is None
        ):
            return

        endpoint = self.armed_endpoint
        filename = self.frames[self.frame_index]
        linked_name = self.trial["frame_links"].get(endpoint, "")

        if linked_name and self.timestamp_filename(linked_name) != filename:
            self.cancel_marking()
            messagebox.showerror(
                "Wrong frame",
                "Use Set again to open the linked timestamp frame.",
            )
            return

        ox, oy, scale_x, scale_y = self.transform
        x = (event.x - ox) / scale_x
        y = (event.y - oy) / scale_y
        width, height = self.image.size

        if not (0 <= x < width and 0 <= y < height):
            return

        self.measurement[endpoint] = {
            "filename": filename,
            "frame_index": self.frame_index + 1,
            "x": float(x),
            "y": float(y),
            "width": width,
            "height": height,
        }

        name = self.measurement["name"]
        self.cancel_marking()

        self.message_var.set(
            f"{name}: {endpoint} point saved on frame "
            f"{self.frame_index + 1}."
        )

        self.changed()

    def clear_endpoint(self, endpoint):
        if self.measurement is None or self.measurement[endpoint] is None:
            return

        if messagebox.askyesno(
            "Clear point",
            f"Clear the {endpoint} point for "
            f"'{self.measurement['name']}'?",
        ):
            self.measurement[endpoint] = None
            self.cancel_marking()
            self.changed()

    def go_to_endpoint(self, endpoint):
        if self.measurement is None:
            return

        point = self.measurement[endpoint]

        if point:
            self.go_to_filename(point["filename"])

    def reference_changed(self):
        self.project["show_references"] = self.reference_var.get()
        self.draw()
        self.save_project()

    def structure_distance(self, structure):
        start = structure["start"]
        end = structure["end"]

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

        spacing_x = self.trial.get("spacing_x")
        spacing_y = self.trial.get("spacing_y")

        millimeters = None

        if spacing_x is not None and spacing_y is not None:
            millimeters = math.hypot(
                dx * spacing_x,
                dy * spacing_y,
            )

        return dx, dy, pixels, millimeters

    # ------------------------------------------------------------------
    # Comparison management
    # ------------------------------------------------------------------

    def add_comparison(self):
        self.comparison_dialog()

    def edit_comparison(self):
        if self.comparison is not None:
            self.comparison_dialog(self.comparison)

    def comparison_dialog(self, existing=None):
        if self.trial is None:
            return

        structures = self.trial["measurements"]

        if len(structures) < 2:
            messagebox.showinfo(
                "Structures required",
                "Add at least two structures first.",
            )
            return

        self.stop_playback()

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit comparison" if existing else "Add comparison")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)

        name_var = tk.StringVar(
            value=existing["name"] if existing else ""
        )

        ttk.Label(body, text="Comparison name:").pack(anchor="w")
        ttk.Entry(
            body,
            textvariable=name_var,
            width=42,
        ).pack(fill="x", pady=(0, 10))

        names = [item["name"] for item in structures]
        ids = [item["id"] for item in structures]

        ttk.Label(
            body,
            text="Structure A — anchor / origin:",
        ).pack(anchor="w")

        a_combo = ttk.Combobox(
            body,
            values=names,
            state="readonly",
        )
        a_combo.pack(fill="x", pady=(0, 8))

        ttk.Label(
            body,
            text="Structure B — line endpoint:",
        ).pack(anchor="w")

        b_combo = ttk.Combobox(
            body,
            values=names,
            state="readonly",
        )
        b_combo.pack(fill="x", pady=(0, 8))

        a_index = (
            ids.index(existing["a_id"])
            if existing and existing["a_id"] in ids else 0
        )
        b_index = (
            ids.index(existing["b_id"])
            if existing and existing["b_id"] in ids else 1
        )

        a_combo.current(a_index)
        b_combo.current(b_index)

        ttk.Label(
            body,
            text=(
                "Start line: A.start → B.start\n"
                "End line: A.end → B.end\n"
                "Each line's two points must share a frame."
            ),
            wraplength=360,
        ).pack(anchor="w", pady=8)

        def apply():
            name = name_var.get().strip()

            if (
                not name
                or len(name) > 80
                or "::" in name
                or "\n" in name
                or "\r" in name
            ):
                messagebox.showerror(
                    "Invalid name",
                    "Use 1–80 characters, without line breaks or '::'.",
                    parent=dialog,
                )
                return

            if any(
                item["name"] == name and item is not existing
                for item in self.trial["comparisons"]
            ):
                messagebox.showerror(
                    "Duplicate name",
                    "Use a unique comparison name.",
                    parent=dialog,
                )
                return

            a_id = ids[a_combo.current()]
            b_id = ids[b_combo.current()]

            if a_id == b_id:
                messagebox.showerror(
                    "Invalid comparison",
                    "Choose two different structures.",
                    parent=dialog,
                )
                return

            if existing is None:
                comparison = new_comparison(name, a_id, b_id)
                self.trial["comparisons"].append(comparison)
                self.comparison_index = (
                    len(self.trial["comparisons"]) - 1
                )
            else:
                existing.update({
                    "name": name,
                    "a_id": a_id,
                    "b_id": b_id,
                })

            dialog.destroy()
            self.changed()

        ttk.Button(
            body,
            text="Save comparison",
            command=apply,
        ).pack(fill="x", pady=8)

    def delete_comparison(self):
        comparison = self.comparison

        if comparison is None:
            return

        if messagebox.askyesno(
            "Delete comparison",
            f"Delete '{comparison['name']}'?\n"
            "The structure points will remain.",
        ):
            self.trial["comparisons"].remove(comparison)
            self.comparison_index = 0
            self.changed()

    def comparison_selected(self, _event=None):
        self.comparison_index = self.comparison_combo.current()
        self.refresh_panels()
        self.draw()

    def comparison_result(self, comparison):
        structures = {
            item["id"]: item
            for item in self.trial["measurements"]
        }

        a = structures.get(comparison["a_id"])
        b = structures.get(comparison["b_id"])

        if a is None or b is None:
            raise ValueError("A comparison references a missing structure.")

        if a["id"] == b["id"]:
            raise ValueError("A comparison needs two different structures.")

        points = [a["start"], b["start"], a["end"], b["end"]]

        if all(point is None for point in points):
            return None

        if any(point is None for point in points):
            raise ValueError(
                "Mark Start and End for both structures."
            )

        a1, b1, a2, b2 = points

        if a1["filename"] != b1["filename"]:
            raise ValueError(
                "A1 and B1 must be marked on the same frame."
            )

        if a2["filename"] != b2["filename"]:
            raise ValueError(
                "A2 and B2 must be marked on the same frame."
            )

        sizes = {
            (point["width"], point["height"])
            for point in points
        }

        if len(sizes) != 1:
            raise ValueError(
                "All four points need matching image dimensions."
            )

        if any(point["filename"] not in self.frames for point in points):
            raise ValueError("A source frame is missing.")

        pixels = geometry_from_points(a1, b1, a2, b2)
        millimeters = None

        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        if sx is not None and sy is not None:
            millimeters = geometry_from_points(
                a1, b1, a2, b2, sx, sy
            )

        return {
            "structure_a": a,
            "structure_b": b,
            "points": points,
            "px": pixels,
            "mm": millimeters,
        }

    # ------------------------------------------------------------------
    # Live results
    # ------------------------------------------------------------------

    def refresh_panels(self):
        if not self.in_main:
            return

        self.update_progress()
        self.refresh_link_combos()

        for name, label in self.mark_labels.items():
            filename = self.timestamp_filename(name)
            label.configure(
                text=Path(filename).stem if filename else "-"
            )

        structures = self.trial["measurements"] if self.trial else []
        self.measurement_combo["values"] = [
            item["name"] for item in structures
        ]

        if structures:
            self.measurement_index = max(
                0,
                min(self.measurement_index, len(structures) - 1),
            )
            self.measurement_combo.current(self.measurement_index)
        else:
            self.measurement_combo.set("")

        comparisons = self.trial["comparisons"] if self.trial else []
        self.comparison_combo["values"] = [
            item["name"] for item in comparisons
        ]

        if comparisons:
            self.comparison_index = max(
                0,
                min(self.comparison_index, len(comparisons) - 1),
            )
            self.comparison_combo.current(self.comparison_index)
        else:
            self.comparison_combo.set("")

        structure = self.measurement

        for endpoint, variable in self.point_vars.items():
            point = structure[endpoint] if structure else None

            if point is None:
                variable.set("Not marked")
            else:
                filename = point["filename"]
                index = (
                    self.frames.index(filename) + 1
                    if filename in self.frames else "missing"
                )

                variable.set(
                    f"Frame {index} | {filename}\n"
                    f"x={point['x']:.2f}, y={point['y']:.2f} px"
                )

        distance = (
            self.structure_distance(structure)
            if structure else None
        )

        if distance is not None:
            dx, dy, pixels, millimeters = distance

            text = (
                f"Structure displacement: {pixels:.3f} px\n"
                f"Δx={dx:.3f}, Δy={dy:.3f} px"
            )

            if millimeters is not None:
                text += f"\nStructure displacement: {millimeters:.3f} mm"

            self.displacement_var.set(text)

        elif structure and structure["start"] and structure["end"]:
            self.displacement_var.set(
                "Cannot calculate displacement: dimensions differ."
            )
        else:
            self.displacement_var.set(
                "Structure displacement: mark both points."
            )

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None

        self.calibration_var.set(
            f"Calibration: X={sx:g}, Y={sy:g} mm/px\n"
            "Angles are also calculated in calibrated coordinates."
            if sx is not None and sy is not None
            else "Pixels only. Set this trial's X/Y calibration in Config."
        )

        comparison = self.comparison

        if comparison is None:
            self.geometry_var.set("Add a comparison to calculate line geometry.")
            return

        try:
            result = self.comparison_result(comparison)

            if result is None:
                self.geometry_var.set(
                    "No comparison points marked yet.\n"
                    "Mark Start and End on both structures."
                )
                return

            text = [
                f"A: {result['structure_a']['name']}",
                f"B: {result['structure_b']['name']}",
                "",
            ]

            for unit in ("px", "mm"):
                values = result[unit]
                if values is None:
                    continue

                heading = (
                    "Pixel-coordinate results"
                    if unit == "px" else "Calibrated results"
                )

                text.extend([
                    heading,
                    f"L1 = {fmt(values['L1'])} {unit}",
                    f"L2 = {fmt(values['L2'])} {unit}",
                    f"a = {fmt(values['AngleA'])}°",
                    f"b = {fmt(values['AngleB'])}°",
                    f"c = {fmt(values['AngleC'])}°",
                    f"Signed rotation = {fmt(values['SignedRotation'])}°",
                    f"Opposite side = {fmt(values['OppositeSide'])} {unit}",
                    "",
                ])

            if result["px"]["AngleC"] is None:
                text.append(
                    "A zero-length line has undefined orientation."
                )

            self.geometry_var.set("\n".join(text).strip())

        except (ValueError, KeyError, TypeError) as exc:
            self.geometry_var.set(f"Comparison not ready:\n{exc}")

    # ------------------------------------------------------------------
    # Canvas rendering
    # ------------------------------------------------------------------

    def draw(self):
        if not self.in_main:
            return

        self.canvas.delete("all")
        self.transform = None

        if self.image is None or self.trial is None:
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

        scale = min(canvas_width / width, canvas_height / height)
        display_width = max(1, round(width * scale))
        display_height = max(1, round(height * scale))

        ox = (canvas_width - display_width) / 2
        oy = (canvas_height - display_height) / 2
        scale_x = display_width / width
        scale_y = display_height / height

        self.transform = (ox, oy, scale_x, scale_y)

        key = (id(self.image), display_width, display_height)

        if key != self.render_key:
            resized = self.image.resize(
                (display_width, display_height),
                Image.Resampling.LANCZOS,
            )
            self.photo = ImageTk.PhotoImage(resized)
            self.render_key = key

        self.canvas.create_image(
            ox, oy, image=self.photo, anchor="nw"
        )

        current_filename = self.frames[self.frame_index]
        show_references = self.reference_var.get()

        def visible(point):
            return (
                point is not None
                and (point["width"], point["height"]) == (width, height)
                and point["filename"] in self.frames
                and (
                    point["filename"] == current_filename
                    or show_references
                )
            )

        def position(point):
            return (
                ox + point["x"] * scale_x,
                oy + point["y"] * scale_y,
            )

        # Existing per-structure displacement line.
        structure = self.measurement

        if (
            structure
            and visible(structure["start"])
            and visible(structure["end"])
        ):
            x1, y1 = position(structure["start"])
            x2, y2 = position(structure["end"])

            self.canvas.create_line(
                x1, y1, x2, y2,
                fill="#ffff66",
                width=2,
                dash=(5, 4),
            )

        # Selected comparison: A1-B1 and A2-B2.
        comparison = self.comparison

        if comparison:
            by_id = {
                item["id"]: item
                for item in self.trial["measurements"]
            }

            a = by_id.get(comparison["a_id"])
            b = by_id.get(comparison["b_id"])

            if a and b:
                for endpoint, color, label in [
                    ("start", "#30e0ff", "L1"),
                    ("end", "#ff8c42", "L2"),
                ]:
                    p1 = a[endpoint]
                    p2 = b[endpoint]

                    if (
                        visible(p1)
                        and visible(p2)
                        and p1["filename"] == p2["filename"]
                    ):
                        x1, y1 = position(p1)
                        x2, y2 = position(p2)

                        style = {"fill": color, "width": 2}

                        if p1["filename"] != current_filename:
                            style["dash"] = (5, 3)

                        self.canvas.create_line(
                            x1, y1, x2, y2, **style
                        )
                        self.canvas.create_text(
                            (x1 + x2) / 2,
                            (y1 + y2) / 2 - 12,
                            text=f"{comparison['name']} {label}",
                            fill=color,
                            font=("Arial", 10, "bold"),
                        )

        # Solid current-frame plus signs and dashed reference plus signs.
        for item in self.trial["measurements"]:
            for endpoint, color in [
                ("start", "#30e0ff"),
                ("end", "#ff8c42"),
            ]:
                point = item[endpoint]

                if not visible(point):
                    continue

                x, y = position(point)
                current = point["filename"] == current_filename
                selected = item is structure

                arm_length = 8 if selected else 6

                style = {
                    "fill": color,
                    "width": 2 if selected else 1,
                    "capstyle": tk.BUTT,
                }

                if not current:
                    style["dash"] = (3, 2)

                self.canvas.create_line(
                    x - arm_length, y,
                    x + arm_length, y,
                    **style,
                )
                self.canvas.create_line(
                    x, y - arm_length,
                    x, y + arm_length,
                    **style,
                )

                frame_number = (
                    self.frames.index(point["filename"]) + 1
                )

                label = (
                    f"{item['name']} "
                    f"{'1' if endpoint == 'start' else '2'} "
                    f"| F{frame_number}"
                )

                if not current:
                    label += " [ref]"

                self.canvas.create_text(
                    x + 11,
                    y - 12 if endpoint == "start" else y + 12,
                    text=label,
                    fill=color,
                    anchor="w",
                    font=(
                        "Arial",
                        10,
                        "bold" if selected else "normal",
                    ),
                )

    def show_triangle(self):
        if self.comparison is None:
            return

        try:
            result = self.comparison_result(self.comparison)

            if result is None:
                raise ValueError("Mark all four points first.")

        except (ValueError, KeyError, TypeError) as exc:
            messagebox.showinfo("Triangle unavailable", str(exc))
            return

        self.stop_playback()

        unit = "mm" if result["mm"] is not None else "px"
        values = result[unit]

        window = tk.Toplevel(self.root)
        window.title(
            f"Aligned triangle — {self.comparison['name']}"
        )
        window.geometry("640x470")

        ttk.Label(
            window,
            text=(
                f"Origins aligned without rotation — {unit} coordinates\n"
                f"L1={fmt(values['L1'])}   "
                f"L2={fmt(values['L2'])}   "
                f"c={fmt(values['AngleC'])}°\n"
                f"Opposite side={fmt(values['OppositeSide'])} {unit}"
            ),
            padding=10,
            justify="center",
        ).pack(fill="x")

        canvas = tk.Canvas(
            window,
            background="#151515",
            highlightthickness=0,
        )
        canvas.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            window,
            text=(
                "This is a translated-vector diagram, not an "
                "image-registration result."
            ),
            padding=8,
        ).pack(fill="x")

        def render(_event=None):
            canvas.delete("all")

            points = [
                (0.0, 0.0),
                values["vector_1"],
                values["vector_2"],
            ]

            xs = [point[0] for point in points]
            ys = [point[1] for point in points]

            span_x = max(xs) - min(xs)
            span_y = max(ys) - min(ys)

            width = max(100, canvas.winfo_width())
            height = max(100, canvas.winfo_height())

            scale = min(
                max(1, width - 100) / max(span_x, 1e-9),
                max(1, height - 100) / max(span_y, 1e-9),
            )

            center_x = (min(xs) + max(xs)) / 2
            center_y = (min(ys) + max(ys)) / 2

            def convert(point):
                return (
                    width / 2 + (point[0] - center_x) * scale,
                    height / 2 - (point[1] - center_y) * scale,
                )

            origin, end1, end2 = [convert(point) for point in points]

            canvas.create_line(
                *origin, *end1,
                fill="#30e0ff",
                width=3,
            )
            canvas.create_line(
                *origin, *end2,
                fill="#ff8c42",
                width=3,
            )
            canvas.create_line(
                *end1, *end2,
                fill="#ffff66",
                width=2,
                dash=(5, 3),
            )

            for point, label, color in [
                (origin, "A1 = A2", "white"),
                (end1, "B1", "#30e0ff"),
                (end2, "B2 aligned", "#ff8c42"),
            ]:
                x, y = point
                canvas.create_line(
                    x - 5, y, x + 5, y, fill=color, width=2
                )
                canvas.create_line(
                    x, y - 5, x, y + 5, fill=color, width=2
                )
                canvas.create_text(
                    x, y + 17,
                    text=label,
                    fill=color,
                )

        canvas.bind("<Configure>", render)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def settings(self):
        self.stop_playback()
        self.capture_form()

        dialog = tk.Toplevel(self.root)
        dialog.title("Configuration")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)

        row_vars = []

        for index, row in enumerate(self.project["mark_rows"]):
            ttk.Label(
                body,
                text=(
                    f"Timestamp row {index + 1} "
                    f"({''.join(ROW_KEYS[index]).upper()}):"
                ),
            ).pack(anchor="w", pady=(6, 2))

            variable = tk.StringVar(value=", ".join(row))
            ttk.Entry(
                body,
                textvariable=variable,
                width=65,
            ).pack(fill="x")
            row_vars.append(variable)

        fps_var = tk.StringVar(value=str(self.project["fps"]))
        custom_var = tk.StringVar(
            value=", ".join(self.project["custom_fields"])
        )
        sort_var = tk.StringVar(value=self.project["frame_sort"])

        for label, variable in [
            ("Playback FPS:", fps_var),
            ("Custom variables, comma-separated:", custom_var),
        ]:
            ttk.Label(
                body,
                text=label,
            ).pack(anchor="w", pady=(8, 2))

            ttk.Entry(
                body,
                textvariable=variable,
            ).pack(fill="x")

        ttk.Label(
            body,
            text="Filename ordering:",
        ).pack(anchor="w", pady=(8, 2))

        ttk.Combobox(
            body,
            textvariable=sort_var,
            values=["lexicographic", "natural"],
            state="readonly",
        ).pack(fill="x")

        ttk.Label(
            body,
            text=(
                "Lexicographic retains Timestamper's ordering.\n"
                "Natural places frame_2 before frame_10."
            ),
        ).pack(anchor="w", pady=3)

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None

        sx_var = tk.StringVar(value="" if sx is None else str(sx))
        sy_var = tk.StringVar(value="" if sy is None else str(sy))

        if self.trial is not None:
            for label, variable in [
                ("This trial: X spacing, mm/pixel:", sx_var),
                ("This trial: Y spacing, mm/pixel:", sy_var),
            ]:
                ttk.Label(
                    body,
                    text=label,
                ).pack(anchor="w", pady=(8, 2))

                ttk.Entry(
                    body,
                    textvariable=variable,
                ).pack(fill="x")

            ttk.Label(
                body,
                text=(
                    "Leave BOTH blank for pixel-only results.\n"
                    "One calibration applies to all frames in this trial."
                ),
            ).pack(anchor="w", pady=5)

        def apply():
            try:
                rows = [
                    [
                        name.strip()
                        for name in variable.get().split(",")
                        if name.strip()
                    ]
                    for variable in row_vars
                ]
                custom_fields = [
                    name.strip()
                    for name in custom_var.get().split(",")
                    if name.strip()
                ]

                validate_field_names(rows, custom_fields)

                fps = float(fps_var.get())
                if not math.isfinite(fps) or not 0 < fps <= 1000:
                    raise ValueError(
                        "FPS must be greater than 0 and at most 1000."
                    )

                spacing_x = spacing_y = None

                if self.trial is not None:
                    x_text = sx_var.get().strip()
                    y_text = sy_var.get().strip()

                    if bool(x_text) != bool(y_text):
                        raise ValueError(
                            "Provide both spacing values or leave both blank."
                        )

                    if x_text:
                        spacing_x = float(x_text)
                        spacing_y = float(y_text)

                        if not all(
                            math.isfinite(value) and value > 0
                            for value in (spacing_x, spacing_y)
                        ):
                            raise ValueError(
                                "Spacing values must be positive finite numbers."
                            )

                remaining_names = {
                    name for row in rows for name in row
                }

                removed_links = [
                    (trial, endpoint)
                    for trial in self.project["trials"].values()
                    for endpoint, name in trial["frame_links"].items()
                    if name and name not in remaining_names
                ]

                if removed_links:
                    if not messagebox.askyesno(
                        "Removed timestamp categories",
                        "Some saved trials link points to categories "
                        "that you are removing.\n\n"
                        "Those links will become Manual. Existing point "
                        "coordinates will be retained.\nContinue?",
                        parent=dialog,
                    ):
                        return

            except ValueError as exc:
                messagebox.showerror(
                    "Invalid configuration",
                    str(exc),
                    parent=dialog,
                )
                return

            self.capture_form()

            for trial, endpoint in removed_links:
                trial["frame_links"][endpoint] = ""
                trial["status"] = "draft"

            self.project["mark_rows"] = rows
            self.project["custom_fields"] = custom_fields
            self.project["fps"] = fps
            self.project["frame_sort"] = sort_var.get()

            if self.trial is not None:
                self.trial["spacing_x"] = spacing_x
                self.trial["spacing_y"] = spacing_y
                self.trial["status"] = "draft"

            self.build_timestamp_ui()
            self.rebuild_custom_fields()

            # Store changes before refreshing trial/frame ordering.
            if not self.save_project():
                return

            dialog.destroy()
            self.refresh_trials()

        ttk.Button(
            body,
            text="Apply",
            command=apply,
        ).pack(fill="x", pady=(14, 0))

    # ------------------------------------------------------------------
    # Validation and combined CSV
    # ------------------------------------------------------------------

    def validate_point(self, point, size_cache):
        filename = point.get("filename")

        if filename not in self.frames:
            raise ValueError(f"Missing source frame: {filename}")

        x = point.get("x")
        y = point.get("y")

        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError(f"Invalid point coordinates: {filename}")

        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"Nonfinite point coordinates: {filename}")

        expected = (point.get("width"), point.get("height"))

        if filename not in size_cache:
            with Image.open(Path(self.trial_key) / filename) as source:
                size_cache[filename] = source.size

        if size_cache[filename] != expected:
            raise ValueError(
                f"Source dimensions changed: {filename}\n"
                "Please re-mark points on this frame."
            )

        width, height = size_cache[filename]

        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"Point lies outside the image: {filename}")

    def validate_trial_for_export(self):
        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        if (sx is None) != (sy is None):
            raise ValueError("Both calibration values are required.")

        if sx is not None:
            if not all(
                isinstance(value, (int, float))
                and math.isfinite(value)
                and value > 0
                for value in (sx, sy)
            ):
                raise ValueError("Invalid calibration. Check Config.")

        for name in self.timestamp_names():
            filename = self.timestamp_filename(name)
            if filename is not None and filename not in self.frames:
                raise ValueError(
                    f"Timestamp '{name}' references a missing frame."
                )

        size_cache = {}

        for structure in self.trial["measurements"]:
            start = structure["start"]
            end = structure["end"]

            # Untouched structures do not prevent timestamp-only submission.
            if start is None and end is None:
                continue

            if start is None or end is None:
                raise ValueError(
                    f"'{structure['name']}' has only one point.\n"
                    "Complete it, clear it, or delete the structure "
                    "before submitting."
                )

            for endpoint in ("start", "end"):
                point = structure[endpoint]
                self.validate_point(point, size_cache)

                linked_name = self.trial["frame_links"].get(endpoint, "")

                if linked_name:
                    linked_filename = self.timestamp_filename(linked_name)

                    if linked_filename != point["filename"]:
                        raise ValueError(
                            f"'{structure['name']}' {endpoint} does not match "
                            f"linked timestamp '{linked_name}'.\n"
                            "Re-mark it or switch the frame selection to Manual."
                        )

            if self.structure_distance(structure) is None:
                raise ValueError(
                    f"'{structure['name']}': Start and End image "
                    "dimensions differ."
                )

        for comparison in self.trial["comparisons"]:
            try:
                self.comparison_result(comparison)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(
                    f"Comparison '{comparison['name']}': {exc}\n"
                    "Complete/correct the comparison or delete it."
                ) from exc

    def export_row(self):
        self.validate_trial_for_export()

        # Preserve the original Timestamper columns and stored timestamp values.
        row = {
            "Trial": Path(self.trial_key).name,
            "RecordTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for name in self.timestamp_names():
            filename = self.timestamp_filename(name)
            row[name] = Path(filename).stem if filename else "nil"

        for name in self.project["custom_fields"]:
            value = self.trial.get("custom", {}).get(name, "")
            row[name] = str(value).strip() or "nil"

        row["Remarks"] = self.trial.get("remarks", "").strip() or "nil"

        row.update({
            "Project": self.project["name"],
            "SourceFolder": self.trial_key,
            "SpacingX_mm_per_px": self.trial.get("spacing_x"),
            "SpacingY_mm_per_px": self.trial.get("spacing_y"),
        })

        # Additional timestamp metadata.
        for name in self.timestamp_names():
            filename = self.timestamp_filename(name)
            prefix = f"Timestamp::{name}::"

            row[prefix + "Filename"] = filename
            row[prefix + "FrameIndex"] = (
                self.frames.index(filename) + 1
                if filename in self.frames else None
            )

        # Original point-marker information, flattened into trial columns.
        for structure in self.trial["measurements"]:
            prefix = f"Point::{structure['name']}::"

            row[prefix + "MeasurementID"] = structure["id"]

            for endpoint, label in [
                ("start", "Start"),
                ("end", "End"),
            ]:
                point = structure[endpoint]

                row[prefix + label + "Filename"] = (
                    point["filename"] if point else None
                )
                row[prefix + label + "FrameIndex"] = (
                    self.frames.index(point["filename"]) + 1
                    if point else None
                )
                row[prefix + label + "X_px"] = point["x"] if point else None
                row[prefix + label + "Y_px"] = point["y"] if point else None
                row[prefix + label + "ImageWidth_px"] = (
                    point["width"] if point else None
                )
                row[prefix + label + "ImageHeight_px"] = (
                    point["height"] if point else None
                )
                row[prefix + label + "TimestampLink"] = (
                    self.trial["frame_links"].get(endpoint, "")
                )

            distance = self.structure_distance(structure)

            row[prefix + "DeltaX_px"] = distance[0] if distance else None
            row[prefix + "DeltaY_px"] = distance[1] if distance else None
            row[prefix + "Distance_px"] = distance[2] if distance else None
            row[prefix + "Distance_mm"] = distance[3] if distance else None

        # New paired-line geometry.
        structures = {
            item["id"]: item
            for item in self.trial["measurements"]
        }

        for comparison in self.trial["comparisons"]:
            prefix = f"Comparison::{comparison['name']}::"
            result = self.comparison_result(comparison)

            a = structures[comparison["a_id"]]
            b = structures[comparison["b_id"]]

            row[prefix + "ComparisonID"] = comparison["id"]
            row[prefix + "StructureA"] = a["name"]
            row[prefix + "StructureB"] = b["name"]
            row[prefix + "StructureA_ID"] = a["id"]
            row[prefix + "StructureB_ID"] = b["id"]

            row[prefix + "Status"] = (
                "not_marked" if result is None
                else (
                    "zero_length_line_angle_undefined"
                    if result["px"]["AngleC"] is None
                    else "complete"
                )
            )

            for endpoint, label in [
                ("start", "Start"),
                ("end", "End"),
            ]:
                point = a[endpoint] if result else None

                row[prefix + label + "Filename"] = (
                    point["filename"] if point else None
                )
                row[prefix + label + "FrameIndex"] = (
                    self.frames.index(point["filename"]) + 1
                    if point else None
                )

            for unit in ("px", "mm"):
                values = result[unit] if result else None

                for key in ("L1", "L2", "OppositeSide"):
                    row[prefix + f"{key}_{unit}"] = (
                        values[key] if values else None
                    )

                for key in (
                    "AngleA",
                    "AngleB",
                    "AngleC",
                    "SignedRotation",
                ):
                    row[prefix + f"{key}_{unit}_deg"] = (
                        values[key] if values else None
                    )

        return row

    def append_csv_row(self, path, row):
        """
        Append a submission while preserving existing rows.

        If new fields appear, expand the header and leave those fields blank
        in older rows. A one-time backup is made before expanding a header.
        """
        path = Path(path)
        previous_rows = []
        columns = []

        if path.exists() and path.stat().st_size > 0:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames or []

                if not columns:
                    raise ValueError("The existing CSV has no header.")

                if (
                    any(not column for column in columns)
                    or len(columns) != len(set(columns))
                ):
                    raise ValueError(
                        "The existing CSV has empty or duplicate column names."
                    )

                previous_rows = list(reader)

                if any(None in previous for previous in previous_rows):
                    raise ValueError(
                        "An existing CSV row has more values than its header.\n"
                        "Select a new output CSV or repair that file first."
                    )

        added = [column for column in row if column not in columns]

        if columns and added:
            backup_once(path, ".before_merge.bak")

        columns.extend(added)

        def write(handle):
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(previous_rows)
            writer.writerow(row)

        atomic_write(path, write)

    def submit(self):
        self.stop_playback()
        self.cancel_marking()

        if self.trial is None:
            return

        if not self.project["csv_path"]:
            self.select_csv()

            if not self.project["csv_path"]:
                return

        if not self.save_project():
            return

        try:
            row = self.export_row()
            self.append_csv_row(
                self.project["csv_path"],
                row,
            )

        except Exception as exc:
            messagebox.showerror(
                "Submit failed",
                str(exc),
                parent=self.root,
            )
            return

        self.trial["status"] = "submitted"
        self.update_progress()

        # The CSV has already been written successfully at this point.
        if not self.save_project():
            messagebox.showwarning(
                "CSV saved",
                "The CSV row was saved, but project saving failed.\n"
                "Do not submit again merely to retry the project save; "
                "that would append another CSV row.",
            )
            return

        self.advance_trial()

    def skip_trial(self):
        if self.trial is None:
            return

        self.stop_playback()
        self.cancel_marking()

        if messagebox.askyesno(
            "Skip trial",
            "Move to the next trial without CSV export?\n"
            "Timestamps, points, and observations remain saved as a draft.",
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
                "Use the trial selector to revisit a trial.\n\n"
                "Submitting a trial again appends another CSV row.",
            )

    # ------------------------------------------------------------------
    # Keyboard and close
    # ------------------------------------------------------------------

    def is_typing(self):
        focus = self.root.focus_get()

        return isinstance(
            focus,
            (
                tk.Entry,
                ttk.Entry,
                tk.Text,
                ttk.Combobox,
                tk.Spinbox,
                ttk.Spinbox,
            ),
        )

    def handle_key(self, event):
        if not self.in_main:
            return

        if self.root.grab_current() is not None:
            return

        focus = self.root.focus_get()

        if focus is not None and focus.winfo_toplevel() != self.root:
            return

        if self.is_typing():
            return

        # Leave Ctrl/Alt combinations available for normal text/UI shortcuts.
        if event.state & 0x0004 or event.state & 0x0008:
            return

        key = event.keysym.lower()

        if key == "escape":
            self.cancel_marking()
            self.message_var.set("Marking canceled.")
            return "break"

        common = {
            "left": lambda: self.step(-1),
            "right": lambda: self.step(1),
            "space": self.toggle_playback,
            "return": self.submit,
        }

        if key in common:
            common[key]()
            return "break"

        if self.point_tab_active():
            if key == "s":
                self.arm("start")
                return "break"
            if key == "e":
                self.arm("end")
                return "break"

        else:
            character = event.char.lower()

            for row_index, keys in enumerate(ROW_KEYS):
                if character in keys:
                    column_index = keys.index(character)
                    categories = self.project["mark_rows"][row_index]

                    if column_index < len(categories):
                        self.set_mark(categories[column_index])
                        return "break"

    def close(self):
        self.stop_playback()

        if self.save_project():
            self.cancel_pending_save()
            self.in_main = False
            self.root.destroy()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_geometry_self_tests()
    else:
        root = tk.Tk()
        app = UltrasoundAnnotator(root)
        root.mainloop()