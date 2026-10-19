import copy
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
APP_VERSION = 3

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

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
    "DecisionID",
    "DecisionRevision",
}

COLUMN_PREFIXES = ("Timestamp::", "Point::", "Comparison::")
MANUAL_FRAME_LABEL = "Manual — current frame"

HISTORY_FIELDS = {
    "decisions",
    "mark_history",
    "active_decision_id",
}


# ----------------------------------------------------------------------
# General helpers
# ----------------------------------------------------------------------

def natural_key(value):
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(value))
    ]


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write(path, writer):
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


def timestamped_backup(path, label="before_overwrite"):
    path = Path(path)

    if not path.exists():
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = path.with_name(f"{path.name}.{label}.{stamp}.bak")
    shutil.copy2(path, backup)
    return backup


def same_folder(left, right):
    if not left or not right:
        return False

    try:
        return os.path.normcase(str(Path(left).resolve())) == (
            os.path.normcase(str(Path(right).resolve()))
        )
    except (OSError, ValueError):
        return False


def new_structure(name):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "start": None,
        "end": None,
    }


def new_comparison(name, a_id, b_id):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "a_id": a_id,
        "b_id": b_id,
    }


def new_trial():
    a = new_structure("Structure A")
    b = new_structure("Structure B")

    return {
        "measurements": [a, b],
        "comparisons": [new_comparison("A-B", a["id"], b["id"])],
        "marks": {},
        "mark_history": {},
        "decisions": [],
        "active_decision_id": "",
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
        "show_lines": True,
        "show_points": True,
        "submission_mode": "append",
        "advance_after_submit": True,
        "frame_sort": "lexicographic",
        "trials": {},
    }


def validate_field_names(mark_rows, custom_fields):
    if not isinstance(mark_rows, list) or len(mark_rows) != 4:
        raise ValueError("Exactly four timestamp category rows are required.")

    if not isinstance(custom_fields, list):
        raise ValueError("Custom fields must be a list.")

    for index, names in enumerate(mark_rows):
        if not isinstance(names, list):
            raise ValueError("Each timestamp row must be a list.")

        if len(names) > len(ROW_KEYS[index]):
            raise ValueError(
                f"Timestamp row {index + 1} supports at most "
                f"{len(ROW_KEYS[index])} categories."
            )

    names = [name for row in mark_rows for name in row] + custom_fields

    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("Field names must be nonempty text.")

    if len(names) != len(set(names)):
        raise ValueError("Timestamp and custom-field names must be unique.")

    for name in names:
        if name in RESERVED_COLUMNS or name.startswith(COLUMN_PREFIXES):
            raise ValueError(f"'{name}' conflicts with a reserved CSV column.")
        if "\n" in name or "\r" in name:
            raise ValueError("Field names cannot contain line breaks.")


def normalize_trial(trial):
    if not isinstance(trial, dict):
        raise ValueError("Invalid trial record.")

    defaults = new_trial()
    defaults["measurements"] = []
    defaults["comparisons"] = []

    for key, value in defaults.items():
        trial.setdefault(key, copy.deepcopy(value))

    for key in ("marks", "mark_history", "frame_links", "custom"):
        if not isinstance(trial[key], dict):
            raise ValueError(f"Invalid trial field: {key}")

    for key in ("measurements", "comparisons", "decisions"):
        if not isinstance(trial[key], list):
            raise ValueError(f"Invalid trial field: {key}")

    trial["frame_links"].setdefault("start", "")
    trial["frame_links"].setdefault("end", "")

    ids = set()
    names = set()

    for structure in trial["measurements"]:
        structure.setdefault("id", uuid.uuid4().hex)
        structure.setdefault("start", None)
        structure.setdefault("end", None)

        if not structure.get("name"):
            raise ValueError("A saved structure has no name.")

        if structure["id"] in ids or structure["name"] in names:
            raise ValueError("Duplicate structure name or ID.")

        ids.add(structure["id"])
        names.add(structure["name"])

    ids = set()
    names = set()

    for comparison in trial["comparisons"]:
        comparison.setdefault("id", uuid.uuid4().hex)

        if not comparison.get("name"):
            raise ValueError("A saved comparison has no name.")

        if comparison["id"] in ids or comparison["name"] in names:
            raise ValueError("Duplicate comparison name or ID.")

        ids.add(comparison["id"])
        names.add(comparison["name"])

    for name, history in trial["mark_history"].items():
        if not isinstance(history, list):
            raise ValueError(f"Invalid timestamp history for '{name}'.")

    return trial


def normalize_project(raw, name):
    if not isinstance(raw, dict):
        raise ValueError("The project file must contain a JSON object.")

    application = raw.get("application")

    if application not in (None, APP_ID, "WorkSmartPointMarker"):
        raise ValueError("Unsupported project format.")

    if application == APP_ID and raw.get("version") not in (2, 3):
        raise ValueError("Unsupported integrated project version.")

    if application == "WorkSmartPointMarker" and raw.get("version") != 1:
        raise ValueError("Unsupported point-marker project version.")

    project = new_project(name)
    project.update(copy.deepcopy(raw))
    project["application"] = APP_ID
    project["version"] = APP_VERSION
    project["name"] = name

    if application == "WorkSmartPointMarker":
        project["frame_sort"] = raw.get("frame_sort", "natural")

    rows = project.get("mark_rows", [])

    if not isinstance(rows, list) or len(rows) > 4:
        raise ValueError("Invalid timestamp category rows.")

    rows += [[] for _ in range(4 - len(rows))]
    project["mark_rows"] = rows
    validate_field_names(rows, project["custom_fields"])

    fps = float(project.get("fps", 30))
    if not math.isfinite(fps) or not 0 < fps <= 1000:
        raise ValueError("FPS must be greater than 0 and at most 1000.")
    project["fps"] = fps

    if project["frame_sort"] not in ("lexicographic", "natural"):
        project["frame_sort"] = "lexicographic"

    if project["submission_mode"] not in ("append", "overwrite"):
        project["submission_mode"] = "append"

    trials = project.get("trials", {})
    if not isinstance(trials, dict):
        raise ValueError("Invalid trial data.")

    project["trials"] = {
        str(Path(key).resolve()): normalize_trial(trial)
        for key, trial in trials.items()
    }

    if project.get("current_trial"):
        project["current_trial"] = str(
            Path(project["current_trial"]).resolve()
        )

    return project


def decision_snapshot(trial):
    return copy.deepcopy({
        key: value
        for key, value in trial.items()
        if key not in HISTORY_FIELDS
    })


def fmt(value, digits=3):
    return "undefined" if value is None else f"{value:.{digits}f}"


def remember_trial_mark(trial, name, mark):
    """History helper usable for both visible and staged import trials."""
    if not isinstance(mark, dict):
        return

    history = trial["mark_history"].setdefault(name, [])

    if history and history[-1].get("mark") == mark:
        return

    history.append({
        "id": uuid.uuid4().hex,
        "saved_at": now_text(),
        "mark": copy.deepcopy(mark),
    })


def append_trial_snapshot(trial, mode, record_id="", revision=None, **metadata):
    entry = {
        "id": uuid.uuid4().hex,
        "record_id": record_id,
        "revision": revision,
        "saved_at": now_text(),
        "mode": mode,
        "snapshot": decision_snapshot(trial),
    }
    entry.update(metadata)
    trial["decisions"].append(entry)
    return entry


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------

def line_geometry(vector_1, vector_2):
    x1, y1 = vector_1
    x2, y2 = vector_2

    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        raise ValueError("Geometry contains a nonfinite coordinate.")

    length_1 = math.hypot(x1, y1)
    length_2 = math.hypot(x2, y2)

    angle_a = math.degrees(math.atan2(y1, x1)) if length_1 else None
    angle_b = math.degrees(math.atan2(y2, x2)) if length_2 else None

    signed_rotation = None
    angle_c = None

    if length_1 and length_2:
        ux1, uy1 = x1 / length_1, y1 / length_1
        ux2, uy2 = x2 / length_2, y2 / length_2

        signed_rotation = math.degrees(math.atan2(
            ux1 * uy2 - uy1 * ux2,
            ux1 * ux2 + uy1 * uy2,
        ))
        angle_c = abs(signed_rotation)

    return {
        "L1": length_1,
        "L2": length_2,
        "AngleA": angle_a,
        "AngleB": angle_b,
        "AngleC": angle_c,
        "SignedRotation": signed_rotation,
        "OppositeSide": math.hypot(x2 - x1, y2 - y1),
        "vector_1": vector_1,
        "vector_2": vector_2,
    }


def geometry_from_points(a1, b1, a2, b2, spacing_x=1.0, spacing_y=1.0):
    return line_geometry(
        (
            (b1["x"] - a1["x"]) * spacing_x,
            -(b1["y"] - a1["y"]) * spacing_y,
        ),
        (
            (b2["x"] - a2["x"]) * spacing_x,
            -(b2["y"] - a2["y"]) * spacing_y,
        ),
    )


def run_geometry_self_tests():
    result = line_geometry((10.0, 0.0), (0.0, 10.0))
    assert math.isclose(result["L1"], 10.0)
    assert math.isclose(result["L2"], 10.0)
    assert math.isclose(result["AngleA"], 0.0)
    assert math.isclose(result["AngleB"], 90.0)
    assert math.isclose(result["AngleC"], 90.0)
    assert math.isclose(result["OppositeSide"], math.sqrt(200.0))

    result = line_geometry((3.0, 4.0), (3.0, 4.0))
    assert math.isclose(result["AngleC"], 0.0, abs_tol=1e-12)
    assert math.isclose(result["OppositeSide"], 0.0, abs_tol=1e-12)

    def vector(angle):
        radians = math.radians(angle)
        return math.cos(radians), math.sin(radians)

    result = line_geometry(vector(170), vector(-170))
    assert math.isclose(result["SignedRotation"], 20.0, abs_tol=1e-10)

    result = line_geometry((0.0, 0.0), (3.0, 4.0))
    assert result["AngleA"] is None
    assert result["AngleC"] is None
    assert math.isclose(result["OppositeSide"], 5.0)

    a = {"x": 0.0, "y": 0.0}
    b = {"x": 1.0, "y": -1.0}
    result = geometry_from_points(a, b, a, b, 2.0, 1.0)
    assert math.isclose(
        result["AngleA"], math.degrees(math.atan2(1.0, 2.0))
    )

    print("Geometry self-tests passed.")


# ----------------------------------------------------------------------
# CSV helpers
# ----------------------------------------------------------------------

def read_csv_table(path):
    path = Path(path)

    if not path.exists() or path.stat().st_size == 0:
        return [], []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []

        if not columns:
            raise ValueError("The existing CSV has no header.")

        if any(not c for c in columns) or len(columns) != len(set(columns)):
            raise ValueError("The CSV has empty or duplicate column names.")

        rows = list(reader)

    if any(None in row for row in rows):
        raise ValueError("A CSV row has more values than its header.")

    return columns, rows


def write_csv_table(path, columns, rows):
    def write(handle):
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    atomic_write(path, write)


def legacy_csv_value(value):
    """
    Old exporter used literal 'nil' for missing values.

    Do not convert numeric-looking strings: '00012' is a filename stem.
    """
    if value is None or not str(value).strip() or value == "nil":
        return ""
    return str(value)


def read_legacy_csv(path, encoding="utf-8-sig"):
    with Path(path).open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames or []

        if not columns:
            raise ValueError("The CSV has no header.")

        if any(not c.strip() for c in columns):
            raise ValueError("The CSV contains an empty column name.")

        if len(columns) != len(set(columns)):
            raise ValueError(
                "The CSV contains duplicate column names.\n"
                "The original exporter cannot distinguish duplicate fields."
            )

        if (
            len(columns) < 3
            or columns[:2] != ["Trial", "RecordTime"]
            or columns[-1] != "Remarks"
        ):
            raise ValueError(
                "Expected the original Timestamper CSV layout:\n"
                "Trial,RecordTime,<timestamps>,<custom variables>,Remarks\n\n"
                "This importer is for the old CSV, not a combined export."
            )

        records = []

        for row_number, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"CSV data row {row_number} has the wrong number of values.\n"
                    "Its header may not match the settings used to export it."
                )

            if all(row[column] == column for column in columns):
                raise ValueError(
                    f"CSV data row {row_number} repeats the header.\n"
                    "Remove the repeated header before importing."
                )

            if not row["Trial"].strip():
                raise ValueError(
                    f"CSV data row {row_number} has no trial name."
                )

            records.append({
                "row_number": row_number,
                "row": row,
            })

    if not records:
        raise ValueError("The CSV has no data rows.")

    return columns, records


def legacy_mark_from_stem(value, frames):
    if not value:
        return None

    # The old application used PNG files exclusively.
    matches = [
        name for name in frames
        if Path(name).suffix.lower() == ".png"
        and Path(name).stem == value
    ]

    if not matches:
        matches = [
            name for name in frames
            if Path(name).stem == value
        ]

    filename = matches[0] if len(matches) == 1 else None

    return {
        "filename": filename,
        "frame_index": frames.index(filename) + 1 if filename else None,
        "value": value,
        "legacy_unresolved": filename is None,
    }


def mark_identity(mark):
    """Compare active values, ignoring history/provenance metadata."""
    if not mark:
        return None

    if isinstance(mark, str):
        return ("value", mark)

    filename = mark.get("filename")
    if filename:
        return ("filename", filename)

    value = mark.get("value")
    return ("value", value) if value else None


def mark_display(mark):
    if not mark:
        return "(empty)"
    if isinstance(mark, str):
        return mark
    return (
        mark.get("filename")
        or f"{mark.get('value', '')} [missing / unresolved]"
    )


def trial_has_work(trial):
    return bool(
        any(trial["marks"].values())
        or any(str(value or "").strip() for value in trial["custom"].values())
        or str(trial.get("remarks") or "").strip()
        or any(
            item.get("start") or item.get("end")
            for item in trial["measurements"]
        )
        or any(trial["frame_links"].values())
        or trial.get("spacing_x") is not None
        or trial.get("spacing_y") is not None
        or trial["decisions"]
        or any(trial["mark_history"].values())
    )


# ----------------------------------------------------------------------
# GUI
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

    @property
    def trial(self):
        if self.project is None or self.trial_key is None:
            return None
        return self.project["trials"].get(self.trial_key)

    @property
    def measurement(self):
        items = self.trial["measurements"] if self.trial else []
        if 0 <= self.measurement_index < len(items):
            return items[self.measurement_index]
        return None

    @property
    def comparison(self):
        items = self.trial["comparisons"] if self.trial else []
        if 0 <= self.comparison_index < len(items):
            return items[self.comparison_index]
        return None

    def timestamp_names(self):
        return [name for row in self.project["mark_rows"] for name in row]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def capture_form(self):
        if not self.in_main or self.loading_form or self.trial is None:
            return

        self.trial["remarks"] = self.remarks_var.get()
        self.trial["custom"].update({
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

        # Keep typed entries in the trial immediately, even before autosave.
        self.capture_form()
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
    # Project menu
    # ------------------------------------------------------------------

    def show_menu(self):
        self.clear_ui()
        self.root.minsize(540, 380)
        self.root.geometry("720x490")

        body = ttk.Frame(self.root, padding=24)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="WorkSmart", font=("Arial", 23, "bold")
        ).pack(pady=8)

        ttk.Label(
            body,
            text="Timestamps + Point Marking + Decision History",
        ).pack(pady=(0, 18))

        box = ttk.LabelFrame(body, text="Create project", padding=12)
        box.pack(fill="x", pady=6)

        self.new_project_var = tk.StringVar()

        ttk.Entry(box, textvariable=self.new_project_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ttk.Button(
            box, text="Create", command=self.create_project
        ).pack(side="right")

        box = ttk.LabelFrame(body, text="Load project", padding=12)
        box.pack(fill="x", pady=6)

        names = sorted(
            [path.stem for path in self.projects_dir.glob("*.json")],
            key=natural_key,
        )

        self.project_combo = ttk.Combobox(
            box, values=names, state="readonly"
        )
        self.project_combo.pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )

        if names:
            self.project_combo.current(0)

        ttk.Button(
            box, text="Launch", command=self.load_project
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
                "Older project files are backed up before migration."
            ),
            wraplength=650,
        ).pack(anchor="w", pady=8)

    @staticmethod
    def valid_project_name(name):
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", name))

    def create_project(self):
        name = self.new_project_var.get().strip()

        if not self.valid_project_name(name):
            messagebox.showerror(
                "Project name",
                "Use 1–80 letters, numbers, spaces, underscores, or hyphens.\n"
                "Start with a letter or number.",
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

            if (
                raw.get("application") != APP_ID
                or raw.get("version") != APP_VERSION
            ):
                backup_once(path, ".before_v3.bak")

            if raw.get("application") == "WorkSmartPointMarker":
                project["csv_path"] = ""

            self.project = project
            self.project_path = path
            self.setup_main_ui()
            self.refresh_trials()

        except Exception as exc:
            messagebox.showerror("Load failed", str(exc), parent=self.root)

    def import_project(self):
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Import project JSON",
            filetypes=[("JSON project", "*.json")],
        )
        if not filename:
            return

        try:
            source = Path(filename)
            with source.open(encoding="utf-8-sig") as handle:
                raw = json.load(handle)

            suggested = re.sub(r"[^A-Za-z0-9 _-]", "_", source.stem).strip()
            if not suggested or not suggested[0].isalnum():
                suggested = "ImportedProject"

            name = simpledialog.askstring(
                "Imported project",
                "New project name:",
                initialvalue=suggested[:65] + "_merged",
                parent=self.root,
            )
            if name is None:
                return

            name = name.strip()
            if not self.valid_project_name(name):
                raise ValueError("Invalid project name.")

            destination = self.projects_dir / f"{name}.json"
            if destination.exists():
                raise ValueError("That project already exists.")

            project = normalize_project(raw, name)
            if raw.get("application") == "WorkSmartPointMarker":
                project["csv_path"] = ""

            atomic_write(
                destination,
                lambda handle: json.dump(
                    project, handle, indent=2,
                    ensure_ascii=False, allow_nan=False,
                ),
            )

            self.project = project
            self.project_path = destination
            self.setup_main_ui()
            self.refresh_trials()

        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))

    def return_to_menu(self):
        self.stop_playback()
        if self.save_project():
            self.show_menu()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def button_row(self, parent, buttons):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)

        for column, (text, command) in enumerate(buttons):
            row.columnconfigure(column, weight=1, uniform="buttons")
            ttk.Button(
                row, text=text, command=command, width=1
            ).grid(row=0, column=column, sticky="ew", padx=2)

        return row

    def setup_main_ui(self):
        self.clear_ui()
        self.loading_form = True

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1450, max(850, screen_width - 70))
        height = min(940, max(600, screen_height - 100))

        self.root.minsize(850, 600)
        self.root.geometry(f"{width}x{height}")

        header = ttk.Frame(self.root, padding=8)
        header.pack(fill="x")

        ttk.Label(
            header,
            text=f"PROJECT: {self.project['name']}",
            font=("Arial", 11, "bold"),
        ).pack(side="left")

        ttk.Button(
            header, text="Config", command=self.settings
        ).pack(side="left", padx=12)

        ttk.Button(
            header, text="Menu", command=self.return_to_menu
        ).pack(side="right")

        ttk.Button(
            header, text="Save Project", command=self.save_project
        ).pack(side="right", padx=8)

        self.paths_var = tk.StringVar()
        ttk.Label(
            self.root,
            textvariable=self.paths_var,
            padding=(8, 2),
            wraplength=max(700, width - 50),
        ).pack(fill="x")

        panes = tk.PanedWindow(
            self.root, orient="horizontal",
            sashwidth=7, sashrelief="raised",
        )
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes)
        outer = ttk.Frame(panes, width=470)

        panes.add(left, minsize=300, stretch="always")
        panes.add(outer, minsize=410, width=470, stretch="never")

        self.canvas = tk.Canvas(
            left, background="black", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.canvas.bind("<Button-1>", self.canvas_click)

        navigation = ttk.Frame(left, padding=8)
        navigation.pack(fill="x")

        self.play_button = ttk.Button(
            navigation, text="Play", width=6,
            command=self.toggle_playback,
        )
        self.play_button.pack(side="left")

        for text, amount in [("<", -1), (">", 1)]:
            ttk.Button(
                navigation, text=text, width=3,
                command=lambda n=amount: self.step(n),
            ).pack(side="left", padx=2)

        self.slider = tk.Scale(
            navigation,
            from_=1, to=1,
            orient="horizontal",
            showvalue=False,
            resolution=1,
            command=self.slider_changed,
        )
        self.slider.pack(side="left", fill="x", expand=True, padx=6)

        self.goto_var = tk.StringVar(value="1")
        ttk.Entry(
            navigation, width=6, textvariable=self.goto_var
        ).pack(side="left")

        ttk.Button(
            navigation, text="Go", width=4, command=self.go_to_number
        ).pack(side="left", padx=4)

        self.frame_var = tk.StringVar(value="No frame loaded")
        self.message_var = tk.StringVar(value="Select a parent folder.")

        ttk.Label(
            left, textvariable=self.frame_var, padding=(8, 2),
            wraplength=650,
        ).pack(fill="x")

        ttk.Label(
            left, textvariable=self.message_var,
            padding=8, wraplength=650,
        ).pack(fill="x")

        self.sidebar_canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            outer, orient="vertical", command=self.sidebar_canvas.yview
        )
        scrollbar.pack(side="right", fill="y")

        self.sidebar_canvas.configure(yscrollcommand=scrollbar.set)
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)

        self.sidebar = ttk.Frame(self.sidebar_canvas, padding=8)
        window = self.sidebar_canvas.create_window(
            (0, 0), window=self.sidebar, anchor="nw"
        )

        self.sidebar.bind(
            "<Configure>",
            lambda _event: self.sidebar_canvas.configure(
                scrollregion=self.sidebar_canvas.bbox("all")
            ),
        )
        self.sidebar_canvas.bind(
            "<Configure>",
            lambda event: self.sidebar_canvas.itemconfigure(
                window, width=event.width
            ),
        )

        self.button_row(self.sidebar, [
            ("Parent Folder", self.select_parent),
            ("Output CSV", self.select_csv),
        ])

        ttk.Button(
            self.sidebar,
            text="Import Old CSV...",
            command=self.import_old_csv,
        ).pack(fill="x", pady=(2, 6))

        ttk.Label(self.sidebar, text="Trial:").pack(anchor="w")
        self.trial_combo = ttk.Combobox(self.sidebar, state="readonly")
        self.trial_combo.pack(fill="x")
        self.trial_combo.bind("<<ComboboxSelected>>", self.trial_selected)

        self.button_row(self.sidebar, [
            ("Previous trial", lambda: self.move_trial(-1)),
            ("Next trial", lambda: self.move_trial(1)),
        ])

        self.progress_var = tk.StringVar()
        ttk.Label(
            self.sidebar, textvariable=self.progress_var, wraplength=395
        ).pack(anchor="w", pady=4)

        visibility_box = ttk.LabelFrame(
            self.sidebar, text="Image visibility", padding=7
        )
        visibility_box.pack(fill="x", pady=5)

        self.show_lines_var = tk.BooleanVar(
            value=self.project["show_lines"]
        )
        self.show_points_var = tk.BooleanVar(
            value=self.project["show_points"]
        )
        self.reference_var = tk.BooleanVar(
            value=self.project["show_references"]
        )

        for text, variable in [
            ("Show lines and line labels", self.show_lines_var),
            ("Show annotated points and point labels", self.show_points_var),
            ("Show references from other frames", self.reference_var),
        ]:
            ttk.Checkbutton(
                visibility_box,
                text=text,
                variable=variable,
                command=self.reference_changed,
            ).pack(anchor="w", pady=2)

        self.notebook = ttk.Notebook(self.sidebar)
        self.notebook.pack(fill="x", pady=7)

        self.timestamp_tab = ttk.Frame(self.notebook, padding=6)
        self.point_tab = ttk.Frame(self.notebook, padding=6)

        self.notebook.add(self.timestamp_tab, text="Timestamps")
        self.notebook.add(self.point_tab, text="Point Marking")
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)

        self.timestamp_container = ttk.Frame(self.timestamp_tab)
        self.timestamp_container.pack(fill="x")

        self.build_timestamp_ui()
        self.build_point_ui()

        self.custom_box = ttk.LabelFrame(
            self.sidebar, text="Custom Variables", padding=8
        )
        self.custom_box.pack(fill="x", pady=6)
        self.rebuild_custom_fields()

        ttk.Label(self.sidebar, text="Observations:").pack(anchor="w")
        self.remarks_var = tk.StringVar()
        self.remarks_var.trace_add("write", self.form_changed)

        ttk.Entry(
            self.sidebar, textvariable=self.remarks_var
        ).pack(fill="x", pady=5)

        history_box = ttk.LabelFrame(
            self.sidebar, text="Decision history", padding=7
        )
        history_box.pack(fill="x", pady=6)

        self.decision_var = tk.StringVar()
        ttk.Label(
            history_box, textvariable=self.decision_var, wraplength=375
        ).pack(anchor="w")

        ttk.Button(
            history_box,
            text="Recall saved decision...",
            command=self.show_decision_history,
        ).pack(fill="x", pady=4)

        export_box = ttk.LabelFrame(
            self.sidebar, text="Submit / update CSV", padding=7
        )
        export_box.pack(fill="x", pady=6)

        self.submit_mode_var = tk.StringVar(
            value=self.project["submission_mode"]
        )
        self.advance_var = tk.BooleanVar(
            value=self.project["advance_after_submit"]
        )

        ttk.Radiobutton(
            export_box,
            text="Append — create a new decision row",
            variable=self.submit_mode_var,
            value="append",
            command=self.export_preferences_changed,
        ).pack(anchor="w")

        ttk.Radiobutton(
            export_box,
            text="Overwrite — update recalled / latest matching row",
            variable=self.submit_mode_var,
            value="overwrite",
            command=self.export_preferences_changed,
        ).pack(anchor="w")

        ttk.Checkbutton(
            export_box,
            text="Go to next trial after successful submission",
            variable=self.advance_var,
            command=self.export_preferences_changed,
        ).pack(anchor="w", pady=4)

        self.button_row(export_box, [
            ("Skip — keep draft", self.skip_trial),
            ("Submit / Update", self.submit),
        ])

        ttk.Label(
            self.sidebar,
            text=(
                "Timestamps: configured category hotkeys\n"
                "Point Marking: S = start, E = end\n"
                "Space = play/pause | Left/Right = step\n"
                "Enter = submit | Escape = cancel marking\n\n"
                "Solid + = current frame; dashed + = reference.\n"
                "Hiding annotations does not delete data.\n"
                "Timestamp and decision history are saved in the project."
            ),
            wraplength=385,
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
            ).pack(anchor="w", pady=(7, 3))

            for column_index, name in enumerate(names):
                key = ROW_KEYS[row_index][column_index]

                box = ttk.LabelFrame(
                    self.timestamp_container,
                    text=f"{name}  [{key.upper()}]",
                    padding=5,
                )
                box.pack(fill="x", pady=3)

                label = ttk.Label(
                    box, text="Not marked", wraplength=335, justify="left"
                )
                label.pack(fill="x", pady=(0, 3))
                self.mark_labels[name] = label

                self.button_row(box, [
                    ("Set", lambda n=name: self.set_mark(n)),
                    ("Go", lambda n=name: self.go_to_mark(n)),
                    ("Clear", lambda n=name: self.clear_mark(n)),
                ])

        ttk.Button(
            self.timestamp_container,
            text="Recall previous timestamp frames...",
            command=self.show_timestamp_history,
        ).pack(fill="x", pady=(10, 4))

        ttk.Label(
            self.timestamp_container,
            text=(
                "Set marks the current frame. Go opens the active mark.\n"
                "Clear removes the active mark, but keeps its history.\n"
                "History can open or restore earlier marked frames."
            ),
            wraplength=345,
        ).pack(anchor="w", pady=7)

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
                lambda _event, e=endpoint: self.link_changed(e),
            )
            self.link_combos[endpoint] = combo

        ttk.Label(
            link_box,
            text=(
                "Links apply to all structures in this trial. "
                "Set opens the linked timestamp frame."
            ),
            wraplength=330,
        ).pack(anchor="w")

        structure_box = ttk.LabelFrame(
            self.point_tab, text="Structures", padding=7
        )
        structure_box.pack(fill="x", pady=5)

        self.measurement_combo = ttk.Combobox(
            structure_box, state="readonly"
        )
        self.measurement_combo.pack(fill="x")
        self.measurement_combo.bind(
            "<<ComboboxSelected>>", self.measurement_selected
        )

        self.button_row(structure_box, [
            ("Add", self.add_structure),
            ("Rename", self.rename_structure),
            ("Delete", self.delete_structure),
        ])

        self.point_vars = {}

        for endpoint, label in [
            ("start", "Start point — A1 / B1"),
            ("end", "End point — A2 / B2"),
        ]:
            box = ttk.LabelFrame(structure_box, text=label, padding=5)
            box.pack(fill="x", pady=3)

            variable = tk.StringVar(value="Not marked")
            self.point_vars[endpoint] = variable
            ttk.Label(
                box, textvariable=variable, wraplength=315
            ).pack(anchor="w")

            self.button_row(box, [
                ("Set", lambda e=endpoint: self.arm(e)),
                ("Go to", lambda e=endpoint: self.go_to_endpoint(e)),
                ("Clear", lambda e=endpoint: self.clear_endpoint(e)),
            ])

        self.displacement_var = tk.StringVar()
        ttk.Label(
            structure_box,
            textvariable=self.displacement_var,
            wraplength=325,
        ).pack(anchor="w", pady=5)

        comparison_box = ttk.LabelFrame(
            self.point_tab, text="Line comparisons", padding=7
        )
        comparison_box.pack(fill="x", pady=5)

        self.comparison_combo = ttk.Combobox(
            comparison_box, state="readonly"
        )
        self.comparison_combo.pack(fill="x")
        self.comparison_combo.bind(
            "<<ComboboxSelected>>", self.comparison_selected
        )

        self.button_row(comparison_box, [
            ("Add", self.add_comparison),
            ("Edit", self.edit_comparison),
            ("Delete", self.delete_comparison),
        ])

        self.geometry_var = tk.StringVar()
        ttk.Label(
            comparison_box,
            textvariable=self.geometry_var,
            wraplength=325,
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
            wraplength=335,
        ).pack(anchor="w", pady=6)

    def rebuild_custom_fields(self):
        previous = self.loading_form
        self.loading_form = True

        for widget in self.custom_box.winfo_children():
            widget.destroy()

        self.custom_vars = {}
        values = self.trial["custom"] if self.trial else {}

        for name in self.project["custom_fields"]:
            ttk.Label(self.custom_box, text=name).pack(anchor="w")
            variable = tk.StringVar(value=values.get(name, ""))
            variable.trace_add("write", self.form_changed)
            ttk.Entry(
                self.custom_box, textvariable=variable
            ).pack(fill="x", pady=(0, 5))
            self.custom_vars[name] = variable

        self.loading_form = previous

    def populate_form(self):
        previous = self.loading_form
        self.loading_form = True

        self.remarks_var.set(
            self.trial.get("remarks", "") if self.trial else ""
        )

        for name, variable in self.custom_vars.items():
            variable.set(
                self.trial["custom"].get(name, "") if self.trial else ""
            )

        self.loading_form = previous

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
            amount = -int(delta / 120) or (-1 if delta > 0 else 1)

        self.sidebar_canvas.yview_scroll(amount, "units")
        return "break"

    def tab_changed(self, _event=None):
        if not self.in_main:
            return
        self.cancel_marking()
        self.message_var.set(
            "Point Marking: choose a structure; S = Start, E = End."
            if self.point_tab_active()
            else "Timestamps: category hotkeys mark the current frame."
        )

    def point_tab_active(self):
        return self.notebook.select() == str(self.point_tab)

    def reference_changed(self):
        self.project["show_references"] = self.reference_var.get()
        self.project["show_lines"] = self.show_lines_var.get()
        self.project["show_points"] = self.show_points_var.get()
        self.draw()
        self.save_project()

    def export_preferences_changed(self):
        self.project["submission_mode"] = self.submit_mode_var.get()
        self.project["advance_after_submit"] = self.advance_var.get()
        self.save_project()

    def update_paths(self):
        self.paths_var.set(
            f"Source: {self.project['parent_folder'] or '(not selected)'}\n"
            f"CSV: {self.project['csv_path'] or '(not selected)'}"
        )

    # ------------------------------------------------------------------
    # Trials / frames
    # ------------------------------------------------------------------

    def image_names(self, folder):
        names = [
            path.name for path in Path(folder).iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and not path.name.startswith((".", "~"))
        ]
        return sorted(
            names,
            key=natural_key if self.project["frame_sort"] == "natural" else None,
        )

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
            title="Select combined output CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )

        if filename:
            self.project["csv_path"] = str(Path(filename).resolve())
            self.update_paths()
            self.save_project()

    def refresh_trials(self):
        self.stop_playback()

        # Save the outgoing form BEFORE clearing the trial reference.
        # Refreshing or changing sort order must not discard pending drafts.
        if self.trial is not None and not self.save_project():
            return

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
                candidates = [p for p in Path(folder).iterdir() if p.is_dir()]
                key = (
                    (lambda p: natural_key(p.name))
                    if self.project["frame_sort"] == "natural"
                    else (lambda p: p.name)
                )
                self.trial_paths = [
                    str(path.resolve())
                    for path in sorted(candidates, key=key)
                    if self.image_names(path)
                ]
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
                index = max(
                    0,
                    min(
                        int(self.project.get("last_trial_idx", 0)),
                        len(self.trial_paths) - 1,
                    ),
                )

            self.load_trial(index, save_previous=False)
        else:
            self.trial_combo.set("")
            self.populate_form()
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

    def move_trial(self, amount):
        if self.trial_key in self.trial_paths:
            self.load_trial(self.trial_paths.index(self.trial_key) + amount)

    def load_trial(self, index, save_previous=True):
        self.stop_playback()

        if not 0 <= index < len(self.trial_paths):
            return

        # Every navigation path saves the outgoing working trial.
        # If saving fails, do not leave that trial.
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
                raise ValueError("This trial contains no image files.")
        except Exception as exc:
            messagebox.showerror("Trial error", str(exc))
            if self.trial_key in self.trial_paths:
                self.trial_combo.current(
                    self.trial_paths.index(self.trial_key)
                )
            return

        self.cancel_pending_save()
        self.cancel_marking()

        self.trial_key = key
        self.project["current_trial"] = key
        self.project["last_trial_idx"] = index

        # Never reset an existing trial when revisiting it.
        self.project["trials"].setdefault(key, new_trial())

        self.frames = frames
        self.frame_index = -1
        self.image = None
        self.render_key = None
        self.measurement_index = 0
        self.comparison_index = 0
        self.trial_combo.current(index)

        for name, mark in list(self.trial["marks"].items()):
            if isinstance(mark, str):
                matches = [
                    filename for filename in frames
                    if filename == mark or Path(filename).stem == mark
                ]
                self.trial["marks"][name] = {
                    "filename": matches[0] if len(matches) == 1 else None,
                    "value": mark,
                    "legacy_unresolved": len(matches) != 1,
                }

            self.remember_mark(name, self.trial["marks"].get(name))

        self.populate_form()
        self.slider.configure(to=max(1, len(frames)))

        previous = self.trial.get("last_frame")
        self.show_frame(frames.index(previous) if previous in frames else 0)

        self.refresh_panels()
        self.message_var.set(
            "Mark timestamps or points. Use history to recall earlier decisions."
        )
        self.save_project()

    def update_progress(self):
        if self.trial is None:
            self.progress_var.set("No trials loaded")
            return

        index = self.trial_paths.index(self.trial_key)
        self.progress_var.set(
            f"Trial {index + 1}/{len(self.trial_paths)}"
            f" | {self.trial.get('status', 'draft')}"
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
            with Image.open(Path(self.trial_key) / self.frames[index]) as source:
                self.image = source.convert("RGB")
        except Exception as exc:
            self.stop_playback()
            self.message_var.set(f"Cannot open {self.frames[index]}: {exc}")

        self.slider.set(index + 1)
        self.goto_var.set(str(index + 1))
        self.frame_var.set(
            f"Frame {index + 1}/{len(self.frames)} | {self.frames[index]}"
        )
        self.trial["last_frame"] = self.frames[index]
        self.draw()
        self.save_soon()

    def slider_changed(self, value):
        if self.in_main and self.frames:
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
                "Frame number", f"Enter a number from 1 to {len(self.frames)}."
            )
            return

        self.stop_playback()
        self.show_frame(number - 1)
        self.canvas.focus_set()

    def go_to_filename(self, filename):
        if filename not in self.frames:
            messagebox.showerror(
                "Missing frame",
                f"Source frame is unavailable or unresolved:\n{filename}",
                parent=self.root,
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
            max(1, round(1000 / self.project["fps"])), self.play_tick
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
            max(1, round(1000 / self.project["fps"])), self.play_tick
        )

    # ------------------------------------------------------------------
    # Timestamps and timestamp history
    # ------------------------------------------------------------------

    def timestamp_filename(self, name):
        if self.trial is None:
            return None
        mark = self.trial["marks"].get(name)
        return mark.get("filename") if isinstance(mark, dict) else None

    def remember_mark(self, name, mark):
        if self.trial is not None:
            remember_trial_mark(self.trial, name, mark)

    def confirm_linked_point_changes(self, endpoints, filename):
        affected = [
            (structure, endpoint)
            for structure in self.trial["measurements"]
            for endpoint in endpoints
            if structure.get(endpoint)
            and structure[endpoint]["filename"] != filename
        ]

        if affected:
            if not messagebox.askyesno(
                "Linked frame changed",
                f"{len(affected)} linked point(s) belong to a different frame.\n"
                "They must be cleared and marked again.\n\nContinue?",
                parent=self.root,
            ):
                return False

            for structure, endpoint in affected:
                structure[endpoint] = None

        return True

    def apply_mark(self, name, mark):
        filename = mark.get("filename")
        if filename not in self.frames:
            messagebox.showerror(
                "Missing frame",
                "This timestamp frame is missing or unresolved.",
                parent=self.root,
            )
            return False

        endpoints = [
            endpoint
            for endpoint, linked_name in self.trial["frame_links"].items()
            if linked_name == name
        ]

        if not self.confirm_linked_point_changes(endpoints, filename):
            return False

        self.remember_mark(name, self.trial["marks"].get(name))

        restored = copy.deepcopy(mark)
        restored["filename"] = filename
        restored["frame_index"] = self.frames.index(filename) + 1
        restored["value"] = Path(filename).stem
        restored.pop("legacy_unresolved", None)

        self.trial["marks"][name] = restored
        self.remember_mark(name, restored)
        self.cancel_marking()
        self.changed()
        return True

    def set_mark(self, name):
        if self.trial is None or self.image is None:
            return

        self.stop_playback()
        filename = self.frames[self.frame_index]

        if self.apply_mark(name, {
            "filename": filename,
            "frame_index": self.frame_index + 1,
            "value": Path(filename).stem,
        }):
            self.message_var.set(f"Timestamp '{name}' set to {filename}.")

    def clear_mark(self, name):
        if self.trial is None or not self.trial["marks"].get(name):
            return

        self.stop_playback()

        if not messagebox.askyesno(
            "Clear timestamp",
            f"Clear active timestamp '{name}'?\n"
            "Its previous frame will remain in timestamp history.",
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

        self.remember_mark(name, self.trial["marks"][name])
        self.trial["marks"][name] = None
        self.cancel_marking()
        self.changed()

    def go_to_mark(self, name):
        filename = self.timestamp_filename(name)
        if filename is None:
            messagebox.showinfo(
                "Timestamp unavailable",
                f"Mark '{name}' first, or restore a frame from history.",
                parent=self.root,
            )
            return
        self.go_to_filename(filename)

    def show_timestamp_history(self):
        if self.trial is None:
            return

        self.stop_playback()

        for name, mark in self.trial["marks"].items():
            self.remember_mark(name, mark)

        records = []
        for name, entries in self.trial["mark_history"].items():
            for entry in entries:
                mark = entry.get("mark")
                if isinstance(mark, dict):
                    records.append((name, entry))

        if not records:
            messagebox.showinfo(
                "Timestamp history", "No timestamp history exists yet."
            )
            return

        records.sort(
            key=lambda item: item[1].get("saved_at", ""), reverse=True
        )

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Timestamp history — {Path(self.trial_key).name}")
        dialog.geometry("850x450")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=(
                "Go opens an old frame without changing the active mark.\n"
                "Restore makes it the active timestamp again."
            ),
        ).pack(anchor="w", pady=(0, 8))

        table_box = ttk.Frame(body)
        table_box.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            table_box,
            columns=("category", "frame", "saved", "status"),
            show="headings",
            selectmode="browse",
        )

        for column, title, width in [
            ("category", "Category", 130),
            ("frame", "Filename / value", 260),
            ("saved", "Recorded", 200),
            ("status", "Status", 100),
        ]:
            tree.heading(column, text=title)
            tree.column(column, width=width, minwidth=70)

        scroll = ttk.Scrollbar(table_box, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        for index, (name, entry) in enumerate(records):
            mark = entry["mark"]
            filename = mark.get("filename")
            active = self.timestamp_filename(name) == filename and filename
            status = "Active" if active else "Previous"
            if filename not in self.frames:
                status = "Missing"

            tree.insert("", "end", iid=str(index), values=(
                name,
                filename or mark.get("value", "(unresolved)"),
                entry.get("saved_at", ""),
                status,
            ))

        def selected():
            selection = tree.selection()
            return records[int(selection[0])] if selection else None

        def go():
            item = selected()
            if item:
                self.go_to_filename(item[1]["mark"].get("filename"))

        def restore():
            item = selected()
            if not item:
                return

            name, entry = item

            if name not in self.timestamp_names():
                messagebox.showinfo(
                    "Category not configured",
                    f"Add '{name}' back in Config before restoring it.",
                    parent=dialog,
                )
                return

            if not messagebox.askyesno(
                "Restore timestamp",
                f"Restore '{name}' to:\n"
                f"{entry['mark'].get('filename')}\n\n"
                "This updates the draft, not the CSV.",
                parent=dialog,
            ):
                return

            if self.apply_mark(name, entry["mark"]):
                self.go_to_filename(entry["mark"]["filename"])
                dialog.destroy()

        tree.bind("<Double-1>", lambda _event: go())
        self.button_row(body, [
            ("Go to frame", go),
            ("Restore active mark", restore),
            ("Close", dialog.destroy),
        ])

    # ------------------------------------------------------------------
    # Decision history
    # ------------------------------------------------------------------

    def add_decision_history(self, mode, record_id="", revision=None):
        self.capture_form()
        return append_trial_snapshot(
            self.trial, mode, record_id, revision
        )

    def show_decision_history(self):
        if self.trial is None:
            return

        self.stop_playback()

        if not self.trial["decisions"]:
            messagebox.showinfo(
                "Decision history",
                "No decision snapshots exist yet.\n\n"
                "Submitting stores a snapshot. Your current saved marks "
                "can already be recalled using Go or timestamp history.",
            )
            return

        entries = list(reversed(self.trial["decisions"]))

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Decision history — {Path(self.trial_key).name}")
        dialog.geometry("900x480")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=(
                "Restore loads timestamps, points, links, calibration, and notes.\n"
                "It does not modify the CSV until you submit. "
                "Your current draft is preserved as a snapshot."
            ),
            wraplength=850,
        ).pack(anchor="w", pady=(0, 8))

        table_box = ttk.Frame(body)
        table_box.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            table_box,
            columns=("saved", "mode", "revision", "record", "marks"),
            show="headings",
            selectmode="browse",
        )

        for column, title, width in [
            ("saved", "Recorded", 190),
            ("mode", "Action", 120),
            ("revision", "Revision", 65),
            ("record", "Decision ID", 120),
            ("marks", "Timestamps", 300),
        ]:
            tree.heading(column, text=title)
            tree.column(column, width=width, minwidth=50)

        scroll = ttk.Scrollbar(table_box, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        for index, entry in enumerate(entries):
            marks = entry.get("snapshot", {}).get("marks", {})
            summary = ", ".join(
                f"{name}={mark.get('value') or mark.get('filename')}"
                for name, mark in marks.items()
                if isinstance(mark, dict)
            )

            tree.insert("", "end", iid=str(index), values=(
                entry.get("saved_at", ""),
                entry.get("mode", ""),
                entry.get("revision") or "",
                (entry.get("record_id") or "")[:12],
                summary,
            ))

        def restore():
            selection = tree.selection()
            if not selection:
                return

            entry = entries[int(selection[0])]

            if not messagebox.askyesno(
                "Recall decision",
                "Load this decision into the current draft?\n\n"
                "The current draft will be retained in history.\n"
                "The CSV will not change yet.",
                parent=dialog,
            ):
                return

            try:
                restored = normalize_trial(
                    copy.deepcopy(entry["snapshot"])
                )
            except Exception as exc:
                messagebox.showerror(
                    "Restore failed", str(exc), parent=dialog
                )
                return

            self.capture_form()

            for name, mark in self.trial["marks"].items():
                self.remember_mark(name, mark)

            self.add_decision_history(
                "draft-before-recall",
                self.trial.get("active_decision_id", ""),
            )

            old = self.trial
            restored["mark_history"] = old["mark_history"]
            restored["decisions"] = old["decisions"]
            restored["active_decision_id"] = entry.get("record_id", "")
            restored["status"] = "draft"

            self.project["trials"][self.trial_key] = restored

            for name, mark in restored["marks"].items():
                self.remember_mark(name, mark)

            self.cancel_marking()
            self.measurement_index = 0
            self.comparison_index = 0
            self.populate_form()

            filename = restored.get("last_frame")

            if filename not in self.frames:
                filename = next(
                    (
                        mark.get("filename")
                        for mark in restored["marks"].values()
                        if isinstance(mark, dict)
                        and mark.get("filename") in self.frames
                    ),
                    None,
                )

            if filename in self.frames:
                self.show_frame(self.frames.index(filename))

            self.advance_var.set(False)
            self.project["advance_after_submit"] = False
            self.refresh_panels()
            self.draw()
            self.save_project()
            dialog.destroy()

            self.message_var.set(
                "Decision recalled. Edit it, then choose Append or Overwrite "
                "and submit. CSV has not changed."
            )

        tree.bind("<Double-1>", lambda _event: restore())
        self.button_row(body, [
            ("Restore selected decision", restore),
            ("Close", dialog.destroy),
        ])

    # ------------------------------------------------------------------
    # Legacy CSV import
    # ------------------------------------------------------------------

    def import_choice_dialog(self, title, explanation, choices):
        """
        choices: [(label, detail_text, return_value), ...]

        No option is selected automatically.
        Closing the dialog or Cancel returns None.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)

        width = min(900, max(600, self.root.winfo_screenwidth() - 100))
        height = min(650, max(420, self.root.winfo_screenheight() - 140))
        dialog.geometry(f"{width}x{height}")

        result = {"value": None}

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=explanation,
            wraplength=width - 50,
            justify="left",
        ).pack(fill="x", pady=(0, 10))

        list_box = ttk.Frame(body)
        list_box.pack(fill="x")

        tree = ttk.Treeview(
            list_box,
            columns=("choice",),
            show="headings",
            selectmode="browse",
            height=min(7, max(3, len(choices))),
        )
        tree.heading("choice", text="Choose an option")
        tree.column("choice", width=width - 80, minwidth=200)

        list_scroll = ttk.Scrollbar(
            list_box, orient="vertical", command=tree.yview
        )
        tree.configure(yscrollcommand=list_scroll.set)
        list_scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        for index, (label, _detail, _value) in enumerate(choices):
            tree.insert("", "end", iid=str(index), values=(label,))

        detail_box = ttk.LabelFrame(body, text="Details", padding=5)
        detail_box.pack(fill="both", expand=True, pady=10)

        detail_scroll = ttk.Scrollbar(detail_box, orient="vertical")
        detail_scroll.pack(side="right", fill="y")

        detail = tk.Text(
            detail_box,
            wrap="word",
            height=10,
            state="disabled",
            yscrollcommand=detail_scroll.set,
        )
        detail.pack(fill="both", expand=True)
        detail_scroll.configure(command=detail.yview)

        footer = ttk.Frame(body)
        footer.pack(fill="x")

        def selection_changed(_event=None):
            selection = tree.selection()
            if not selection:
                return

            index = int(selection[0])
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("1.0", choices[index][1])
            detail.configure(state="disabled")
            use_button.configure(state="normal")

        def accept():
            selection = tree.selection()
            if not selection:
                return
            result["value"] = choices[int(selection[0])][2]
            dialog.destroy()

        use_button = ttk.Button(
            footer, text="Use selected option", command=accept,
            state="disabled",
        )
        use_button.pack(side="left", fill="x", expand=True, padx=(0, 5))

        ttk.Button(
            footer, text="Cancel import", command=dialog.destroy
        ).pack(side="left", fill="x", expand=True)

        tree.bind("<<TreeviewSelect>>", selection_changed)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["value"]

    def import_column_mapping(self, staged, columns, records):
        """
        Existing configured field names determine known column types.
        Unknown columns require explicit classification.
        """
        timestamp_names = {
            name for row in staged["mark_rows"] for name in row
        }
        custom_names = set(staged["custom_fields"])
        mapping = {}
        ignored = []

        for column in columns[2:-1]:
            if column in timestamp_names:
                mapping[column] = "mark"
                continue

            if column in custom_names:
                mapping[column] = "custom"
                continue

            samples = []
            for record in records:
                value = legacy_csv_value(record["row"][column])
                if value and value not in samples:
                    samples.append(value)
                if len(samples) >= 6:
                    break

            details = (
                f"CSV column: {column}\n\n"
                "The old CSV does not identify timestamps versus custom "
                "variables. Choose the correct type.\n\n"
                "Sample values:\n"
                + ("\n".join(repr(value) for value in samples) or "(all empty)")
            )

            choices = []

            permitted = (
                column not in RESERVED_COLUMNS
                and not column.startswith(COLUMN_PREFIXES)
                and "\n" not in column
                and "\r" not in column
            )

            if permitted:
                for index, row in enumerate(staged["mark_rows"]):
                    if len(row) < len(ROW_KEYS[index]):
                        choices.append((
                            f"Timestamp — add to category row {index + 1}",
                            details + (
                                "\n\nValues will be interpreted as image "
                                "filename stems, not frame indices."
                            ),
                            f"mark:{index}",
                        ))

                choices.append((
                    "Custom variable",
                    details + "\n\nValues will be preserved as text.",
                    "custom",
                ))

            choices.append((
                "Ignore this CSV column",
                details + (
                    "\n\nThis column will not be imported."
                    + (
                        "\nIts name conflicts with a reserved application "
                        "column. Rename it in a COPY of the source CSV "
                        "if it needs to be imported."
                        if not permitted else ""
                    )
                ),
                "ignore",
            ))

            choice = self.import_choice_dialog(
                "Classify CSV column",
                f"How should '{column}' be imported?",
                choices,
            )

            if choice is None:
                return None

            if choice == "ignore":
                ignored.append(column)
            elif choice == "custom":
                staged["custom_fields"].append(column)
                custom_names.add(column)
                mapping[column] = "custom"
            else:
                row_index = int(choice.split(":")[1])
                staged["mark_rows"][row_index].append(column)
                timestamp_names.add(column)
                mapping[column] = "mark"

        validate_field_names(staged["mark_rows"], staged["custom_fields"])
        return mapping, ignored

    @staticmethod
    def imported_row_details(record, mapping):
        row = record["row"]
        lines = [
            f"CSV data row: {record['row_number']}",
            f"Trial: {row['Trial']}",
            f"Original RecordTime: {row['RecordTime']}",
            "",
        ]

        for name, kind in mapping.items():
            value = legacy_csv_value(row[name])
            lines.append(
                f"{'Timestamp' if kind == 'mark' else 'Custom'} "
                f"{name}: {value if value else '(empty / nil)'}"
            )

        lines.extend([
            "",
            "Remarks: " + (
                legacy_csv_value(row["Remarks"]) or "(empty / nil)"
            ),
        ])
        return "\n".join(lines)

    @staticmethod
    def import_differences(trial, incoming):
        differences = []

        for name, mark in incoming["marks"].items():
            old = trial["marks"].get(name)
            if mark_identity(old) != mark_identity(mark):
                differences.append((
                    "mark", name, old, mark,
                ))

        for name, value in incoming["custom"].items():
            old = trial["custom"].get(name, "")
            if old != value:
                differences.append(("custom", name, old, value))

        old = trial.get("remarks", "")
        if old != incoming["remarks"]:
            differences.append((
                "remarks", "Remarks", old, incoming["remarks"],
            ))

        return differences

    @staticmethod
    def import_difference_details(differences):
        lines = []
        for kind, name, old, new in differences:
            if kind == "mark":
                old_text = mark_display(old)
                new_text = mark_display(new)
            else:
                old_text = repr(old) if old else "(empty)"
                new_text = repr(new) if new else "(empty)"

            lines.extend([
                name,
                f"  Existing: {old_text}",
                f"  CSV:      {new_text}",
                "",
            ])
        return "\n".join(lines)

    def import_old_csv(self):
        if not self.in_main or not self.trial_paths:
            messagebox.showinfo(
                "Load trials first",
                "Select the parent folder containing the trial image folders "
                "before importing the old CSV.",
                parent=self.root,
            )
            return

        self.stop_playback()
        self.cancel_marking()

        # Capture the visible draft and persist it before any import dialogs.
        if not self.save_project():
            return

        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Import CSV from the original Timestamper",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return

        source = Path(filename).resolve()

        try:
            try:
                columns, records = read_legacy_csv(source)
            except UnicodeDecodeError:
                encoding = simpledialog.askstring(
                    "CSV encoding",
                    "This CSV is not UTF-8.\n"
                    "Enter its original text encoding, for example cp1252.\n\n"
                    "Cancel leaves the project unchanged.",
                    initialvalue="cp1252",
                    parent=self.root,
                )
                if encoding is None:
                    return
                columns, records = read_legacy_csv(
                    source, encoding=encoding.strip()
                )

            # All import changes happen on this copy.
            staged = copy.deepcopy(self.project)

            by_name = {}
            for path in self.trial_paths:
                by_name.setdefault(Path(path).name, []).append(path)

            grouped = {}
            unmatched = []

            for record in records:
                trial_name = record["row"]["Trial"]
                if trial_name not in by_name:
                    unmatched.append(record)
                else:
                    grouped.setdefault(trial_name, []).append(record)

            if not grouped:
                raise ValueError(
                    "No CSV trial names match the loaded trial folders.\n\n"
                    "Matching uses the exact folder name, not the full path.\n"
                    "Check that the correct parent folder is selected."
                )

            mapping_result = self.import_column_mapping(
                staged, columns, records
            )
            if mapping_result is None:
                return

            mapping, ignored = mapping_result

            changed_names = []
            kept_names = []
            identical_names = []
            skipped_names = []
            unresolved = []
            report = []

            for trial_name, candidates in grouped.items():
                paths = by_name[trial_name]

                if len(paths) == 1:
                    key = paths[0]
                else:
                    choice = self.import_choice_dialog(
                        "Ambiguous trial folder",
                        f"Choose the destination folder for '{trial_name}'.",
                        [
                            (path, path, path)
                            for path in paths
                        ] + [
                            (
                                "Skip this trial",
                                "Do not import this trial.",
                                "__skip__",
                            )
                        ],
                    )
                    if choice is None:
                        return
                    if choice == "__skip__":
                        skipped_names.append(trial_name)
                        continue
                    key = choice

                # Group semantically identical rows; RecordTime alone does
                # not make two annotation decisions conflict.
                unique = {}
                compared_columns = list(mapping) + ["Remarks"]

                for record in candidates:
                    signature = tuple(
                        legacy_csv_value(record["row"][name])
                        for name in compared_columns
                    )
                    unique.setdefault(signature, []).append(record)

                groups = list(unique.values())

                if len(groups) > 1:
                    options = []

                    for index, equivalent in enumerate(groups):
                        representative = equivalent[-1]
                        numbers = ", ".join(
                            str(item["row_number"]) for item in equivalent
                        )
                        options.append((
                            f"Use CSV data row(s) {numbers} — "
                            f"{representative['row']['RecordTime']}",
                            self.imported_row_details(
                                representative, mapping
                            ) + (
                                "\n\nEquivalent annotation rows: " + numbers
                            ),
                            index,
                        ))

                    options.append((
                        "Skip this trial",
                        "Keep the project's existing trial unchanged.",
                        "__skip__",
                    ))

                    selected = self.import_choice_dialog(
                        "Conflicting CSV submissions",
                        f"'{trial_name}' has different annotation rows in "
                        "the CSV. Choose which row to use.",
                        options,
                    )
                    if selected is None:
                        return
                    if selected == "__skip__":
                        skipped_names.append(trial_name)
                        continue

                    record = groups[selected][-1]
                else:
                    # Annotation values are identical; retain all original
                    # rows as provenance when an import is committed.
                    record = groups[0][-1]

                frames = self.image_names(key)
                original = staged["trials"].get(key)
                working = (
                    copy.deepcopy(original)
                    if original is not None else new_trial()
                )

                # Normalize older string marks for accurate comparisons.
                for name, mark in list(working["marks"].items()):
                    if isinstance(mark, str):
                        working["marks"][name] = legacy_mark_from_stem(
                            legacy_csv_value(mark), frames
                        )

                row = record["row"]
                incoming = {
                    "marks": {},
                    "custom": {},
                    "remarks": legacy_csv_value(row["Remarks"]),
                }

                for name, kind in mapping.items():
                    value = legacy_csv_value(row[name])
                    if kind == "mark":
                        incoming["marks"][name] = legacy_mark_from_stem(
                            value, frames
                        )
                    else:
                        incoming["custom"][name] = value

                differences = self.import_differences(working, incoming)

                if not differences:
                    identical_names.append(trial_name)
                    continue

                if trial_has_work(working):
                    detail = self.import_difference_details(differences)
                    status = working.get("status", "draft")

                    choice = self.import_choice_dialog(
                        "Existing trial entries",
                        f"'{trial_name}' already has entries "
                        f"(status: {status}). Choose what to keep.\n"
                        "The project has saved any pending form edits; "
                        "unsubmitted entries are still drafts.",
                        [
                            (
                                "Keep existing entries — skip this trial",
                                detail + (
                                    "\nKeep all current trial entries. "
                                    "No CSV values will be applied to it."
                                ),
                                "keep",
                            ),
                            (
                                "Use selected CSV row",
                                detail + (
                                    "\nReplace only fields represented by "
                                    "the imported CSV columns and Remarks.\n"
                                    "CSV nil/empty values clear those fields.\n"
                                    "Other fields and point data are retained "
                                    "unless a linked-point conflict is "
                                    "separately approved.\n\n"
                                    "The previous working trial will be "
                                    "preserved in decision history."
                                ),
                                "csv",
                            ),
                            (
                                "Choose existing or CSV for each changed field",
                                detail + (
                                    "\nReview each differing timestamp, "
                                    "custom variable, and Remarks separately."
                                ),
                                "fields",
                            ),
                        ],
                    )

                    if choice is None:
                        return
                    if choice == "keep":
                        kept_names.append(trial_name)
                        continue

                    if choice == "fields":
                        selected_differences = []

                        for difference in differences:
                            kind, name, old, new = difference
                            detail = self.import_difference_details(
                                [difference]
                            )
                            field_choice = self.import_choice_dialog(
                                "Choose field value",
                                f"Trial: {trial_name}\nField: {name}",
                                [
                                    (
                                        "Keep existing value",
                                        detail,
                                        "existing",
                                    ),
                                    (
                                        "Use CSV value",
                                        detail,
                                        "csv",
                                    ),
                                ],
                            )
                            if field_choice is None:
                                return
                            if field_choice == "csv":
                                selected_differences.append(difference)

                        differences = selected_differences

                if not differences:
                    kept_names.append(trial_name)
                    continue

                # Preserve the complete outgoing state before changing
                # any marks, notes, or linked points.
                for name, mark in working["marks"].items():
                    remember_trial_mark(working, name, mark)

                append_trial_snapshot(
                    working,
                    "draft-before-csv-import",
                    working.get("active_decision_id", ""),
                )

                applied = []

                for kind, name, old, new in differences:
                    if kind == "mark":
                        new_filename = (
                            new.get("filename") if isinstance(new, dict)
                            else None
                        )

                        linked_endpoints = [
                            endpoint
                            for endpoint, linked_name
                            in working["frame_links"].items()
                            if linked_name == name
                        ]

                        affected = [
                            (structure, endpoint)
                            for structure in working["measurements"]
                            for endpoint in linked_endpoints
                            if structure.get(endpoint)
                            and structure[endpoint]["filename"] != new_filename
                        ]

                        if affected:
                            detail = (
                                f"Trial: {trial_name}\n"
                                f"Timestamp: {name}\n"
                                f"Existing: {mark_display(old)}\n"
                                f"CSV: {mark_display(new)}\n\n"
                                "Affected points:\n"
                                + "\n".join(
                                    f"{structure['name']} — {endpoint}"
                                    for structure, endpoint in affected
                                )
                            )

                            action = self.import_choice_dialog(
                                "Linked-point conflict",
                                "Changing this timestamp conflicts with "
                                "existing linked point coordinates.",
                                [
                                    (
                                        "Keep existing timestamp and points",
                                        detail,
                                        "keep",
                                    ),
                                    (
                                        "Use CSV timestamp and clear affected points",
                                        detail + (
                                            "\n\nOnly the listed points will "
                                            "be cleared. Re-mark them on the "
                                            "new linked frame.\n"
                                            "The old complete trial remains "
                                            "available in decision history."
                                        ),
                                        "clear",
                                    ),
                                ],
                            )

                            if action is None:
                                return
                            if action == "keep":
                                continue

                            for structure, endpoint in affected:
                                structure[endpoint] = None

                        working["marks"][name] = copy.deepcopy(new)
                        remember_trial_mark(working, name, new)

                        if new and not new.get("filename"):
                            unresolved.append(
                                f"{trial_name}: {name} = {new.get('value')}"
                            )

                    elif kind == "custom":
                        working["custom"][name] = new
                    else:
                        working["remarks"] = new

                    applied.append((kind, name, old, new))

                if not applied:
                    kept_names.append(trial_name)
                    continue

                working["status"] = "draft"

                append_trial_snapshot(
                    working,
                    "legacy-csv-import",
                    working.get("active_decision_id", ""),
                    source_csv=str(source),
                    source_record_time=row["RecordTime"],
                    source_data_row=record["row_number"],
                    source_row=copy.deepcopy(row),
                    source_trial_rows=copy.deepcopy(candidates),
                    applied_fields=[
                        {"kind": kind, "name": name}
                        for kind, name, _old, _new in applied
                    ],
                )

                staged["trials"][key] = working
                changed_names.append(trial_name)
                report.append(
                    f"{trial_name} — CSV data row {record['row_number']}\n"
                    + self.import_difference_details(applied)
                )

            summary = (
                f"Trials to update: {len(changed_names)}\n"
                f"Existing entries kept: {len(kept_names)}\n"
                f"Already identical: {len(identical_names)}\n"
                f"Explicitly skipped: {len(skipped_names)}\n"
                f"Unmatched CSV rows: {len(unmatched)}\n"
                f"Unresolved imported timestamps: {len(unresolved)}"
            )

            if unmatched:
                report.append(
                    "UNMATCHED CSV ROWS — not imported:\n"
                    + "\n".join(
                        f"Data row {item['row_number']}: "
                        f"{item['row']['Trial']}"
                        for item in unmatched
                    )
                )

            if ignored:
                report.append(
                    "IGNORED COLUMNS:\n" + "\n".join(ignored)
                )

            if unresolved:
                report.append(
                    "UNRESOLVED TIMESTAMPS:\n"
                    + "\n".join(unresolved)
                    + "\n\nTheir original text is retained. Re-mark or "
                    "clear them before submitting."
                )

            if kept_names:
                report.append(
                    "EXISTING ENTRIES KEPT:\n" + "\n".join(kept_names)
                )

            if identical_names:
                report.append(
                    "ALREADY IDENTICAL:\n" + "\n".join(identical_names)
                )

            if skipped_names:
                report.append(
                    "SKIPPED TRIALS:\n" + "\n".join(skipped_names)
                )

            details = summary + "\n\n" + "\n\n".join(report)

            if not changed_names:
                self.import_choice_dialog(
                    "Nothing to import",
                    summary + "\n\nNo project annotations were changed.",
                    [("Close report", details, "close")],
                )
                return

            approval = self.import_choice_dialog(
                "Review CSV import",
                summary + (
                    "\n\nReview the details, then confirm. "
                    "No CSV file will be modified."
                ),
                [
                    (
                        "Confirm import — save these draft changes",
                        details + (
                            "\n\nA backup of the current project JSON will "
                            "be created. Replaced drafts are also preserved "
                            "in decision history."
                        ),
                        "commit",
                    )
                ],
            )

            if approval != "commit":
                return

            # Commit the staged project directly. Do not call save_project()
            # here: its capture_form() would copy stale visible fields over
            # the newly imported values.
            self.cancel_pending_save()
            backup = timestamped_backup(
                self.project_path, "before_csv_import"
            )

            atomic_write(
                self.project_path,
                lambda handle: json.dump(
                    staged,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            )

        except Exception as exc:
            messagebox.showerror(
                "CSV import failed",
                f"{exc}\n\nNo staged import changes were applied.",
                parent=self.root,
            )
            return

        # The disk write succeeded. Now update the visible working project.
        self.project = staged
        self.build_timestamp_ui()
        self.rebuild_custom_fields()
        self.populate_form()
        self.refresh_panels()
        self.draw()

        self.message_var.set(
            f"Imported CSV changes into {len(changed_names)} trial(s). "
            "Saved as drafts; CSV files unchanged."
        )

        messagebox.showinfo(
            "Import complete",
            summary
            + "\n\nImported entries are saved in the project as drafts."
            + "\nUse Submit / Update when ready to export."
            + (
                "\n\nMissing or ambiguous timestamp frames were retained "
                "as unresolved values. Review them before submitting."
                if unresolved else ""
            )
            + (f"\n\nProject backup:\n{backup}" if backup else ""),
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Frame links / structures
    # ------------------------------------------------------------------

    def refresh_link_combos(self):
        names = self.timestamp_names()
        values = [MANUAL_FRAME_LABEL] + [
            f"Timestamp: {name}" for name in names
        ]

        for endpoint, combo in self.link_combos.items():
            combo["values"] = values
            linked = (
                self.trial["frame_links"].get(endpoint, "")
                if self.trial else ""
            )
            combo.current(names.index(linked) + 1 if linked in names else 0)

    def link_changed(self, endpoint):
        if self.trial is None:
            self.refresh_link_combos()
            return

        self.stop_playback()
        names = self.timestamp_names()
        index = self.link_combos[endpoint].current()
        linked = names[index - 1] if index > 0 else ""

        if linked == self.trial["frame_links"].get(endpoint, ""):
            return

        if linked and not self.confirm_linked_point_changes(
            [endpoint], self.timestamp_filename(linked)
        ):
            self.refresh_link_combos()
            return

        self.trial["frame_links"][endpoint] = linked
        self.cancel_marking()
        self.changed()

    def request_name(self, title, initial, existing):
        name = simpledialog.askstring(
            title, "Name:", initialvalue=initial, parent=self.root
        )

        if name is None:
            return None

        name = name.strip()
        if (
            not name or len(name) > 80 or "::" in name
            or "\n" in name or "\r" in name
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
            "Add structure", "",
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
            "Rename structure", structure["name"],
            {
                item["name"] for item in self.trial["measurements"]
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
            item for item in self.trial["comparisons"]
            if structure["id"] in (item["a_id"], item["b_id"])
        ]
        text = f"Delete '{structure['name']}' and its points?"
        if dependent:
            text += "\n\nAlso delete comparisons:\n" + "\n".join(
                item["name"] for item in dependent
            )

        if messagebox.askyesno("Delete structure", text):
            self.trial["measurements"].remove(structure)
            self.trial["comparisons"] = [
                item for item in self.trial["comparisons"]
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
        linked = self.trial["frame_links"].get(endpoint, "")

        if linked:
            filename = self.timestamp_filename(linked)
            if filename is None:
                messagebox.showinfo(
                    "Timestamp required", f"Mark '{linked}' first."
                )
                return
            if not self.go_to_filename(filename):
                return

        if self.image is None:
            return

        self.armed_endpoint = endpoint
        self.canvas.configure(cursor="crosshair")
        self.canvas.focus_set()

        hidden_note = (
            " Points are currently hidden; enable Show annotated points "
            "to see the result."
            if not self.show_points_var.get() else ""
        )

        self.message_var.set(
            f"Click to set {endpoint.upper()} for "
            f"'{self.measurement['name']}'. Escape cancels.{hidden_note}"
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
        linked = self.trial["frame_links"].get(endpoint, "")

        if linked and self.timestamp_filename(linked) != filename:
            self.cancel_marking()
            messagebox.showerror(
                "Wrong frame", "Use Set again to open the linked frame."
            )
            return

        ox, oy, sx, sy = self.transform
        x = (event.x - ox) / sx
        y = (event.y - oy) / sy
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
            f"{name}: {endpoint} point saved on frame {self.frame_index + 1}."
        )
        self.changed()

    def clear_endpoint(self, endpoint):
        if self.measurement is None or self.measurement[endpoint] is None:
            return

        if messagebox.askyesno(
            "Clear point",
            f"Clear the {endpoint} point for '{self.measurement['name']}'?",
        ):
            self.measurement[endpoint] = None
            self.cancel_marking()
            self.changed()

    def go_to_endpoint(self, endpoint):
        if self.measurement and self.measurement[endpoint]:
            self.go_to_filename(self.measurement[endpoint]["filename"])

    def structure_distance(self, structure):
        start = structure["start"]
        end = structure["end"]

        if start is None or end is None:
            return None

        if (start["width"], start["height"]) != (end["width"], end["height"]):
            return None

        dx = end["x"] - start["x"]
        dy = end["y"] - start["y"]
        pixels = math.hypot(dx, dy)

        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")
        mm = (
            math.hypot(dx * sx, dy * sy)
            if sx is not None and sy is not None else None
        )

        return dx, dy, pixels, mm

    # ------------------------------------------------------------------
    # Comparisons
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
                "Structures required", "Add at least two structures first."
            )
            return

        self.stop_playback()

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit comparison" if existing else "Add comparison")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)

        name_var = tk.StringVar(value=existing["name"] if existing else "")
        ttk.Label(body, text="Comparison name:").pack(anchor="w")
        ttk.Entry(body, textvariable=name_var, width=45).pack(
            fill="x", pady=(0, 10)
        )

        names = [item["name"] for item in structures]
        ids = [item["id"] for item in structures]
        combos = []

        for label, field, fallback in [
            ("Structure A — anchor:", "a_id", 0),
            ("Structure B — endpoint:", "b_id", 1),
        ]:
            ttk.Label(body, text=label).pack(anchor="w")
            combo = ttk.Combobox(body, values=names, state="readonly")
            combo.pack(fill="x", pady=(0, 8))
            combo.current(
                ids.index(existing[field])
                if existing and existing[field] in ids else fallback
            )
            combos.append(combo)

        ttk.Label(
            body,
            text=(
                "Start line: A.start → B.start\n"
                "End line: A.end → B.end\n"
                "Each line's points must share a frame."
            ),
        ).pack(anchor="w", pady=8)

        def apply():
            name = name_var.get().strip()
            if (
                not name or len(name) > 80 or "::" in name
                or "\n" in name or "\r" in name
            ):
                messagebox.showerror(
                    "Invalid name", "Use 1–80 characters without '::'.",
                    parent=dialog,
                )
                return

            if any(
                item["name"] == name and item is not existing
                for item in self.trial["comparisons"]
            ):
                messagebox.showerror(
                    "Duplicate name", "Use a unique name.", parent=dialog
                )
                return

            a_id = ids[combos[0].current()]
            b_id = ids[combos[1].current()]

            if a_id == b_id:
                messagebox.showerror(
                    "Invalid comparison",
                    "Choose different structures.", parent=dialog,
                )
                return

            if existing is None:
                self.trial["comparisons"].append(
                    new_comparison(name, a_id, b_id)
                )
                self.comparison_index = len(self.trial["comparisons"]) - 1
            else:
                existing.update(name=name, a_id=a_id, b_id=b_id)

            dialog.destroy()
            self.changed()

        ttk.Button(
            body, text="Save comparison", command=apply
        ).pack(fill="x", pady=8)

    def delete_comparison(self):
        comparison = self.comparison
        if comparison and messagebox.askyesno(
            "Delete comparison",
            f"Delete '{comparison['name']}'?\nThe points will remain.",
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
            item["id"]: item for item in self.trial["measurements"]
        }
        a = structures.get(comparison["a_id"])
        b = structures.get(comparison["b_id"])

        if a is None or b is None:
            raise ValueError("A comparison references a missing structure.")
        if a["id"] == b["id"]:
            raise ValueError("Choose two different structures.")

        points = [a["start"], b["start"], a["end"], b["end"]]

        if all(point is None for point in points):
            return None
        if any(point is None for point in points):
            raise ValueError("Mark Start and End for both structures.")

        a1, b1, a2, b2 = points

        if a1["filename"] != b1["filename"]:
            raise ValueError("A1 and B1 must share a frame.")
        if a2["filename"] != b2["filename"]:
            raise ValueError("A2 and B2 must share a frame.")

        if len({(p["width"], p["height"]) for p in points}) != 1:
            raise ValueError("All four points need matching image dimensions.")

        if any(p["filename"] not in self.frames for p in points):
            raise ValueError("A source frame is missing.")

        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        return {
            "structure_a": a,
            "structure_b": b,
            "points": points,
            "px": geometry_from_points(a1, b1, a2, b2),
            "mm": (
                geometry_from_points(a1, b1, a2, b2, sx, sy)
                if sx is not None and sy is not None else None
            ),
        }

    # ------------------------------------------------------------------
    # Live panels
    # ------------------------------------------------------------------

    def refresh_panels(self):
        if not self.in_main:
            return

        self.update_progress()
        self.refresh_link_combos()

        for name, label in self.mark_labels.items():
            filename = self.timestamp_filename(name)
            mark = self.trial["marks"].get(name) if self.trial else None

            if filename in self.frames:
                text = f"Frame {self.frames.index(filename) + 1}: {filename}"
            elif mark:
                value = mark.get("value", "") if isinstance(mark, dict) else mark
                text = f"Missing / unresolved: {filename or value}"
            else:
                text = "Not marked"

            label.configure(text=text)

        structures = self.trial["measurements"] if self.trial else []
        self.measurement_combo["values"] = [i["name"] for i in structures]

        if structures:
            self.measurement_index = max(
                0, min(self.measurement_index, len(structures) - 1)
            )
            self.measurement_combo.current(self.measurement_index)
        else:
            self.measurement_combo.set("")

        comparisons = self.trial["comparisons"] if self.trial else []
        self.comparison_combo["values"] = [i["name"] for i in comparisons]

        if comparisons:
            self.comparison_index = max(
                0, min(self.comparison_index, len(comparisons) - 1)
            )
            self.comparison_combo.current(self.comparison_index)
        else:
            self.comparison_combo.set("")

        if self.trial:
            active = self.trial.get("active_decision_id", "")
            self.decision_var.set(
                f"{len(self.trial['decisions'])} saved snapshot(s)\n"
                f"Overwrite target: "
                f"{active[:12] if active else 'latest matching legacy row'}"
            )
        else:
            self.decision_var.set("No trial loaded")

        structure = self.measurement

        for endpoint, variable in self.point_vars.items():
            point = structure[endpoint] if structure else None

            if not point:
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

        distance = self.structure_distance(structure) if structure else None

        if distance:
            dx, dy, pixels, mm = distance
            text = (
                f"Displacement: {pixels:.3f} px\n"
                f"Δx={dx:.3f}, Δy={dy:.3f} px"
            )
            if mm is not None:
                text += f"\nDisplacement: {mm:.3f} mm"
            self.displacement_var.set(text)
        elif structure and structure["start"] and structure["end"]:
            self.displacement_var.set("Cannot calculate: dimensions differ.")
        else:
            self.displacement_var.set("Displacement: mark both points.")

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None

        self.calibration_var.set(
            f"Calibration: X={sx:g}, Y={sy:g} mm/px"
            if sx is not None and sy is not None
            else "Pixels only. Set X/Y calibration in Config."
        )

        if self.comparison is None:
            self.geometry_var.set("Add a comparison to calculate geometry.")
            return

        try:
            result = self.comparison_result(self.comparison)

            if result is None:
                self.geometry_var.set(
                    "Mark Start and End on both structures."
                )
                return

            lines = [
                f"A: {result['structure_a']['name']}",
                f"B: {result['structure_b']['name']}",
            ]

            for unit in ("px", "mm"):
                values = result[unit]
                if values is None:
                    continue

                lines.extend([
                    "",
                    "Pixel results" if unit == "px" else "Calibrated results",
                    f"L1 = {fmt(values['L1'])} {unit}",
                    f"L2 = {fmt(values['L2'])} {unit}",
                    f"a = {fmt(values['AngleA'])}°",
                    f"b = {fmt(values['AngleB'])}°",
                    f"c = {fmt(values['AngleC'])}°",
                    f"Signed rotation = {fmt(values['SignedRotation'])}°",
                    f"Opposite side = {fmt(values['OppositeSide'])} {unit}",
                ])

            self.geometry_var.set("\n".join(lines))

        except (ValueError, KeyError, TypeError) as exc:
            self.geometry_var.set(f"Comparison not ready:\n{exc}")

    # ------------------------------------------------------------------
    # Rendering
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
                text="No image loaded", fill="white",
            )
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        width, height = self.image.size

        scale = min(cw / width, ch / height)
        dw = max(1, round(width * scale))
        dh = max(1, round(height * scale))

        ox, oy = (cw - dw) / 2, (ch - dh) / 2
        sx, sy = dw / width, dh / height
        self.transform = (ox, oy, sx, sy)

        key = (id(self.image), dw, dh)
        if key != self.render_key:
            self.photo = ImageTk.PhotoImage(
                self.image.resize((dw, dh), Image.Resampling.LANCZOS)
            )
            self.render_key = key

        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")

        current_filename = self.frames[self.frame_index]
        show_references = self.reference_var.get()
        show_lines = self.show_lines_var.get()
        show_points = self.show_points_var.get()

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
            return ox + point["x"] * sx, oy + point["y"] * sy

        structure = self.measurement

        if (
            show_lines and structure
            and visible(structure["start"])
            and visible(structure["end"])
        ):
            self.canvas.create_line(
                *position(structure["start"]),
                *position(structure["end"]),
                fill="#ffff66", width=2, dash=(5, 4),
            )

        comparison = self.comparison

        if show_lines and comparison:
            by_id = {i["id"]: i for i in self.trial["measurements"]}
            a = by_id.get(comparison["a_id"])
            b = by_id.get(comparison["b_id"])

            if a and b:
                for endpoint, color, label in [
                    ("start", "#30e0ff", "L1"),
                    ("end", "#ff8c42", "L2"),
                ]:
                    p1, p2 = a[endpoint], b[endpoint]

                    if (
                        visible(p1) and visible(p2)
                        and p1["filename"] == p2["filename"]
                    ):
                        x1, y1 = position(p1)
                        x2, y2 = position(p2)
                        style = {"fill": color, "width": 2}

                        if p1["filename"] != current_filename:
                            style["dash"] = (5, 3)

                        self.canvas.create_line(x1, y1, x2, y2, **style)
                        self.canvas.create_text(
                            (x1 + x2) / 2, (y1 + y2) / 2 - 12,
                            text=f"{comparison['name']} {label}",
                            fill=color, font=("Arial", 10, "bold"),
                        )

        if not show_points:
            return

        for item in self.trial["measurements"]:
            for endpoint, color in [
                ("start", "#30e0ff"), ("end", "#ff8c42")
            ]:
                point = item[endpoint]
                if not visible(point):
                    continue

                x, y = position(point)
                current = point["filename"] == current_filename
                selected = item is structure
                length = 8 if selected else 6

                style = {
                    "fill": color,
                    "width": 2 if selected else 1,
                    "capstyle": tk.BUTT,
                }
                if not current:
                    style["dash"] = (3, 2)

                self.canvas.create_line(
                    x - length, y, x + length, y, **style
                )
                self.canvas.create_line(
                    x, y - length, x, y + length, **style
                )

                number = self.frames.index(point["filename"]) + 1
                label = (
                    f"{item['name']} "
                    f"{'1' if endpoint == 'start' else '2'} | F{number}"
                    + ("" if current else " [ref]")
                )

                self.canvas.create_text(
                    x + 11,
                    y - 12 if endpoint == "start" else y + 12,
                    text=label, fill=color, anchor="w",
                    font=("Arial", 10, "bold" if selected else "normal"),
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
        window.title(f"Aligned triangle — {self.comparison['name']}")
        window.geometry("640x470")

        ttk.Label(
            window,
            text=(
                f"Origins aligned without rotation — {unit}\n"
                f"L1={fmt(values['L1'])} | L2={fmt(values['L2'])} | "
                f"c={fmt(values['AngleC'])}°\n"
                f"Opposite side={fmt(values['OppositeSide'])} {unit}"
            ),
            padding=10, justify="center",
        ).pack(fill="x")

        canvas = tk.Canvas(
            window, background="#151515", highlightthickness=0
        )
        canvas.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            window,
            text="Translated-vector diagram, not image registration.",
            padding=8,
        ).pack(fill="x")

        def render(_event=None):
            canvas.delete("all")
            points = [(0.0, 0.0), values["vector_1"], values["vector_2"]]
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            width = max(100, canvas.winfo_width())
            height = max(100, canvas.winfo_height())

            scale = min(
                max(1, width - 100) / max(max(xs) - min(xs), 1e-9),
                max(1, height - 100) / max(max(ys) - min(ys), 1e-9),
            )
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2

            converted = [
                (
                    width / 2 + (x - cx) * scale,
                    height / 2 - (y - cy) * scale,
                )
                for x, y in points
            ]
            origin, end1, end2 = converted

            canvas.create_line(*origin, *end1, fill="#30e0ff", width=3)
            canvas.create_line(*origin, *end2, fill="#ff8c42", width=3)
            canvas.create_line(
                *end1, *end2, fill="#ffff66", width=2, dash=(5, 3)
            )

            for (x, y), label, color in [
                (origin, "A1 = A2", "white"),
                (end1, "B1", "#30e0ff"),
                (end2, "B2 aligned", "#ff8c42"),
            ]:
                canvas.create_line(x - 5, y, x + 5, y, fill=color, width=2)
                canvas.create_line(x, y - 5, x, y + 5, fill=color, width=2)
                canvas.create_text(x, y + 17, text=label, fill=color)

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

        dialog.geometry(
            f"650x{min(780, max(500, self.root.winfo_screenheight() - 120))}"
        )

        footer = ttk.Frame(dialog, padding=8)
        footer.pack(side="bottom", fill="x")

        scroll = ttk.Scrollbar(dialog, orient="vertical")
        scroll.pack(side="right", fill="y")

        canvas = tk.Canvas(dialog, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.configure(command=canvas.yview)

        body = ttk.Frame(canvas, padding=16)
        win = canvas.create_window((0, 0), window=body, anchor="nw")

        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(win, width=event.width),
        )

        row_vars = []

        for index, row in enumerate(self.project["mark_rows"]):
            ttk.Label(
                body,
                text=f"Timestamp row {index + 1} "
                     f"({''.join(ROW_KEYS[index]).upper()}):",
            ).pack(anchor="w", pady=(6, 2))

            variable = tk.StringVar(value=", ".join(row))
            ttk.Entry(body, textvariable=variable).pack(fill="x")
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
            ttk.Label(body, text=label).pack(anchor="w", pady=(8, 2))
            ttk.Entry(body, textvariable=variable).pack(fill="x")

        ttk.Label(body, text="Filename ordering:").pack(
            anchor="w", pady=(8, 2)
        )
        ttk.Combobox(
            body, textvariable=sort_var,
            values=["lexicographic", "natural"], state="readonly",
        ).pack(fill="x")

        ttk.Label(
            body,
            text="Lexicographic retains original ordering.\n"
                 "Natural puts frame_2 before frame_10.",
        ).pack(anchor="w", pady=4)

        sx = self.trial.get("spacing_x") if self.trial else None
        sy = self.trial.get("spacing_y") if self.trial else None
        sx_var = tk.StringVar(value="" if sx is None else str(sx))
        sy_var = tk.StringVar(value="" if sy is None else str(sy))

        if self.trial is not None:
            for label, variable in [
                ("This trial: X spacing, mm/pixel:", sx_var),
                ("This trial: Y spacing, mm/pixel:", sy_var),
            ]:
                ttk.Label(body, text=label).pack(anchor="w", pady=(8, 2))
                ttk.Entry(body, textvariable=variable).pack(fill="x")

            ttk.Label(
                body,
                text="Leave BOTH blank for pixel-only results.",
            ).pack(anchor="w", pady=5)

        def apply():
            try:
                rows = [
                    [n.strip() for n in variable.get().split(",") if n.strip()]
                    for variable in row_vars
                ]
                custom = [
                    n.strip() for n in custom_var.get().split(",") if n.strip()
                ]
                validate_field_names(rows, custom)

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
                            "Provide both spacings or leave both blank."
                        )

                    if x_text:
                        spacing_x = float(x_text)
                        spacing_y = float(y_text)

                        if not all(
                            math.isfinite(v) and v > 0
                            for v in (spacing_x, spacing_y)
                        ):
                            raise ValueError(
                                "Spacings must be positive finite numbers."
                            )

                names = {name for row in rows for name in row}
                removed_links = [
                    (trial, endpoint)
                    for trial in self.project["trials"].values()
                    for endpoint, name in trial["frame_links"].items()
                    if name and name not in names
                ]

                if removed_links and not messagebox.askyesno(
                    "Removed categories",
                    "Some point links refer to removed categories.\n"
                    "Switch those links to Manual and retain their points?",
                    parent=dialog,
                ):
                    return

            except ValueError as exc:
                messagebox.showerror(
                    "Invalid configuration", str(exc), parent=dialog
                )
                return

            self.capture_form()

            for trial, endpoint in removed_links:
                trial["frame_links"][endpoint] = ""
                trial["status"] = "draft"

            self.project.update(
                mark_rows=rows,
                custom_fields=custom,
                fps=fps,
                frame_sort=sort_var.get(),
            )

            if self.trial is not None:
                self.trial.update(
                    spacing_x=spacing_x,
                    spacing_y=spacing_y,
                    status="draft",
                )

            self.build_timestamp_ui()
            self.rebuild_custom_fields()

            if self.save_project():
                dialog.destroy()
                self.refresh_trials()

        ttk.Button(footer, text="Apply", command=apply).pack(fill="x")

    # ------------------------------------------------------------------
    # Export validation
    # ------------------------------------------------------------------

    def validate_point(self, point, size_cache):
        filename = point.get("filename")
        if filename not in self.frames:
            raise ValueError(f"Missing source frame: {filename}")

        x, y = point.get("x"), point.get("y")
        if not all(
            isinstance(v, (int, float)) and math.isfinite(v)
            for v in (x, y)
        ):
            raise ValueError(f"Invalid coordinates: {filename}")

        if filename not in size_cache:
            with Image.open(Path(self.trial_key) / filename) as source:
                size_cache[filename] = source.size

        if size_cache[filename] != (point.get("width"), point.get("height")):
            raise ValueError(
                f"Source dimensions changed: {filename}\nPlease re-mark it."
            )

        width, height = size_cache[filename]
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"Point is outside the image: {filename}")

    def validate_trial_for_export(self):
        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        if (sx is None) != (sy is None):
            raise ValueError("Both calibration values are required.")

        if sx is not None and not all(
            isinstance(v, (int, float)) and math.isfinite(v) and v > 0
            for v in (sx, sy)
        ):
            raise ValueError("Invalid calibration.")

        for name in self.timestamp_names():
            mark = self.trial["marks"].get(name)
            if mark and self.timestamp_filename(name) not in self.frames:
                raise ValueError(
                    f"Timestamp '{name}' has a missing or unresolved frame.\n"
                    "Re-mark it or clear it before submitting."
                )

        size_cache = {}

        for structure in self.trial["measurements"]:
            start, end = structure["start"], structure["end"]
            if start is None and end is None:
                continue

            if start is None or end is None:
                raise ValueError(
                    f"'{structure['name']}' has only one point.\n"
                    "Complete it, clear it, or delete the structure."
                )

            for endpoint in ("start", "end"):
                point = structure[endpoint]
                self.validate_point(point, size_cache)
                linked = self.trial["frame_links"].get(endpoint, "")

                if linked:
                    if linked not in self.timestamp_names():
                        raise ValueError(
                            f"Link '{linked}' is not configured. "
                            "Switch it to Manual or add the category in Config."
                        )
                    if self.timestamp_filename(linked) != point["filename"]:
                        raise ValueError(
                            f"'{structure['name']}' {endpoint} does not match "
                            f"timestamp '{linked}'."
                        )

            if self.structure_distance(structure) is None:
                raise ValueError(
                    f"'{structure['name']}': image dimensions differ."
                )

        for comparison in self.trial["comparisons"]:
            try:
                self.comparison_result(comparison)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(
                    f"Comparison '{comparison['name']}': {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Combined CSV row
    # ------------------------------------------------------------------

    def export_row(self):
        self.validate_trial_for_export()

        row = {
            "Trial": Path(self.trial_key).name,
            "RecordTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for name in self.timestamp_names():
            filename = self.timestamp_filename(name)
            row[name] = Path(filename).stem if filename else "nil"

        for name in self.project["custom_fields"]:
            value = self.trial["custom"].get(name, "")
            row[name] = str(value).strip() or "nil"

        row["Remarks"] = self.trial.get("remarks", "").strip() or "nil"
        row.update({
            "Project": self.project["name"],
            "SourceFolder": self.trial_key,
            "SpacingX_mm_per_px": self.trial.get("spacing_x"),
            "SpacingY_mm_per_px": self.trial.get("spacing_y"),
        })

        for name in self.timestamp_names():
            filename = self.timestamp_filename(name)
            prefix = f"Timestamp::{name}::"
            row[prefix + "Filename"] = filename
            row[prefix + "FrameIndex"] = (
                self.frames.index(filename) + 1
                if filename in self.frames else None
            )

        for structure in self.trial["measurements"]:
            prefix = f"Point::{structure['name']}::"
            row[prefix + "MeasurementID"] = structure["id"]

            for endpoint, label in [("start", "Start"), ("end", "End")]:
                point = structure[endpoint]
                values = {
                    "Filename": point["filename"] if point else None,
                    "FrameIndex": (
                        self.frames.index(point["filename"]) + 1
                        if point else None
                    ),
                    "X_px": point["x"] if point else None,
                    "Y_px": point["y"] if point else None,
                    "ImageWidth_px": point["width"] if point else None,
                    "ImageHeight_px": point["height"] if point else None,
                    "TimestampLink": self.trial["frame_links"].get(endpoint, ""),
                }

                for suffix, value in values.items():
                    row[prefix + label + suffix] = value

            distance = self.structure_distance(structure)
            for index, label in enumerate([
                "DeltaX_px", "DeltaY_px", "Distance_px", "Distance_mm"
            ]):
                row[prefix + label] = distance[index] if distance else None

        structures = {
            item["id"]: item for item in self.trial["measurements"]
        }

        for comparison in self.trial["comparisons"]:
            prefix = f"Comparison::{comparison['name']}::"
            result = self.comparison_result(comparison)
            a = structures[comparison["a_id"]]
            b = structures[comparison["b_id"]]

            metadata = {
                "ComparisonID": comparison["id"],
                "StructureA": a["name"],
                "StructureB": b["name"],
                "StructureA_ID": a["id"],
                "StructureB_ID": b["id"],
                "Status": (
                    "not_marked" if result is None
                    else "zero_length_line_angle_undefined"
                    if result["px"]["AngleC"] is None else "complete"
                ),
            }

            for label, value in metadata.items():
                row[prefix + label] = value

            for endpoint, label in [("start", "Start"), ("end", "End")]:
                point = a[endpoint] if result else None
                row[prefix + label + "Filename"] = (
                    point["filename"] if point else None
                )
                row[prefix + label + "FrameIndex"] = (
                    self.frames.index(point["filename"]) + 1 if point else None
                )

            for unit in ("px", "mm"):
                values = result[unit] if result else None

                for key in ("L1", "L2", "OppositeSide"):
                    row[prefix + f"{key}_{unit}"] = (
                        values[key] if values else None
                    )

                for key in ("AngleA", "AngleB", "AngleC", "SignedRotation"):
                    row[prefix + f"{key}_{unit}_deg"] = (
                        values[key] if values else None
                    )

        return row

    # ------------------------------------------------------------------
    # Append / overwrite
    # ------------------------------------------------------------------

    def matching_csv_rows(self, rows):
        """Prefer explicit project + source-folder identity."""
        matches = []

        for index, row in enumerate(rows):
            project = (row.get("Project") or "").strip()
            source = (row.get("SourceFolder") or "").strip()

            if project and project != self.project["name"]:
                continue

            if source:
                if same_folder(source, self.trial_key):
                    matches.append(index)
            elif row.get("Trial") == Path(self.trial_key).name:
                matches.append(index)

        return matches

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

        path = Path(self.project["csv_path"])
        mode = self.submit_mode_var.get()
        target_index = None

        try:
            row = self.export_row()
            columns, previous_rows = read_csv_table(path)

            if mode == "overwrite":
                active_id = self.trial.get("active_decision_id", "")

                if active_id:
                    matches = [
                        index for index, previous in enumerate(previous_rows)
                        if previous.get("DecisionID") == active_id
                    ]

                    if len(matches) > 1:
                        raise ValueError(
                            "The CSV contains duplicate DecisionID values.\n"
                            "Repair the duplicates before overwriting."
                        )

                    if not matches:
                        raise ValueError(
                            "The recalled decision is not present in the selected CSV.\n"
                            "Select its original CSV or choose Append.\n\n"
                            "No unrelated row was overwritten."
                        )

                    target_index = matches[0]
                    target = previous_rows[target_index]

                    if (
                        target.get("Project")
                        and target["Project"] != self.project["name"]
                    ) or (
                        target.get("SourceFolder")
                        and not same_folder(target["SourceFolder"], self.trial_key)
                    ):
                        raise ValueError(
                            "The matching DecisionID belongs to a different "
                            "project or source folder."
                        )

                else:
                    matches = self.matching_csv_rows(previous_rows)
                    if not matches:
                        raise ValueError(
                            "No matching decision exists in this CSV.\n"
                            "Choose Append for the first submission."
                        )

                    target_index = matches[-1]
                    target = previous_rows[target_index]

                record_id = target.get("DecisionID") or uuid.uuid4().hex

                try:
                    revision = int(target.get("DecisionRevision") or "1") + 1
                except (TypeError, ValueError):
                    revision = 2

                weak_identity = not target.get("SourceFolder")

                text = (
                    f"Overwrite CSV data row {target_index + 1}?\n\n"
                    f"Trial: {target.get('Trial', '')}\n"
                    f"Previous record time: {target.get('RecordTime', '')}\n"
                    f"New revision: {revision}\n\n"
                    "Only this row will be replaced. Other rows remain.\n"
                    "A backup of the CSV will be created."
                )

                if weak_identity:
                    text += (
                        "\n\nLEGACY ROW: matched by trial name because this row "
                        "has no source-folder identity. Verify the trial carefully."
                    )

                if not messagebox.askyesno(
                    "Confirm overwrite", text, parent=self.root
                ):
                    return

            else:
                record_id = uuid.uuid4().hex
                revision = 1

                if not messagebox.askyesno(
                    "Append decision",
                    f"Append a new decision row for '{Path(self.trial_key).name}'?\n\n"
                    "Existing CSV rows will remain unchanged.",
                    parent=self.root,
                ):
                    return

            row["DecisionID"] = record_id
            row["DecisionRevision"] = revision

            added_columns = [column for column in row if column not in columns]

            if target_index is not None:
                timestamped_backup(path)
            elif columns and added_columns:
                backup_once(path, ".before_merge.bak")

            columns.extend(added_columns)

            if target_index is None:
                output_rows = previous_rows + [row]
            else:
                output_rows = list(previous_rows)
                old_row = previous_rows[target_index]

                replacement = {
                    column: (
                        ""
                        if column.startswith(COLUMN_PREFIXES)
                        else old_row.get(column, "")
                    )
                    for column in columns
                }

                owned_names = set(self.timestamp_names())
                owned_names.update(self.project["custom_fields"])
                owned_names.update(self.trial["marks"])
                owned_names.update(self.trial["custom"])

                for entry in self.trial["decisions"]:
                    snapshot = entry.get("snapshot", {})
                    owned_names.update(snapshot.get("marks", {}))
                    owned_names.update(snapshot.get("custom", {}))

                for name in owned_names:
                    if name in replacement:
                        replacement[name] = ""

                replacement.update(row)
                output_rows[target_index] = replacement

            write_csv_table(path, columns, output_rows)

        except Exception as exc:
            messagebox.showerror(
                "Submit failed", str(exc), parent=self.root
            )
            return

        self.trial["active_decision_id"] = record_id
        self.trial["status"] = "submitted"
        self.add_decision_history(mode, record_id, revision)
        self.refresh_panels()

        if not self.save_project():
            messagebox.showwarning(
                "CSV saved",
                "The CSV was saved, but saving the project/history failed.\n"
                "Use Save Project to retry. Do not append again just to "
                "retry saving the project.",
                parent=self.root,
            )
            return

        self.message_var.set(
            f"Decision {'appended' if mode == 'append' else 'updated'}: "
            f"{record_id[:12]}, revision {revision}."
        )

        if self.advance_var.get():
            self.advance_trial()

    def skip_trial(self):
        if self.trial is None:
            return

        self.stop_playback()
        self.cancel_marking()

        if messagebox.askyesno(
            "Skip trial",
            "Move to the next trial without exporting?\n"
            "The current working annotations will remain saved.",
            parent=self.root,
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
                "Use the trial selector or Previous trial to revisit a trial.\n\n"
                "Recall a decision, edit it, then choose Append or Overwrite.",
            )

    # ------------------------------------------------------------------
    # Keyboard / shutdown
    # ------------------------------------------------------------------

    def is_typing(self):
        return isinstance(
            self.root.focus_get(),
            (
                tk.Entry, ttk.Entry, tk.Text,
                ttk.Combobox, tk.Spinbox, ttk.Spinbox,
            ),
        )

    def handle_key(self, event):
        if not self.in_main or self.root.grab_current() is not None:
            return

        focus = self.root.focus_get()

        if focus is not None and focus.winfo_toplevel() != self.root:
            return
        if self.is_typing():
            return
        if event.state & 0x0004 or event.state & 0x0008:
            return

        key = event.keysym.lower()

        if key == "escape":
            self.cancel_marking()
            self.message_var.set("Marking canceled.")
            return "break"

        if isinstance(focus, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton)):
            if key in ("space", "return"):
                return

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
            if key in ("s", "e"):
                self.arm("start" if key == "s" else "end")
                return "break"
        else:
            character = event.char.lower()

            for row_index, keys in enumerate(ROW_KEYS):
                if character in keys:
                    column_index = keys.index(character)
                    names = self.project["mark_rows"][row_index]

                    if column_index < len(names):
                        self.set_mark(names[column_index])
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
