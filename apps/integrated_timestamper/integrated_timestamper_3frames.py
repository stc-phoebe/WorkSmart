"""
WorkSmart Integrated Timestamper — Three-Frame Extension

Required companion:
    integrated_timestamper.py
    Leave the original file unchanged, in this same folder.

Run:
    python integrated_timestamper_3frames.py

Run self-tests:
    python integrated_timestamper_3frames.py --self-test

Frame sets:
    Set 1 = Start
    Set 2 = Middle
    Set 3 = End

Point hotkeys:
    S = Start
    M = Middle
    E = End

CSV:
    Reads original Timestamper CSVs and combined two-/three-frame CSVs.
    Continues exporting the existing three-frame combined format.
    The selected display pair never limits exported pairs.

Folder relocation:
    Saved trials can be moved to a new parent folder after confirmation.
    Original project data is backed up before committed changes.
    Ambiguous trial matches require an explicit choice.

Import:
    CSV files are never modified by importing.
    Imported annotations are saved as drafts.
    Conflicting source rows require an explicit choice.
    Replaced project annotations remain in decision history.
"""

import copy
import csv
import importlib.util
import json
import math
import ntpath
import posixpath
import sys
import tempfile
from pathlib import Path


# ----------------------------------------------------------------------
# Load the original application.
# ----------------------------------------------------------------------

ORIGINAL_SCRIPT = Path(__file__).resolve().with_name(
    "integrated_timestamper.py"
)

if not ORIGINAL_SCRIPT.is_file():
    raise SystemExit(
        "Required original script was not found:\n"
        f"{ORIGINAL_SCRIPT}\n\n"
        "Keep integrated_timestamper.py unchanged in this same folder."
    )

if ORIGINAL_SCRIPT == Path(__file__).resolve():
    raise SystemExit(
        "The extension and original script need different filenames."
    )

_spec = importlib.util.spec_from_file_location(
    "_worksmart_original_timestamper",
    ORIGINAL_SCRIPT,
)

if _spec is None or _spec.loader is None:
    raise SystemExit("Could not load the original Timestamper script.")

base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

tk = base.tk
ttk = base.ttk
messagebox = base.messagebox
Image = base.Image
ImageTk = base.ImageTk

THREE_FRAME_VERSION = 4

FRAME_SETS = (
    ("start", "Start", 1, "#30e0ff"),
    ("middle", "Middle", 2, "#75ef87"),
    ("end", "End", 3, "#ff8c42"),
)

SET_INFO = {
    key: {
        "label": label,
        "number": number,
        "color": color,
    }
    for key, label, number, color in FRAME_SETS
}

PAIR_SPECS = (
    (
        "start:middle",
        "1 → 2 — Start → Middle",
        ("start", "middle"),
        "Pair12",
    ),
    (
        "middle:end",
        "2 → 3 — Middle → End",
        ("middle", "end"),
        "Pair23",
    ),
    (
        "start:end",
        "1 → 3 — Start → End",
        ("start", "end"),
        "Pair13",
    ),
)

PAIR_BY_ID = {
    identifier: (label, pair, csv_label)
    for identifier, label, pair, csv_label in PAIR_SPECS
}

DEFAULT_PAIR_ID = "start:end"
LEGACY_PAIR = ("start", "end")

DISTANCE_FIELDS = (
    "DeltaX_px",
    "DeltaY_px",
    "Distance_px",
    "Distance_mm",
)

LENGTH_FIELDS = ("L1", "L2", "OppositeSide")
ANGLE_FIELDS = ("AngleA", "AngleB", "AngleC", "SignedRotation")

POINT_DATA_KEYS = (
    "measurements",
    "comparisons",
    "frame_links",
    "spacing_x",
    "spacing_y",
)

# Exact historical source folders explicitly accepted by the user.
SOURCE_ALIASES_KEY = "_confirmed_source_folders"


# ----------------------------------------------------------------------
# Extend original data helpers in memory only.
# ----------------------------------------------------------------------

_original_new_structure = base.new_structure
_original_new_trial = base.new_trial
_original_new_project = base.new_project
_original_normalize_trial = base.normalize_trial
_original_normalize_project = base.normalize_project
_original_trial_has_work = base.trial_has_work


def new_structure(name):
    structure = _original_new_structure(name)
    structure["middle"] = None
    return structure


def new_trial():
    trial = _original_new_trial()
    trial["frame_links"].setdefault("middle", "")
    trial.setdefault(SOURCE_ALIASES_KEY, [])

    for structure in trial["measurements"]:
        structure.setdefault("middle", None)

    return trial


def new_project(name):
    project = _original_new_project(name)
    project["version"] = THREE_FRAME_VERSION
    project["point_pair"] = DEFAULT_PAIR_ID
    return project


def normalize_trial(trial):
    trial = _original_normalize_trial(trial)

    for endpoint, _label, _number, _color in FRAME_SETS:
        trial["frame_links"].setdefault(endpoint, "")

    for structure in trial["measurements"]:
        for endpoint, _label, _number, _color in FRAME_SETS:
            structure.setdefault(endpoint, None)

    aliases = trial.setdefault(SOURCE_ALIASES_KEY, [])
    if not isinstance(aliases, list) or any(
        not isinstance(value, str) for value in aliases
    ):
        raise ValueError("Invalid confirmed source-folder list.")

    return trial


def normalize_project(raw, name):
    if not isinstance(raw, dict):
        raise ValueError("The project file must contain a JSON object.")

    incoming = copy.deepcopy(raw)

    if incoming.get("application") == base.APP_ID:
        version = incoming.get("version")
        if version not in (2, 3, THREE_FRAME_VERSION):
            raise ValueError("Unsupported integrated project version.")
        if version == THREE_FRAME_VERSION:
            incoming["version"] = 3

    project = _original_normalize_project(incoming, name)
    project["version"] = THREE_FRAME_VERSION

    if project.get("point_pair") not in PAIR_BY_ID:
        project["point_pair"] = DEFAULT_PAIR_ID

    return project


def trial_has_work(trial):
    return bool(
        _original_trial_has_work(trial)
        or any(
            structure.get("middle") is not None
            for structure in trial.get("measurements", [])
        )
    )


base.APP_VERSION = THREE_FRAME_VERSION
base.new_structure = new_structure
base.new_trial = new_trial
base.new_project = new_project
base.normalize_trial = normalize_trial
base.normalize_project = normalize_project
base.trial_has_work = trial_has_work


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------

def pair_title(pair):
    first, second = pair
    return (
        f"{SET_INFO[first]['number']} → {SET_INFO[second]['number']}"
        f" ({SET_INFO[first]['label']} → {SET_INFO[second]['label']})"
    )


def point_pair_distance(structure, pair, spacing_x=None, spacing_y=None):
    if structure is None:
        return None

    first, second = pair
    point_1 = structure.get(first)
    point_2 = structure.get(second)

    if point_1 is None or point_2 is None:
        return None

    if (
        point_1["width"], point_1["height"]
    ) != (
        point_2["width"], point_2["height"]
    ):
        return None

    dx = point_2["x"] - point_1["x"]
    dy = point_2["y"] - point_1["y"]

    if not all(math.isfinite(value) for value in (dx, dy)):
        raise ValueError("Point coordinates must be finite.")

    pixels = math.hypot(dx, dy)
    millimeters = (
        math.hypot(dx * spacing_x, dy * spacing_y)
        if spacing_x is not None and spacing_y is not None
        else None
    )

    return dx, dy, pixels, millimeters


def distance_status(structure, pair):
    points = [structure.get(endpoint) for endpoint in pair]

    if all(point is None for point in points):
        return "not_marked"
    if any(point is None for point in points):
        return "incomplete"
    if len({(p["width"], p["height"]) for p in points}) != 1:
        return "dimension_mismatch"

    return "complete"


def comparison_status(a, b, pair, result):
    if result is not None:
        return (
            "zero_length_line_angle_undefined"
            if result["px"]["AngleC"] is None
            else "complete"
        )

    points = [
        structure.get(endpoint)
        for endpoint in pair
        for structure in (a, b)
    ]
    return (
        "not_marked"
        if all(point is None for point in points)
        else "incomplete"
    )


def add_geometry_columns(row, prefix, result):
    for unit in ("px", "mm"):
        values = result[unit] if result is not None else None

        for key in LENGTH_FIELDS:
            row[prefix + f"{key}_{unit}"] = (
                values[key] if values is not None else None
            )

        for key in ANGLE_FIELDS:
            row[prefix + f"{key}_{unit}_deg"] = (
                values[key] if values is not None else None
            )


# ----------------------------------------------------------------------
# Path and CSV helpers
# ----------------------------------------------------------------------

def portable_basename(value):
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def path_identity(value):
    """
    Compare saved absolute paths without accessing the NAS.

    Windows paths are case-insensitive.
    POSIX paths retain case.
    """
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""

    drive, _tail = ntpath.splitdrive(text)
    normalized = posixpath.normpath(text)

    if drive:
        normalized = normalized.casefold()

    return normalized


def same_saved_path(left, right):
    return bool(
        path_identity(left)
        and path_identity(left) == path_identity(right)
    )


def add_source_alias(trial, source, current=None):
    if not source or (current and same_saved_path(source, current)):
        return

    aliases = trial.setdefault(SOURCE_ALIASES_KEY, [])
    if not any(same_saved_path(source, old) for old in aliases):
        aliases.append(str(source))


def source_matches_trial(source, key, trial):
    if same_saved_path(source, key):
        return True
    return any(
        same_saved_path(source, alias)
        for alias in trial.get(SOURCE_ALIASES_KEY, [])
    )


def csv_text(value):
    """
    Preserve leading zeros and text.

    The exporter uses literal 'nil' for missing values.
    """
    if value is None:
        return ""
    text = str(value)
    return "" if not text.strip() or text == "nil" else text


def require_float(value, label):
    text = csv_text(value)
    if not text:
        raise ValueError(f"Missing numeric value: {label}")

    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {label}: {text!r}") from exc

    if not math.isfinite(number):
        raise ValueError(f"Nonfinite value for {label}.")

    return number


def require_positive_int(value, label):
    number = require_float(value, label)
    if number <= 0 or not number.is_integer():
        raise ValueError(f"{label} must be a positive integer.")
    return int(number)


def read_import_csv(path, encoding="utf-8-sig"):
    """
    Read both layouts without converting numeric-looking text.

    Reject malformed rows rather than shifting annotation columns.
    """
    with Path(path).open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames or []

        if not columns:
            raise ValueError("The CSV has no header.")

        if any(not name or not name.strip() for name in columns):
            raise ValueError("The CSV contains an empty column name.")

        if len(columns) != len(set(columns)):
            raise ValueError("The CSV contains duplicate column names.")

        required = {"Trial", "RecordTime", "Remarks"}
        missing = required.difference(columns)
        if missing:
            raise ValueError(
                "Missing required CSV columns: " + ", ".join(sorted(missing))
            )

        combined = any(
            column.startswith(base.COLUMN_PREFIXES)
            or column in (
                "Project",
                "SourceFolder",
                "DecisionID",
                "DecisionRevision",
                "SpacingX_mm_per_px",
                "SpacingY_mm_per_px",
            )
            for column in columns
        )

        if not combined and (
            columns[:2] != ["Trial", "RecordTime"]
            or columns[-1] != "Remarks"
        ):
            raise ValueError(
                "Unrecognized original CSV layout.\n"
                "Expected Trial,RecordTime,<fields>,Remarks."
            )

        records = []

        for row_number, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"CSV data row {row_number} has a different number of "
                    "values from its header.\n"
                    "No columns will be guessed or shifted."
                )

            if all(row[column] == column for column in columns):
                raise ValueError(
                    f"CSV data row {row_number} repeats the header."
                )

            if not row["Trial"].strip():
                raise ValueError(
                    f"CSV data row {row_number} has no Trial value."
                )

            records.append({
                "row_number": row_number,
                "row": row,
            })

    if not records:
        raise ValueError("The CSV has no data rows.")

    return columns, records, combined


def timestamp_columns(columns):
    result = {}

    for column in columns:
        if not column.startswith("Timestamp::"):
            continue

        remainder = column[len("Timestamp::"):]
        if "::" not in remainder:
            raise ValueError(f"Invalid timestamp column: {column}")

        name, field = remainder.rsplit("::", 1)
        if not name or field not in ("Filename", "FrameIndex"):
            raise ValueError(f"Unsupported timestamp column: {column}")

        result.setdefault(name, {})[field] = column

    return result


def grouped_columns(columns, prefix):
    result = {}

    for column in columns:
        if not column.startswith(prefix):
            continue

        remainder = column[len(prefix):]
        if "::" not in remainder:
            raise ValueError(f"Invalid structured CSV column: {column}")

        name, field = remainder.split("::", 1)
        if not name or not field:
            raise ValueError(f"Invalid structured CSV column: {column}")

        result.setdefault(name, {})[field] = column

    return result


def imported_timestamp(row, name, fields, frames):
    value = csv_text(row.get(name))
    filename_column = fields.get("Filename")
    filename = csv_text(row.get(filename_column)) if filename_column else ""

    if filename:
        if portable_basename(filename) != filename:
            raise ValueError(
                f"Timestamp '{name}' contains a path instead of a filename:\n"
                f"{filename}"
            )

        if value and Path(filename).stem != value:
            raise ValueError(
                f"Timestamp '{name}' has conflicting CSV values:\n"
                f"Stem: {value}\nFilename: {filename}"
            )

        return {
            "filename": filename,
            "frame_index": (
                frames.index(filename) + 1 if filename in frames else None
            ),
            "value": value or Path(filename).stem,
            "legacy_unresolved": filename not in frames,
        }

    # Never use FrameIndex to guess the image.
    return base.legacy_mark_from_stem(value, frames)


def parse_point_data(row, columns, frames):
    """
    Reconstruct source annotation data, not derived geometry.

    Empty historical column groups are ignored. A structure/comparison
    belongs to a row only when that row contains its identifying data.
    """
    point_groups = grouped_columns(columns, "Point::")
    comparison_groups = grouped_columns(columns, "Comparison::")

    has_point_schema = bool(point_groups or comparison_groups)
    has_calibration_schema = any(
        field in columns
        for field in ("SpacingX_mm_per_px", "SpacingY_mm_per_px")
    )

    if not has_point_schema and not has_calibration_schema:
        return None

    measurements = []
    ids = set()
    link_values = {endpoint: [] for endpoint, *_rest in FRAME_SETS}

    for name, fields in point_groups.items():
        prefix = f"Point::{name}::"
        identifier = csv_text(row.get(prefix + "MeasurementID"))

        primary_values = [
            csv_text(row.get(prefix + label + suffix))
            for _endpoint, label, _number, _color in FRAME_SETS
            for suffix in (
                "Filename",
                "X_px",
                "Y_px",
                "ImageWidth_px",
                "ImageHeight_px",
                "TimestampLink",
            )
        ]

        if not identifier:
            if any(primary_values):
                raise ValueError(
                    f"Structure '{name}' has point/link data but no "
                    "MeasurementID."
                )
            continue

        if identifier in ids:
            raise ValueError(f"Duplicate MeasurementID in CSV row: {identifier}")
        ids.add(identifier)

        structure = {
            "id": identifier,
            "name": name,
            "start": None,
            "middle": None,
            "end": None,
        }

        for endpoint, label, number, _color in FRAME_SETS:
            endpoint_prefix = prefix + label
            filename = csv_text(row.get(endpoint_prefix + "Filename"))

            coordinate_fields = (
                "X_px", "Y_px", "ImageWidth_px", "ImageHeight_px"
            )
            coordinates = [
                csv_text(row.get(endpoint_prefix + suffix))
                for suffix in coordinate_fields
            ]

            link_column = endpoint_prefix + "TimestampLink"
            if link_column in columns:
                link_values[endpoint].append(
                    csv_text(row.get(link_column))
                )

            set_number = csv_text(row.get(endpoint_prefix + "SetNumber"))
            if set_number:
                actual = require_positive_int(
                    set_number, endpoint_prefix + "SetNumber"
                )
                if actual != number:
                    raise ValueError(
                        f"Unexpected set number for {name} / {label}."
                    )

            if not filename:
                if any(coordinates):
                    raise ValueError(
                        f"{name} / {label}: coordinates have no filename."
                    )
                continue

            if portable_basename(filename) != filename:
                raise ValueError(
                    f"{name} / {label}: expected a filename, not a path."
                )

            if not all(coordinates):
                raise ValueError(
                    f"{name} / {label}: incomplete point coordinates/dimensions."
                )

            x = require_float(row.get(endpoint_prefix + "X_px"), name + " X")
            y = require_float(row.get(endpoint_prefix + "Y_px"), name + " Y")
            width = require_positive_int(
                row.get(endpoint_prefix + "ImageWidth_px"),
                name + " image width",
            )
            height = require_positive_int(
                row.get(endpoint_prefix + "ImageHeight_px"),
                name + " image height",
            )

            if not (0 <= x < width and 0 <= y < height):
                raise ValueError(
                    f"{name} / {label}: point is outside its saved image."
                )

            saved_index = csv_text(row.get(endpoint_prefix + "FrameIndex"))
            index = (
                frames.index(filename) + 1
                if filename in frames
                else (
                    require_positive_int(saved_index, name + " frame index")
                    if saved_index else None
                )
            )

            structure[endpoint] = {
                "filename": filename,
                "frame_index": index,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }

        measurements.append(structure)

    links = {}
    for endpoint, values in link_values.items():
        unique = set(values)
        if len(unique) > 1:
            raise ValueError(
                f"Conflicting {endpoint} TimestampLink values across structures."
            )
        links[endpoint] = next(iter(unique), "")

    by_id = {item["id"]: item for item in measurements}
    by_name = {item["name"]: item for item in measurements}

    comparisons = []
    comparison_ids = set()

    for name, fields in comparison_groups.items():
        prefix = f"Comparison::{name}::"
        identifier = csv_text(row.get(prefix + "ComparisonID"))

        reference_values = [
            csv_text(row.get(prefix + suffix))
            for suffix in (
                "StructureA", "StructureB",
                "StructureA_ID", "StructureB_ID",
            )
        ]

        if not identifier:
            if any(reference_values):
                raise ValueError(
                    f"Comparison '{name}' has structure references but "
                    "no ComparisonID."
                )
            continue

        if identifier in comparison_ids:
            raise ValueError(
                f"Duplicate ComparisonID in CSV row: {identifier}"
            )
        comparison_ids.add(identifier)

        resolved = []

        for label in ("A", "B"):
            structure_id = csv_text(
                row.get(prefix + f"Structure{label}_ID")
            )
            structure_name = csv_text(
                row.get(prefix + f"Structure{label}")
            )

            structure = (
                by_id.get(structure_id)
                if structure_id
                else by_name.get(structure_name)
            )

            if structure is None:
                raise ValueError(
                    f"Comparison '{name}' references an unavailable "
                    f"structure {label}."
                )

            if structure_name and structure["name"] != structure_name:
                raise ValueError(
                    f"Comparison '{name}' has inconsistent structure "
                    f"{label} name/ID."
                )

            resolved.append(structure["id"])

        if resolved[0] == resolved[1]:
            raise ValueError(
                f"Comparison '{name}' references the same structure twice."
            )

        comparisons.append({
            "id": identifier,
            "name": name,
            "a_id": resolved[0],
            "b_id": resolved[1],
        })

    spacing = []
    for field in ("SpacingX_mm_per_px", "SpacingY_mm_per_px"):
        text = csv_text(row.get(field))
        value = require_float(text, field) if text else None
        if value is not None and value <= 0:
            raise ValueError("Calibration values must be positive.")
        spacing.append(value)

    if (spacing[0] is None) != (spacing[1] is None):
        raise ValueError("The CSV must provide both calibration values.")

    result = {
        "spacing_x": spacing[0],
        "spacing_y": spacing[1],
    }

    if has_point_schema:
        result.update({
            "measurements": measurements,
            "comparisons": comparisons,
            "frame_links": links,
        })

    return result


def point_data_summary(data):
    if data is None:
        return "(not represented in this CSV)"

    lines = []

    if "measurements" in data:
        for structure in data["measurements"]:
            lines.append(
                f"{structure['name']} [{structure['id'][:12]}]"
            )
            for endpoint, label, _number, _color in FRAME_SETS:
                point = structure.get(endpoint)
                lines.append(
                    f"  {label}: "
                    + (
                        f"{point['filename']} "
                        f"({point['x']:.6f}, {point['y']:.6f})"
                        if point else "(empty)"
                    )
                )

        if not data["measurements"]:
            lines.append("No structures.")

    if "comparisons" in data:
        lines.append(
            "Comparisons: "
            + (
                ", ".join(item["name"] for item in data["comparisons"])
                or "(none)"
            )
        )

    if "frame_links" in data:
        lines.append("Links: " + repr(data["frame_links"]))

    lines.append(
        f"Calibration: X={data.get('spacing_x')!r}, "
        f"Y={data.get('spacing_y')!r}"
    )
    return "\n".join(lines)


def apply_incoming_fields(trial, incoming):
    trial["marks"].update(copy.deepcopy(incoming["marks"]))
    trial["custom"].update(copy.deepcopy(incoming["custom"]))
    trial["remarks"] = incoming["remarks"]

    if incoming.get("point_data") is not None:
        trial.update(copy.deepcopy(incoming["point_data"]))


def raw_record_details(record, incoming):
    row = record["row"]
    lines = [
        f"CSV data row: {record['row_number']}",
        f"Trial: {row['Trial']}",
        f"RecordTime: {row['RecordTime']}",
        f"Project: {row.get('Project', '')}",
        f"SourceFolder: {row.get('SourceFolder', '')}",
        f"DecisionID: {row.get('DecisionID', '')}",
        f"DecisionRevision: {row.get('DecisionRevision', '')}",
        "",
    ]

    for name, mark in incoming["marks"].items():
        lines.append(f"{name}: {base.mark_display(mark)}")

    for name, value in incoming["custom"].items():
        lines.append(f"Custom {name}: {value!r}")

    lines.extend([
        "",
        f"Remarks: {incoming['remarks']!r}",
        "",
        point_data_summary(incoming.get("point_data")),
    ])
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------

class UltrasoundAnnotator(base.UltrasoundAnnotator):

    # ------------------------------------------------------------------
    # Project loading
    # ------------------------------------------------------------------

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
                raw.get("application") != base.APP_ID
                or raw.get("version") != THREE_FRAME_VERSION
            ):
                base.backup_once(path, ".before_v4.bak")

            if raw.get("application") == "WorkSmartPointMarker":
                project["csv_path"] = ""

            self.project = project
            self.project_path = path
            self.setup_main_ui()
            self.refresh_trials()

        except Exception as exc:
            messagebox.showerror(
                "Load failed", str(exc), parent=self.root
            )

    def write_staged_project(self, staged, backup_label):
        """
        Write staged data without capture_form() overwriting imported fields.
        The caller must save/capture the outgoing form before staging.
        """
        self.cancel_pending_save()
        backup = base.timestamped_backup(
            self.project_path, backup_label
        )
        base.atomic_write(
            self.project_path,
            lambda handle: json.dump(
                staged,
                handle,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
        )
        return backup

    # ------------------------------------------------------------------
    # Parent-folder relocation
    # ------------------------------------------------------------------

    def select_parent(self):
        folder = base.filedialog.askdirectory(parent=self.root)
        if not folder:
            return

        self.stop_playback()
        self.cancel_marking()

        if not self.save_project():
            return

        destination_parent = str(Path(folder).resolve())

        try:
            directories = {
                path.name: str(path.resolve())
                for path in Path(destination_parent).iterdir()
                if path.is_dir()
            }

            staged = copy.deepcopy(self.project)
            old_parent = self.project.get("parent_folder", "")
            old_current = self.project.get("current_trial")
            mappings = []

            for trial_name, destination in sorted(
                directories.items(), key=lambda item: base.natural_key(item[0])
            ):
                existing_destination = staged["trials"].get(destination)

                candidates = [
                    key
                    for key, trial in staged["trials"].items()
                    if portable_basename(key) == trial_name
                    and not same_saved_path(key, destination)
                    and trial_has_work(trial)
                ]

                if not candidates:
                    continue

                preferred = [
                    key for key in candidates
                    if same_saved_path(
                        str(Path(key).parent), old_parent
                    )
                ]

                if len(preferred) == 1:
                    source = preferred[0]
                elif len(candidates) == 1:
                    source = candidates[0]
                else:
                    choices = [
                        (
                            key,
                            self.saved_trial_details(
                                key, staged["trials"][key]
                            ),
                            key,
                        )
                        for key in candidates
                    ]
                    choices.append((
                        "Do not relocate this trial",
                        "Keep all existing records unchanged.",
                        "__skip__",
                    ))

                    source = self.import_choice_dialog(
                        "Choose saved trial",
                        f"Several saved paths contain work for '{trial_name}'.\n"
                        "Select the record belonging to this dataset.",
                        choices,
                    )

                    if source is None:
                        return
                    if source == "__skip__":
                        continue

                if (
                    existing_destination is not None
                    and trial_has_work(existing_destination)
                ):
                    choice = self.import_choice_dialog(
                        "Destination already has annotations",
                        f"Trial '{trial_name}' has saved work at both paths.",
                        [
                            (
                                "Keep the destination trial",
                                self.saved_trial_details(
                                    destination, existing_destination
                                ),
                                "keep",
                            ),
                            (
                                "Use the saved trial from the old path",
                                self.saved_trial_details(
                                    source, staged["trials"][source]
                                )
                                + "\n\nThe destination's existing draft and "
                                "history will also be retained in history.",
                                "move",
                            ),
                        ],
                    )

                    if choice is None:
                        return
                    if choice == "keep":
                        continue

                mappings.append((source, destination))

            if mappings:
                details = "\n\n".join(
                    f"FROM: {source}\nTO:   {destination}"
                    for source, destination in mappings
                )

                approval = self.import_choice_dialog(
                    "Confirm parent-folder relocation",
                    f"{len(mappings)} saved trial(s) can be reattached.\n\n"
                    "Confirm that the destination contains the SAME trials "
                    "and unchanged image filenames—not another dataset with "
                    "similar folder names.",
                    [
                        (
                            "Relocate these saved annotations",
                            details
                            + "\n\nTimestamps, points, notes, links, calibration, "
                            "decision history and status are retained.\n"
                            "A project backup is created before committing.",
                            "relocate",
                        ),
                        (
                            "Change parent only; do not relocate annotations",
                            "Old trial records remain under their old paths.\n"
                            "Destination trials are loaded independently.",
                            "parent-only",
                        ),
                    ],
                )

                if approval is None:
                    return
                if approval == "parent-only":
                    mappings = []

            for source, destination in mappings:
                moved = copy.deepcopy(staged["trials"][source])
                previous_destination = staged["trials"].get(destination)

                if (
                    previous_destination is not None
                    and trial_has_work(previous_destination)
                ):
                    retained = copy.deepcopy(previous_destination)

                    base.append_trial_snapshot(
                        retained,
                        "destination-before-relocation",
                        retained.get("active_decision_id", ""),
                        original_source_folder=destination,
                    )

                    seen = {
                        entry.get("id")
                        for entry in moved["decisions"]
                        if entry.get("id")
                    }

                    for entry in retained["decisions"]:
                        if not entry.get("id") or entry["id"] not in seen:
                            moved["decisions"].append(copy.deepcopy(entry))
                            if entry.get("id"):
                                seen.add(entry["id"])

                    for name, entries in retained["mark_history"].items():
                        target = moved["mark_history"].setdefault(name, [])
                        known = {
                            entry.get("id") for entry in target
                            if entry.get("id")
                        }
                        for entry in entries:
                            if not entry.get("id") or entry["id"] not in known:
                                target.append(copy.deepcopy(entry))
                                if entry.get("id"):
                                    known.add(entry["id"])

                add_source_alias(moved, source, destination)
                staged["trials"][destination] = moved
                del staged["trials"][source]

            staged["parent_folder"] = destination_parent
            staged["last_trial_idx"] = 0
            staged["current_trial"] = None

            for source, destination in mappings:
                if old_current and same_saved_path(old_current, source):
                    staged["current_trial"] = destination
                    break

            if (
                staged["current_trial"] is None
                and old_current in directories.values()
            ):
                staged["current_trial"] = old_current

            backup = self.write_staged_project(
                staged, "before_parent_change"
            )

        except Exception as exc:
            messagebox.showerror(
                "Parent-folder change failed",
                f"{exc}\n\nNo staged relocation changes were applied.",
                parent=self.root,
            )
            return

        # Do not capture the old form into a relocated record.
        self.trial_key = None
        self.project = staged
        self.update_paths()
        self.refresh_trials()

        if mappings:
            messagebox.showinfo(
                "Annotations relocated",
                f"Reattached {len(mappings)} saved trial(s).\n\n"
                "CSV files were not modified."
                + (f"\n\nProject backup:\n{backup}" if backup else ""),
                parent=self.root,
            )

    @staticmethod
    def saved_trial_details(key, trial):
        lines = [
            key,
            f"Status: {trial.get('status', 'draft')}",
            f"Decision snapshots: {len(trial.get('decisions', []))}",
            "",
        ]
        lines.extend(
            f"{name}: {base.mark_display(mark)}"
            for name, mark in trial.get("marks", {}).items()
            if mark
        )
        lines.extend([
            "",
            f"Remarks: {trial.get('remarks', '')}",
            "",
            point_data_summary({
                key: copy.deepcopy(trial[key])
                for key in POINT_DATA_KEYS
                if key in trial
            }),
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    @property
    def current_pair(self):
        identifier = (
            self.project.get("point_pair", DEFAULT_PAIR_ID)
            if self.project else DEFAULT_PAIR_ID
        )
        return PAIR_BY_ID.get(
            identifier, PAIR_BY_ID[DEFAULT_PAIR_ID]
        )[1]

    def setup_main_ui(self):
        super().setup_main_ui()
        self.root.title(
            "WorkSmart | Timestamps + Three-Frame Point Marker"
        )

        def update_labels(widget):
            if isinstance(widget, ttk.Label):
                text = str(widget.cget("text"))
                if "Point Marking: S = start, E = end" in text:
                    widget.configure(
                        text=text.replace(
                            "Point Marking: S = start, E = end",
                            "Point Marking: S = start, M = middle, E = end",
                        )
                    )

            if isinstance(widget, ttk.Button):
                if str(widget.cget("text")) == "Import Old CSV...":
                    widget.configure(text="Import CSV — old or combined...")

            for child in widget.winfo_children():
                update_labels(child)

        update_labels(self.sidebar)

    def build_point_ui(self):
        pair_box = ttk.LabelFrame(
            self.point_tab, text="Displayed frame-set pair", padding=7
        )
        pair_box.pack(fill="x", pady=4)

        self.pair_combo = ttk.Combobox(
            pair_box,
            state="readonly",
            values=[item[1] for item in PAIR_SPECS],
        )
        self.pair_combo.pack(fill="x")

        identifiers = [item[0] for item in PAIR_SPECS]
        selected = self.project.get("point_pair", DEFAULT_PAIR_ID)
        self.pair_combo.current(
            identifiers.index(selected)
            if selected in identifiers
            else identifiers.index(DEFAULT_PAIR_ID)
        )
        self.pair_combo.bind(
            "<<ComboboxSelected>>", self.pair_selected
        )

        ttk.Label(
            pair_box,
            text=(
                "Select the pair for live geometry and the triangle view.\n"
                "CSV submission always exports 1–2, 2–3, and 1–3."
            ),
            wraplength=330,
        ).pack(anchor="w", pady=(5, 0))

        link_box = ttk.LabelFrame(
            self.point_tab,
            text="Point frame selection — this trial",
            padding=7,
        )
        link_box.pack(fill="x", pady=4)

        self.link_combos = {}

        for endpoint, label, number, _color in FRAME_SETS:
            ttk.Label(
                link_box, text=f"{label} / frame set {number}:"
            ).pack(anchor="w")

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
                "Set opens the linked timestamp frame. "
                "Manual uses the currently displayed frame."
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
        hotkeys = {"start": "S", "middle": "M", "end": "E"}

        for endpoint, label, number, _color in FRAME_SETS:
            box = ttk.LabelFrame(
                structure_box,
                text=(
                    f"{label} point — A{number} / B{number}"
                    f" [{hotkeys[endpoint]}]"
                ),
                padding=5,
            )
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
            justify="left",
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
            text="View aligned triangle — selected pair",
            command=self.show_triangle,
        ).pack(fill="x", pady=4)

        self.calibration_var = tk.StringVar()
        ttk.Label(
            self.point_tab,
            textvariable=self.calibration_var,
            wraplength=335,
        ).pack(anchor="w", pady=6)

    def pair_selected(self, _event=None):
        index = self.pair_combo.current()
        if not 0 <= index < len(PAIR_SPECS):
            return

        self.project["point_pair"] = PAIR_SPECS[index][0]
        self.cancel_marking()
        self.refresh_panels()
        self.draw()
        self.save_project()

    def tab_changed(self, _event=None):
        if not self.in_main:
            return

        self.cancel_marking()
        self.message_var.set(
            "Point Marking: choose a structure; "
            "S = Start, M = Middle, E = End."
            if self.point_tab_active()
            else "Timestamps: category hotkeys mark the current frame."
        )

    def comparison_dialog(self, existing=None):
        before = set(self.root.winfo_children())
        super().comparison_dialog(existing)

        old_text = (
            "Start line: A.start → B.start\n"
            "End line: A.end → B.end\n"
            "Each line's points must share a frame."
        )
        new_text = (
            "Set 1 line: A.start → B.start\n"
            "Set 2 line: A.middle → B.middle\n"
            "Set 3 line: A.end → B.end\n\n"
            "Each line's points must share a frame.\n"
            "Compare any two sets using the pair selector.\n"
            "CSV exports all three pairings."
        )

        def update_labels(widget):
            if isinstance(widget, ttk.Label):
                if str(widget.cget("text")) == old_text:
                    widget.configure(text=new_text)
            for child in widget.winfo_children():
                update_labels(child)

        for widget in self.root.winfo_children():
            if widget not in before:
                update_labels(widget)

    # ------------------------------------------------------------------
    # CSV import configuration
    # ------------------------------------------------------------------

    def configure_csv_mapping(self, staged, columns, records):
        """
        Combined timestamp metadata identifies timestamp fields.
        Unknown original flat fields retain the original classification UI.
        """
        metadata = timestamp_columns(columns)
        configured_marks = {
            name for row in staged["mark_rows"] for name in row
        }
        configured_custom = set(staged["custom_fields"])

        for name in metadata:
            if name in configured_custom:
                raise ValueError(
                    f"'{name}' is a timestamp in the CSV but a custom field "
                    "in the project. Resolve this in Config before importing."
                )

            if name not in configured_marks:
                available = next(
                    (
                        index
                        for index, row in enumerate(staged["mark_rows"])
                        if len(row) < len(base.ROW_KEYS[index])
                    ),
                    None,
                )
                if available is None:
                    raise ValueError(
                        "There are more timestamp categories than available "
                        "hotkey slots. Remove unused categories in Config."
                    )

                staged["mark_rows"][available].append(name)
                configured_marks.add(name)

        flat_columns = [
            column for column in columns
            if column not in base.RESERVED_COLUMNS
            and not column.startswith(base.COLUMN_PREFIXES)
        ]

        # Reuse the original old-CSV field classifier with just flat fields.
        synthetic_columns = (
            ["Trial", "RecordTime"] + flat_columns + ["Remarks"]
        )

        mapping_result = super().import_column_mapping(
            staged, synthetic_columns, records
        )

        if mapping_result is None:
            return None

        mapping, ignored = mapping_result

        # Metadata-only timestamp fields are also supported.
        for name in metadata:
            mapping[name] = "mark"

        base.validate_field_names(
            staged["mark_rows"], staged["custom_fields"]
        )
        return mapping, ignored, metadata

    def parse_incoming(self, record, columns, mapping, metadata, frames):
        row = record["row"]
        incoming = {
            "marks": {},
            "custom": {},
            "remarks": csv_text(row.get("Remarks")),
            "point_data": parse_point_data(row, columns, frames),
        }

        for name, kind in mapping.items():
            if kind == "mark":
                incoming["marks"][name] = imported_timestamp(
                    row, name, metadata.get(name, {}), frames
                )
            else:
                incoming["custom"][name] = csv_text(row.get(name))

        return incoming

    @staticmethod
    def csv_differences(trial, incoming):
        differences = base.UltrasoundAnnotator.import_differences(
            trial, incoming
        )

        data = incoming.get("point_data")
        if data is not None:
            previous = {
                key: copy.deepcopy(trial.get(key))
                for key in data
            }
            if previous != data:
                differences.append((
                    "points",
                    "Point annotations, comparisons, links and calibration",
                    previous,
                    data,
                ))

        return differences

    @staticmethod
    def csv_difference_details(differences):
        sections = []

        for kind, name, old, new in differences:
            if kind == "points":
                sections.append(
                    name
                    + "\n\nEXISTING:\n"
                    + point_data_summary(old)
                    + "\n\nCSV:\n"
                    + point_data_summary(new)
                )
            else:
                sections.append(
                    base.UltrasoundAnnotator.import_difference_details([
                        (kind, name, old, new)
                    ])
                )

        return "\n\n".join(sections)

    def select_import_differences(self, trial_name, working, differences):
        if not differences or not trial_has_work(working):
            return differences

        detail = self.csv_difference_details(differences)

        choice = self.import_choice_dialog(
            "Existing trial entries",
            f"'{trial_name}' already has saved work "
            f"(status: {working.get('status', 'draft')}).",
            [
                (
                    "Keep existing entries — skip this trial",
                    detail,
                    "keep",
                ),
                (
                    "Use selected CSV row",
                    detail
                    + "\n\nOnly represented fields are replaced.\n"
                    "Empty/nil values clear represented fields.\n"
                    "A combined CSV replaces its represented point data "
                    "as one group, including empty point sets.\n"
                    "The old trial remains in decision history.",
                    "csv",
                ),
                (
                    "Choose existing or CSV for each changed field",
                    detail
                    + "\n\nPoint annotations, comparisons, links and "
                    "calibration are treated as one coherent group.",
                    "fields",
                ),
            ],
        )

        if choice is None:
            return None
        if choice == "keep":
            return []
        if choice == "csv":
            return differences

        selected = []

        for difference in differences:
            kind, name, _old, _new = difference
            detail = self.csv_difference_details([difference])

            selection = self.import_choice_dialog(
                "Choose field value",
                f"Trial: {trial_name}\nField: {name}",
                [
                    ("Keep existing value", detail, "existing"),
                    ("Use CSV value", detail, "csv"),
                ],
            )

            if selection is None:
                return None
            if selection == "csv":
                selected.append(difference)

        return selected

    def apply_csv_differences(self, trial_name, working, differences):
        """
        Apply to a staged working trial.

        A final consistency check prevents a field-by-field merge from
        silently leaving points linked to a different timestamp.
        """
        for kind, name, _old, new in differences:
            if kind == "points":
                working.update(copy.deepcopy(new))

        applied = []

        for kind, name, old, new in differences:
            if kind == "points":
                applied.append((kind, name, old, new))
                continue

            if kind == "mark":
                new_filename = (
                    new.get("filename") if isinstance(new, dict) else None
                )
                endpoints = [
                    endpoint
                    for endpoint, linked in working["frame_links"].items()
                    if linked == name
                ]
                affected = [
                    (structure, endpoint)
                    for structure in working["measurements"]
                    for endpoint in endpoints
                    if structure.get(endpoint)
                    and structure[endpoint]["filename"] != new_filename
                ]

                if affected:
                    detail = (
                        f"Trial: {trial_name}\nTimestamp: {name}\n"
                        f"Existing: {base.mark_display(old)}\n"
                        f"CSV: {base.mark_display(new)}\n\n"
                        "Affected points:\n"
                        + "\n".join(
                            f"{structure['name']} — {endpoint}"
                            for structure, endpoint in affected
                        )
                    )

                    action = self.import_choice_dialog(
                        "Linked-point conflict",
                        "This timestamp change conflicts with point frames.",
                        [
                            (
                                "Keep existing timestamp",
                                detail,
                                "keep",
                            ),
                            (
                                "Use CSV timestamp and clear affected points",
                                detail
                                + "\n\nPrevious data remains in history.",
                                "clear",
                            ),
                        ],
                    )

                    if action is None:
                        return None
                    if action == "keep":
                        continue

                    for structure, endpoint in affected:
                        structure[endpoint] = None

                working["marks"][name] = copy.deepcopy(new)
                base.remember_trial_mark(working, name, new)

            elif kind == "custom":
                working["custom"][name] = new

            elif kind == "remarks":
                working["remarks"] = new

            applied.append((kind, name, old, new))

        bad_points = []

        for structure in working["measurements"]:
            for endpoint, _label, _number, _color in FRAME_SETS:
                linked = working["frame_links"].get(endpoint, "")
                point = structure.get(endpoint)
                mark = working["marks"].get(linked)
                filename = (
                    mark.get("filename") if isinstance(mark, dict) else None
                )

                if linked and point and point["filename"] != filename:
                    bad_points.append((structure, endpoint, linked))

        if bad_points:
            detail = "\n".join(
                f"{structure['name']} — {endpoint} → {linked}"
                for structure, endpoint, linked in bad_points
            )

            choice = self.import_choice_dialog(
                "Merged point links conflict",
                f"'{trial_name}': the chosen field combination leaves "
                "some points on a different frame from their linked timestamp.",
                [
                    (
                        "Keep the original trial — skip this import",
                        detail,
                        "skip",
                    ),
                    (
                        "Keep chosen fields and clear conflicting points",
                        detail
                        + "\n\nThe original trial remains in history.",
                        "clear",
                    ),
                ],
            )

            if choice is None:
                return None
            if choice == "skip":
                return []

            for structure, endpoint, _linked in bad_points:
                structure[endpoint] = None

        return applied

    # ------------------------------------------------------------------
    # Both-format CSV import
    # ------------------------------------------------------------------

    def import_old_csv(self):
        """
        Keep the original command name so the inherited UI still calls it.
        This implementation accepts both supplied CSV layouts.
        """
        if not self.in_main or not self.trial_paths:
            messagebox.showinfo(
                "Load trials first",
                "Select the parent folder containing trial image folders "
                "before importing a CSV.",
                parent=self.root,
            )
            return

        self.stop_playback()
        self.cancel_marking()

        if not self.save_project():
            return

        filename = base.filedialog.askopenfilename(
            parent=self.root,
            title="Import original or combined Timestamper CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return

        source = Path(filename).resolve()

        try:
            try:
                columns, records, combined = read_import_csv(source)
            except UnicodeDecodeError:
                encoding = base.simpledialog.askstring(
                    "CSV encoding",
                    "This CSV is not UTF-8.\n"
                    "Enter its original encoding, for example cp1252.",
                    initialvalue="cp1252",
                    parent=self.root,
                )
                if encoding is None:
                    return
                columns, records, combined = read_import_csv(
                    source, encoding.strip()
                )

            staged = copy.deepcopy(self.project)

            by_name = {}
            for key in self.trial_paths:
                by_name.setdefault(Path(key).name, []).append(key)

            grouped = {}
            unmatched = []

            for record in records:
                trial_name = record["row"]["Trial"]
                if trial_name in by_name:
                    grouped.setdefault(trial_name, []).append(record)
                else:
                    unmatched.append(record)

            if not grouped:
                raise ValueError(
                    "No CSV Trial values match the loaded trial folders.\n"
                    "Matching uses exact names, preserving leading zeros."
                )

            mapping_result = self.configure_csv_mapping(
                staged, columns, records
            )
            if mapping_result is None:
                return

            mapping, ignored, metadata = mapping_result

            # Review source identity separately from annotation conflicts.
            identity_details = []
            foreign_projects = set()

            for trial_name, trial_records in grouped.items():
                paths = by_name[trial_name]
                if len(paths) != 1:
                    continue

                key = paths[0]
                trial = staged["trials"].get(key) or new_trial()

                for record in trial_records:
                    row = record["row"]
                    previous_source = csv_text(row.get("SourceFolder"))
                    previous_project = csv_text(row.get("Project"))

                    if (
                        previous_source
                        and not source_matches_trial(
                            previous_source, key, trial
                        )
                    ):
                        identity_details.append(
                            f"CSV row {record['row_number']}, trial {trial_name}\n"
                            f"CSV:    {previous_source}\n"
                            f"Loaded: {key}"
                        )

                    if (
                        previous_project
                        and previous_project != staged["name"]
                    ):
                        foreign_projects.add(previous_project)

            if identity_details or foreign_projects:
                explanation = (
                    "Some CSV identities differ from the loaded project.\n"
                    "Confirm these rows belong to the SAME image trials.\n"
                    "Folder-name matching alone is not proof."
                )
                details = "\n\n".join(identity_details)

                if foreign_projects:
                    details += (
                        "\n\nCSV project names: "
                        + ", ".join(sorted(foreign_projects))
                        + f"\nCurrent project: {staged['name']}\n\n"
                        "Rows from another project can be imported, but their "
                        "DecisionIDs will not become active overwrite targets."
                    )

                approval = self.import_choice_dialog(
                    "Confirm CSV trial mapping",
                    explanation,
                    [
                        (
                            "Confirm these are the same trials",
                            details,
                            "confirm",
                        )
                    ],
                )
                if approval != "confirm":
                    return

            changed_names = []
            kept_names = []
            skipped_names = []
            unresolved = []
            reports = []

            for trial_name, candidates in grouped.items():
                destinations = by_name[trial_name]

                if len(destinations) == 1:
                    key = destinations[0]
                else:
                    key = self.import_choice_dialog(
                        "Choose destination trial",
                        f"Choose the destination for '{trial_name}'.",
                        [
                            (path, path, path) for path in destinations
                        ] + [
                            (
                                "Skip this trial",
                                "Leave this trial unchanged.",
                                "__skip__",
                            )
                        ],
                    )

                    if key is None:
                        return
                    if key == "__skip__":
                        skipped_names.append(trial_name)
                        continue

                frames = self.image_names(key)
                parsed = []

                for record in candidates:
                    try:
                        incoming = self.parse_incoming(
                            record, columns, mapping, metadata, frames
                        )
                    except Exception as exc:
                        raise ValueError(
                            f"Trial '{trial_name}', CSV data row "
                            f"{record['row_number']}:\n{exc}"
                        ) from exc
                    parsed.append((record, incoming))

                # Different decision identities are not silently collapsed.
                groups = {}
                for index, (record, incoming) in enumerate(parsed):
                    row = record["row"]
                    signature = json.dumps(
                        {
                            "incoming": incoming,
                            "project": csv_text(row.get("Project")),
                            "source": csv_text(row.get("SourceFolder")),
                            "decision": csv_text(row.get("DecisionID")),
                            "revision": csv_text(row.get("DecisionRevision")),
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    groups.setdefault(signature, []).append(index)

                equivalent_groups = list(groups.values())

                if len(equivalent_groups) > 1:
                    options = []

                    for group in equivalent_groups:
                        index = group[-1]
                        record, incoming = parsed[index]
                        numbers = ", ".join(
                            str(parsed[item][0]["row_number"])
                            for item in group
                        )
                        options.append((
                            f"Use row(s) {numbers} — "
                            f"{record['row']['RecordTime']}",
                            raw_record_details(record, incoming),
                            index,
                        ))

                    options.append((
                        "Skip this trial",
                        "Keep existing project entries.",
                        "__skip__",
                    ))

                    selected = self.import_choice_dialog(
                        "Multiple CSV decisions",
                        f"'{trial_name}' has different CSV submissions.\n"
                        "Choose the active decision. All source rows are "
                        "retained as provenance if this trial is imported.",
                        options,
                    )

                    if selected is None:
                        return
                    if selected == "__skip__":
                        skipped_names.append(trial_name)
                        continue

                    selected_index = selected
                else:
                    selected_index = equivalent_groups[0][-1]

                record, incoming = parsed[selected_index]
                row = record["row"]

                original = staged["trials"].get(key)
                working = (
                    copy.deepcopy(original)
                    if original is not None else new_trial()
                )

                for name, mark in list(working["marks"].items()):
                    if isinstance(mark, str):
                        working["marks"][name] = base.legacy_mark_from_stem(
                            csv_text(mark), frames
                        )

                differences = self.csv_differences(working, incoming)
                chosen = self.select_import_differences(
                    trial_name, working, differences
                )

                if chosen is None:
                    return
                if differences and not chosen:
                    kept_names.append(trial_name)
                    continue

                before = copy.deepcopy(working)

                for name, mark in working["marks"].items():
                    base.remember_trial_mark(working, name, mark)

                base.append_trial_snapshot(
                    working,
                    "draft-before-csv-import",
                    working.get("active_decision_id", ""),
                )

                applied = self.apply_csv_differences(
                    trial_name, working, chosen
                )

                if applied is None:
                    return
                if chosen and not applied:
                    kept_names.append(trial_name)
                    continue

                # Retain each distinct CSV decision as a recallable snapshot.
                # For original CSVs, source snapshots contain timestamps,
                # custom fields and notes; points were never in that format.
                for group in equivalent_groups:
                    candidate_index = group[-1]
                    candidate_record, candidate_incoming = parsed[
                        candidate_index
                    ]
                    candidate_row = candidate_record["row"]
                    snapshot_trial = new_trial()
                    apply_incoming_fields(
                        snapshot_trial, candidate_incoming
                    )
                    snapshot_trial["status"] = "draft"

                    candidate_source = csv_text(
                        candidate_row.get("SourceFolder")
                    )
                    add_source_alias(
                        snapshot_trial, candidate_source, key
                    )

                    candidate_project = csv_text(
                        candidate_row.get("Project")
                    )
                    candidate_id = (
                        csv_text(candidate_row.get("DecisionID"))
                        if candidate_project in ("", staged["name"])
                        else ""
                    )

                    revision_text = csv_text(
                        candidate_row.get("DecisionRevision")
                    )
                    candidate_revision = (
                        require_positive_int(
                            revision_text, "DecisionRevision"
                        )
                        if revision_text else None
                    )

                    working["decisions"].append({
                        "id": base.uuid.uuid4().hex,
                        "record_id": candidate_id,
                        "revision": candidate_revision,
                        "saved_at": base.now_text(),
                        "mode": (
                            "combined-csv-source"
                            if combined else "legacy-csv-source"
                        ),
                        "snapshot": base.decision_snapshot(snapshot_trial),
                        "source_csv": str(source),
                        "source_record_time": candidate_row["RecordTime"],
                        "source_data_row": candidate_record["row_number"],
                        "source_row": copy.deepcopy(candidate_row),
                        "source_project": candidate_project,
                        "source_decision_id": csv_text(
                            candidate_row.get("DecisionID")
                        ),
                    })

                accepted_source = csv_text(row.get("SourceFolder"))
                add_source_alias(working, accepted_source, key)

                source_project = csv_text(row.get("Project"))
                source_id = csv_text(row.get("DecisionID"))

                working["active_decision_id"] = (
                    source_id
                    if source_project in ("", staged["name"])
                    else ""
                )
                working["status"] = "draft"

                valid_mark = next(
                    (
                        mark.get("filename")
                        for mark in working["marks"].values()
                        if isinstance(mark, dict)
                        and mark.get("filename") in frames
                    ),
                    None,
                )

                if working.get("last_frame") not in frames:
                    working["last_frame"] = valid_mark

                for name, mark in working["marks"].items():
                    base.remember_trial_mark(working, name, mark)
                    if mark and (
                        not isinstance(mark, dict)
                        or mark.get("filename") not in frames
                    ):
                        unresolved.append(
                            f"{trial_name}: timestamp {name} — "
                            f"{base.mark_display(mark)}"
                        )

                for structure in working["measurements"]:
                    for endpoint, label, _number, _color in FRAME_SETS:
                        point = structure.get(endpoint)
                        if point and point["filename"] not in frames:
                            unresolved.append(
                                f"{trial_name}: {structure['name']} / "
                                f"{label} — {point['filename']}"
                            )

                base.append_trial_snapshot(
                    working,
                    "combined-csv-import" if combined else "legacy-csv-import",
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

                normalize_trial(working)
                staged["trials"][key] = working
                changed_names.append(trial_name)

                reports.append(
                    f"TRIAL {trial_name}: selected CSV data row "
                    f"{record['row_number']}\n"
                    + (
                        self.csv_difference_details(applied)
                        if applied
                        else "Annotation values already matched; imported "
                        "CSV decision identity/history."
                    )
                )

            summary = (
                f"Format: {'combined' if combined else 'original'} CSV\n"
                f"Trials to import: {len(changed_names)}\n"
                f"Existing trials kept: {len(kept_names)}\n"
                f"Explicitly skipped: {len(skipped_names)}\n"
                f"Unmatched CSV rows: {len(unmatched)}\n"
                f"Missing/unresolved frame references: {len(unresolved)}"
            )

            if unmatched:
                reports.append(
                    "UNMATCHED CSV ROWS:\n"
                    + "\n".join(
                        f"Row {item['row_number']}: {item['row']['Trial']}"
                        for item in unmatched
                    )
                )

            if ignored:
                reports.append(
                    "IGNORED FLAT COLUMNS:\n" + "\n".join(ignored)
                )

            if unresolved:
                reports.append(
                    "MISSING / UNRESOLVED FRAME REFERENCES:\n"
                    + "\n".join(unresolved)
                    + "\n\nOriginal values are retained. Review before export."
                )

            reports.append(
                "TIMESTAMP CATEGORY CONFIGURATION:\n"
                + "\n".join(
                    f"Row {index + 1}: {', '.join(names)}"
                    for index, names in enumerate(staged["mark_rows"])
                )
            )

            details = summary + "\n\n" + "\n\n".join(reports)

            if not changed_names:
                self.import_choice_dialog(
                    "Nothing imported",
                    summary,
                    [("Close report", details, "close")],
                )
                return

            approval = self.import_choice_dialog(
                "Review CSV import",
                summary
                + "\n\nImport saves project drafts only. "
                "No CSV file will be modified.",
                [
                    (
                        "Confirm import",
                        details
                        + "\n\nA project JSON backup will be created.",
                        "commit",
                    )
                ],
            )

            if approval != "commit":
                return

            backup = self.write_staged_project(
                staged, "before_csv_import"
            )

        except Exception as exc:
            messagebox.showerror(
                "CSV import failed",
                f"{exc}\n\nNo staged import changes were applied.",
                parent=self.root,
            )
            return

        self.project = staged
        self.measurement_index = 0
        self.comparison_index = 0
        self.build_timestamp_ui()
        self.rebuild_custom_fields()
        self.populate_form()
        self.refresh_panels()
        self.draw()

        self.message_var.set(
            f"Imported {len(changed_names)} trial(s) as drafts. "
            "CSV files unchanged."
        )

        messagebox.showinfo(
            "Import complete",
            summary
            + "\n\nImported annotations are saved as drafts.\n"
            "Review them, then use Submit / Update when ready."
            + (f"\n\nProject backup:\n{backup}" if backup else ""),
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def structure_distance(self, structure, pair=None):
        return point_pair_distance(
            structure,
            self.current_pair if pair is None else pair,
            self.trial.get("spacing_x") if self.trial else None,
            self.trial.get("spacing_y") if self.trial else None,
        )

    def comparison_structures(self, comparison):
        structures = {
            item["id"]: item for item in self.trial["measurements"]
        }
        a = structures.get(comparison["a_id"])
        b = structures.get(comparison["b_id"])

        if a is None or b is None:
            raise ValueError("A comparison references a missing structure.")
        if a["id"] == b["id"]:
            raise ValueError("Choose two different structures.")

        return a, b

    def comparison_result(self, comparison, pair=None):
        pair = self.current_pair if pair is None else pair
        first, second = pair
        a, b = self.comparison_structures(comparison)

        for endpoint in pair:
            pa = a.get(endpoint)
            pb = b.get(endpoint)

            if pa is not None and pb is not None:
                number = SET_INFO[endpoint]["number"]

                if pa["filename"] != pb["filename"]:
                    raise ValueError(
                        f"A{number} and B{number} must share a frame."
                    )
                if (
                    pa["width"], pa["height"]
                ) != (
                    pb["width"], pb["height"]
                ):
                    raise ValueError(
                        f"Set {number}: image dimensions differ."
                    )

        points = [
            a.get(first), b.get(first),
            a.get(second), b.get(second),
        ]

        if any(point is None for point in points):
            return None

        if len({(p["width"], p["height"]) for p in points}) != 1:
            raise ValueError(
                "All four points need matching image dimensions."
            )

        if any(p["filename"] not in self.frames for p in points):
            raise ValueError("A source frame is missing.")

        a1, b1, a2, b2 = points
        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        return {
            "structure_a": a,
            "structure_b": b,
            "points": points,
            "pair": pair,
            "px": base.geometry_from_points(a1, b1, a2, b2),
            "mm": (
                base.geometry_from_points(a1, b1, a2, b2, sx, sy)
                if sx is not None and sy is not None
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Live panels
    # ------------------------------------------------------------------

    def refresh_panels(self):
        if not self.in_main:
            return

        super().refresh_panels()
        structure = self.measurement

        if structure is None:
            self.displacement_var.set("Add a structure to annotate points.")
        else:
            lines = ["Structure displacement:"]

            for _identifier, _label, pair, _csv_label in PAIR_SPECS:
                lines.extend(["", pair_title(pair)])

                try:
                    distance = self.structure_distance(structure, pair)

                    if distance is None:
                        status = distance_status(structure, pair)
                        lines.append(
                            "Cannot calculate: dimensions differ."
                            if status == "dimension_mismatch"
                            else "Mark both points for this pair."
                        )
                        continue

                    dx, dy, pixels, millimeters = distance
                    lines.extend([
                        f"Distance = {pixels:.3f} px",
                        f"Δx={dx:.3f}, Δy={dy:.3f} px",
                    ])

                    if millimeters is not None:
                        lines.append(f"Distance = {millimeters:.3f} mm")

                except (ValueError, KeyError, TypeError) as exc:
                    lines.append(f"Cannot calculate: {exc}")

            self.displacement_var.set("\n".join(lines))

        if self.comparison is None:
            self.geometry_var.set("Add a comparison to calculate geometry.")
            return

        pair = self.current_pair

        try:
            a, b = self.comparison_structures(self.comparison)
            result = self.comparison_result(self.comparison, pair)

            lines = [
                f"Selected pair: {pair_title(pair)}",
                f"A: {a['name']}",
                f"B: {b['name']}",
            ]

            if result is None:
                missing = [
                    f"{structure['name']} — {SET_INFO[endpoint]['label']}"
                    for endpoint in pair
                    for structure in (a, b)
                    if structure.get(endpoint) is None
                ]
                lines.extend([
                    "", "Missing points:", *missing, "",
                    "Other complete pairs can still be exported.",
                ])
                self.geometry_var.set("\n".join(lines))
                return

            first, second = pair

            for unit in ("px", "mm"):
                values = result[unit]
                if values is None:
                    continue

                lines.extend([
                    "",
                    "Pixel results" if unit == "px" else "Calibrated results",
                    f"L1 — set {SET_INFO[first]['number']} = "
                    f"{base.fmt(values['L1'])} {unit}",
                    f"L2 — set {SET_INFO[second]['number']} = "
                    f"{base.fmt(values['L2'])} {unit}",
                    f"a = {base.fmt(values['AngleA'])}°",
                    f"b = {base.fmt(values['AngleB'])}°",
                    f"c = {base.fmt(values['AngleC'])}°",
                    f"Signed rotation = "
                    f"{base.fmt(values['SignedRotation'])}°",
                    f"Aligned opposite side = "
                    f"{base.fmt(values['OppositeSide'])} {unit}",
                ])

            lines.extend([
                "", "CSV exports every pair, not only this selection."
            ])
            self.geometry_var.set("\n".join(lines))

        except (ValueError, KeyError, TypeError) as exc:
            self.geometry_var.set(
                f"Pair {pair_title(pair)} not ready:\n{exc}"
            )

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
                text="No image loaded",
                fill="white",
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

        selected_structure = self.measurement
        selected_pair = self.current_pair

        if show_lines and selected_structure:
            first, second = selected_pair
            p1 = selected_structure.get(first)
            p2 = selected_structure.get(second)

            if visible(p1) and visible(p2):
                self.canvas.create_line(
                    *position(p1), *position(p2),
                    fill="#ffff66", width=2, dash=(5, 4),
                )

        if show_lines and self.comparison:
            by_id = {
                item["id"]: item for item in self.trial["measurements"]
            }
            a = by_id.get(self.comparison["a_id"])
            b = by_id.get(self.comparison["b_id"])

            if a is not None and b is not None:
                for endpoint, label, number, color in FRAME_SETS:
                    p1 = a.get(endpoint)
                    p2 = b.get(endpoint)

                    if not (
                        visible(p1) and visible(p2)
                        and p1["filename"] == p2["filename"]
                    ):
                        continue

                    x1, y1 = position(p1)
                    x2, y2 = position(p2)
                    style = {
                        "fill": color,
                        "width": 3 if endpoint in selected_pair else 1,
                    }

                    if p1["filename"] != current_filename:
                        style["dash"] = (5, 3)

                    self.canvas.create_line(x1, y1, x2, y2, **style)
                    self.canvas.create_text(
                        (x1 + x2) / 2,
                        (y1 + y2) / 2 - 12,
                        text=(
                            f"{self.comparison['name']} "
                            f"set {number} ({label})"
                        ),
                        fill=color,
                        font=("Arial", 10, "bold"),
                    )

        if not show_points:
            return

        label_offsets = {"start": -16, "middle": 0, "end": 16}

        for structure in self.trial["measurements"]:
            for endpoint, _label, number, color in FRAME_SETS:
                point = structure.get(endpoint)
                if not visible(point):
                    continue

                x, y = position(point)
                current = point["filename"] == current_filename
                selected = structure is selected_structure
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

                frame_number = self.frames.index(point["filename"]) + 1
                label = (
                    f"{structure['name']} {number} | F{frame_number}"
                    + ("" if current else " [ref]")
                )

                self.canvas.create_text(
                    x + 11,
                    y + label_offsets[endpoint],
                    text=label,
                    fill=color,
                    anchor="w",
                    font=("Arial", 10, "bold" if selected else "normal"),
                )

    # ------------------------------------------------------------------
    # Triangle view
    # ------------------------------------------------------------------

    def show_triangle(self):
        if self.comparison is None:
            return

        pair = self.current_pair

        try:
            result = self.comparison_result(self.comparison, pair)
            if result is None:
                raise ValueError(
                    "Mark both structures on both selected frame sets."
                )
        except (ValueError, KeyError, TypeError) as exc:
            messagebox.showinfo(
                "Triangle unavailable", str(exc), parent=self.root
            )
            return

        self.stop_playback()
        first, second = pair
        first_info, second_info = SET_INFO[first], SET_INFO[second]
        first_number = first_info["number"]
        second_number = second_info["number"]
        color_1, color_2 = first_info["color"], second_info["color"]

        unit = "mm" if result["mm"] is not None else "px"
        values = result[unit]

        window = tk.Toplevel(self.root)
        window.title(
            f"Aligned triangle — {self.comparison['name']} "
            f"— {pair_title(pair)}"
        )
        window.geometry("690x500")

        ttk.Label(
            window,
            text=(
                f"Frame sets {pair_title(pair)}\n"
                f"Origins aligned without rotation — {unit}\n"
                f"L1={base.fmt(values['L1'])} | "
                f"L2={base.fmt(values['L2'])} | "
                f"c={base.fmt(values['AngleC'])}°\n"
                f"Opposite side={base.fmt(values['OppositeSide'])} {unit}"
            ),
            padding=10,
            justify="center",
        ).pack(fill="x")

        canvas = tk.Canvas(
            window, background="#151515", highlightthickness=0
        )
        canvas.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            window,
            text=(
                "Translated-vector diagram, not image registration.\n"
                "Opposite side is not the individual structure displacement."
            ),
            padding=8,
            justify="center",
        ).pack(fill="x")

        def render(_event=None):
            canvas.delete("all")
            points = [(0.0, 0.0), values["vector_1"], values["vector_2"]]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
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
            origin, end_1, end_2 = converted

            canvas.create_line(*origin, *end_1, fill=color_1, width=3)
            canvas.create_line(*origin, *end_2, fill=color_2, width=3)
            canvas.create_line(
                *end_1, *end_2, fill="#ffff66", width=2, dash=(5, 3)
            )

            for (x, y), label, color in [
                (origin, f"A{first_number} = A{second_number}", "white"),
                (end_1, f"B{first_number}", color_1),
                (end_2, f"B{second_number} aligned", color_2),
            ]:
                canvas.create_line(
                    x - 5, y, x + 5, y, fill=color, width=2
                )
                canvas.create_line(
                    x, y - 5, x, y + 5, fill=color, width=2
                )
                canvas.create_text(x, y + 17, text=label, fill=color)

        canvas.bind("<Configure>", render)

    # ------------------------------------------------------------------
    # Export validation
    # ------------------------------------------------------------------

    def validate_trial_for_export(self):
        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        if (sx is None) != (sy is None):
            raise ValueError("Both calibration values are required.")

        if sx is not None and not all(
            isinstance(value, (int, float))
            and math.isfinite(value)
            and value > 0
            for value in (sx, sy)
        ):
            raise ValueError("Invalid calibration.")

        timestamp_names = self.timestamp_names()

        for name in timestamp_names:
            mark = self.trial["marks"].get(name)
            if mark and self.timestamp_filename(name) not in self.frames:
                raise ValueError(
                    f"Timestamp '{name}' has a missing or unresolved frame.\n"
                    "Re-mark it or clear it before submitting."
                )

        size_cache = {}

        for structure in self.trial["measurements"]:
            for endpoint, label, _number, _color in FRAME_SETS:
                point = structure.get(endpoint)
                if point is None:
                    continue

                self.validate_point(point, size_cache)
                linked = self.trial["frame_links"].get(endpoint, "")

                if linked:
                    if linked not in timestamp_names:
                        raise ValueError(
                            f"Link '{linked}' is not configured. "
                            "Switch it to Manual or add the category in Config."
                        )
                    if self.timestamp_filename(linked) != point["filename"]:
                        raise ValueError(
                            f"'{structure['name']}' {label} does not match "
                            f"timestamp '{linked}'."
                        )

            for _identifier, _label, pair, _csv_label in PAIR_SPECS:
                if all(
                    structure.get(endpoint) is not None
                    for endpoint in pair
                ):
                    if self.structure_distance(structure, pair) is None:
                        raise ValueError(
                            f"'{structure['name']}', pair {pair_title(pair)}: "
                            "image dimensions differ."
                        )

        for comparison in self.trial["comparisons"]:
            for _identifier, _label, pair, _csv_label in PAIR_SPECS:
                try:
                    self.comparison_result(comparison, pair)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"Comparison '{comparison['name']}', "
                        f"pair {pair_title(pair)}: {exc}"
                    ) from exc

    # ------------------------------------------------------------------
    # Existing three-frame output format — unchanged
    # ------------------------------------------------------------------

    def export_row(self):
        self.validate_trial_for_export()

        row = {
            "Trial": Path(self.trial_key).name,
            "RecordTime": base.datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
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

            for endpoint, label, number, _color in FRAME_SETS:
                point = structure.get(endpoint)
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
                    "TimestampLink": self.trial["frame_links"].get(
                        endpoint, ""
                    ),
                    "SetNumber": number,
                }

                for suffix, value in values.items():
                    row[prefix + label + suffix] = value

            legacy_distance = self.structure_distance(
                structure, LEGACY_PAIR
            )

            for index, label in enumerate(DISTANCE_FIELDS):
                row[prefix + label] = (
                    legacy_distance[index]
                    if legacy_distance is not None else None
                )

            for _identifier, _label, pair, csv_label in PAIR_SPECS:
                first, second = pair
                pair_prefix = prefix + csv_label + "::"

                row[pair_prefix + "FromSet"] = SET_INFO[first]["number"]
                row[pair_prefix + "ToSet"] = SET_INFO[second]["number"]
                row[pair_prefix + "Status"] = distance_status(
                    structure, pair
                )

                distance = self.structure_distance(structure, pair)

                for index, label in enumerate(DISTANCE_FIELDS):
                    row[pair_prefix + label] = (
                        distance[index] if distance is not None else None
                    )

        for comparison in self.trial["comparisons"]:
            prefix = f"Comparison::{comparison['name']}::"
            a, b = self.comparison_structures(comparison)
            legacy_result = self.comparison_result(
                comparison, LEGACY_PAIR
            )

            metadata = {
                "ComparisonID": comparison["id"],
                "StructureA": a["name"],
                "StructureB": b["name"],
                "StructureA_ID": a["id"],
                "StructureB_ID": b["id"],
                "Status": comparison_status(
                    a, b, LEGACY_PAIR, legacy_result
                ),
            }

            for label, value in metadata.items():
                row[prefix + label] = value

            for endpoint, label in [("start", "Start"), ("end", "End")]:
                point = (
                    a.get(endpoint)
                    if legacy_result is not None else None
                )
                row[prefix + label + "Filename"] = (
                    point["filename"] if point else None
                )
                row[prefix + label + "FrameIndex"] = (
                    self.frames.index(point["filename"]) + 1
                    if point else None
                )

            add_geometry_columns(row, prefix, legacy_result)

            for _identifier, _label, pair, csv_label in PAIR_SPECS:
                first, second = pair
                pair_prefix = prefix + csv_label + "::"
                result = self.comparison_result(comparison, pair)

                row[pair_prefix + "FromSet"] = SET_INFO[first]["number"]
                row[pair_prefix + "ToSet"] = SET_INFO[second]["number"]
                row[pair_prefix + "Status"] = comparison_status(
                    a, b, pair, result
                )

                for endpoint, label in [
                    (first, "From"), (second, "To")
                ]:
                    point = a.get(endpoint) or b.get(endpoint)
                    row[pair_prefix + label + "Filename"] = (
                        point["filename"] if point else None
                    )
                    row[pair_prefix + label + "FrameIndex"] = (
                        self.frames.index(point["filename"]) + 1
                        if point else None
                    )

                add_geometry_columns(row, pair_prefix, result)

        return row

    # ------------------------------------------------------------------
    # Append / overwrite with confirmed relocation identities
    # ------------------------------------------------------------------

    def csv_row_belongs_to_current_trial(self, row):
        project_name = csv_text(row.get("Project")).strip()
        if project_name and project_name != self.project["name"]:
            return False

        if row.get("Trial") != Path(self.trial_key).name:
            return False

        source = csv_text(row.get("SourceFolder"))
        if source:
            return source_matches_trial(
                source, self.trial_key, self.trial
            )

        return True

    def matching_csv_rows(self, rows):
        return [
            index for index, row in enumerate(rows)
            if self.csv_row_belongs_to_current_trial(row)
        ]

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
            columns, previous_rows = base.read_csv_table(path)

            if mode == "overwrite":
                active_id = self.trial.get("active_decision_id", "")

                if active_id:
                    matches = [
                        index
                        for index, previous in enumerate(previous_rows)
                        if previous.get("DecisionID") == active_id
                    ]

                    if len(matches) > 1:
                        raise ValueError(
                            "The CSV contains duplicate DecisionID values.\n"
                            "Repair the duplicates before overwriting."
                        )

                    if not matches:
                        raise ValueError(
                            "The recalled/imported decision is not present "
                            "in the selected CSV.\n"
                            "Select its original CSV or choose Append.\n\n"
                            "No unrelated row was overwritten."
                        )

                    target_index = matches[0]
                    target = previous_rows[target_index]

                    if not self.csv_row_belongs_to_current_trial(target):
                        raise ValueError(
                            "The matching DecisionID belongs to a different "
                            "project, trial, or unconfirmed source folder.\n"
                            "Import that CSV and confirm its folder mapping, "
                            "or choose Append."
                        )

                else:
                    matches = self.matching_csv_rows(previous_rows)
                    if not matches:
                        raise ValueError(
                            "No matching decision exists in this CSV.\n"
                            "Choose Append for the first submission, or import "
                            "the CSV to confirm an old source-folder mapping."
                        )

                    target_index = matches[-1]
                    target = previous_rows[target_index]

                record_id = (
                    target.get("DecisionID") or base.uuid.uuid4().hex
                )

                try:
                    revision = int(
                        target.get("DecisionRevision") or "1"
                    ) + 1
                except (TypeError, ValueError):
                    revision = 2

                text = (
                    f"Overwrite CSV data row {target_index + 1}?\n\n"
                    f"Trial: {target.get('Trial', '')}\n"
                    f"Previous record time: {target.get('RecordTime', '')}\n"
                    f"New revision: {revision}\n\n"
                    "Only this row will be replaced. Other rows remain.\n"
                    "A backup of the CSV will be created."
                )

                source = csv_text(target.get("SourceFolder"))

                if not source:
                    text += (
                        "\n\nLEGACY ROW: matched by trial name because "
                        "the row has no source-folder identity."
                    )
                elif not same_saved_path(source, self.trial_key):
                    text += (
                        "\n\nCONFIRMED RELOCATED SOURCE:\n"
                        f"{source}\n→ {self.trial_key}\n\n"
                        "The replacement row will use the current source path."
                    )

                if not messagebox.askyesno(
                    "Confirm overwrite", text, parent=self.root
                ):
                    return

            else:
                record_id = base.uuid.uuid4().hex
                revision = 1

                if not messagebox.askyesno(
                    "Append decision",
                    f"Append a new decision row for "
                    f"'{Path(self.trial_key).name}'?\n\n"
                    "Existing CSV rows will remain unchanged.",
                    parent=self.root,
                ):
                    return

            row["DecisionID"] = record_id
            row["DecisionRevision"] = revision

            added_columns = [
                column for column in row if column not in columns
            ]

            if target_index is not None:
                base.timestamped_backup(path)
            elif columns and added_columns:
                base.backup_once(path, ".before_merge.bak")

            columns.extend(added_columns)

            if target_index is None:
                output_rows = previous_rows + [row]
            else:
                output_rows = list(previous_rows)
                old_row = previous_rows[target_index]

                replacement = {
                    column: (
                        ""
                        if column.startswith(base.COLUMN_PREFIXES)
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

            base.write_csv_table(path, columns, output_rows)

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
                "Use Save Project to retry. Do not append again merely "
                "to retry the project save.",
                parent=self.root,
            )
            return

        self.message_var.set(
            f"Decision {'appended' if mode == 'append' else 'updated'}: "
            f"{record_id[:12]}, revision {revision}."
        )

        if self.advance_var.get():
            self.advance_trial()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def handle_key(self, event):
        if (
            self.in_main
            and self.root.grab_current() is None
            and event.keysym.lower() == "m"
            and self.point_tab_active()
        ):
            focus = self.root.focus_get()

            if (
                focus is not None
                and focus.winfo_toplevel() != self.root
            ):
                return

            if self.is_typing():
                return
            if event.state & 0x0004 or event.state & 0x0008:
                return

            self.arm("middle")
            return "break"

        return super().handle_key(event)


# ----------------------------------------------------------------------
# Self-tests — no GUI required
# ----------------------------------------------------------------------

def run_three_frame_self_tests():
    base.run_geometry_self_tests()

    with tempfile.TemporaryDirectory(
        prefix="worksmart_three_frame_test_"
    ) as temporary:
        folder = Path(temporary).resolve()
        filenames = ["000.png", "001.png", "002.png"]

        for filename in filenames:
            Image.new("RGB", (32, 32), color="black").save(
                folder / filename
            )

        def point(filename, x, y):
            return {
                "filename": filename,
                "frame_index": filenames.index(filename) + 1,
                "x": float(x),
                "y": float(y),
                "width": 32,
                "height": 32,
            }

        trial = new_trial()
        a, b = trial["measurements"]

        for index, (endpoint, _label, _number, _color) in enumerate(
            FRAME_SETS
        ):
            a[endpoint] = point(filenames[index], 10, 20)

        b["start"] = point(filenames[0], 20, 20)
        b["middle"] = point(filenames[1], 10, 10)
        b["end"] = point(filenames[2], 0, 20)

        trial["spacing_x"] = 2.0
        trial["spacing_y"] = 1.0

        trial["marks"]["On"] = {
            "filename": filenames[0],
            "frame_index": 1,
            "value": "000",
        }
        trial["marks"]["Max"] = {
            "filename": filenames[1],
            "frame_index": 2,
            "value": "001",
        }
        trial["marks"]["Off"] = {
            "filename": filenames[2],
            "frame_index": 3,
            "value": "002",
        }
        trial["frame_links"] = {
            "start": "On",
            "middle": "Max",
            "end": "Off",
        }

        project = new_project("SelfTest")
        trial_key = str(folder)
        project["trials"][trial_key] = trial
        project["point_pair"] = "start:middle"

        app = object.__new__(UltrasoundAnnotator)
        app.project = project
        app.trial_key = trial_key
        app.frames = filenames

        comparison = trial["comparisons"][0]
        expected_angles = {
            "Pair12": 90.0,
            "Pair23": 90.0,
            "Pair13": 180.0,
        }

        for _identifier, _label, pair, csv_label in PAIR_SPECS:
            result = app.comparison_result(comparison, pair)
            assert result is not None
            assert math.isclose(
                result["px"]["AngleC"],
                expected_angles[csv_label],
                abs_tol=1e-10,
            )

        row = app.export_row()
        prefix = "Comparison::A-B::"

        for csv_label, angle in expected_angles.items():
            assert math.isclose(
                row[prefix + csv_label + "::AngleC_px_deg"],
                angle,
                abs_tol=1e-10,
            )
            assert row[prefix + csv_label + "::Status"] == "complete"

        assert math.isclose(row[prefix + "AngleC_px_deg"], 180.0)
        assert math.isclose(row[prefix + "Pair12::L1_mm"], 20.0)
        assert math.isclose(row[prefix + "Pair12::L2_mm"], 10.0)

        assert math.isclose(
            row["Point::Structure B::Pair13::Distance_px"], 20.0
        )
        assert math.isclose(
            row["Point::Structure B::Distance_px"], 20.0
        )

        # Combined CSV round trip, including point reconstruction.
        row["DecisionID"] = "test-decision"
        row["DecisionRevision"] = 2

        csv_path = folder / "combined.csv"
        base.write_csv_table(csv_path, list(row), [row])
        columns, records, combined = read_import_csv(csv_path)

        assert combined
        assert len(records) == 1

        metadata = timestamp_columns(columns)
        mapping = {"On": "mark", "Max": "mark", "Off": "mark"}
        incoming = app.parse_incoming(
            records[0], columns, mapping, metadata, filenames
        )

        assert incoming["marks"]["On"]["value"] == "000"
        assert incoming["marks"]["On"]["filename"] == "000.png"
        assert incoming["marks"]["On"]["frame_index"] == 1
        assert incoming["point_data"]["measurements"] == trial["measurements"]
        assert incoming["point_data"]["comparisons"] == trial["comparisons"]
        assert incoming["point_data"]["frame_links"] == trial["frame_links"]
        assert incoming["point_data"]["spacing_x"] == 2.0

        imported_trial = new_trial()
        apply_incoming_fields(imported_trial, incoming)
        app.project["trials"][trial_key] = imported_trial

        round_trip = app.export_row()
        assert math.isclose(
            round_trip[prefix + "Pair23::AngleC_px_deg"], 90.0
        )
        assert math.isclose(
            round_trip[prefix + "Pair13::AngleC_px_deg"], 180.0
        )

        app.project["trials"][trial_key] = trial

        # Original CSV: stems and trial names retain leading zeros.
        old_path = folder / "original.csv"
        old_columns = ["Trial", "RecordTime", "On", "Max", "Off", "Remarks"]
        old_rows = [{
            "Trial": "01",
            "RecordTime": "2026-01-01 00:00:00",
            "On": "000",
            "Max": "001",
            "Off": "nil",
            "Remarks": "Example, with comma",
        }]
        base.write_csv_table(old_path, old_columns, old_rows)

        old_columns_read, old_records, old_combined = read_import_csv(
            old_path
        )
        assert not old_combined
        assert old_records[0]["row"]["Trial"] == "01"

        old_incoming = app.parse_incoming(
            old_records[0],
            old_columns_read,
            mapping,
            {},
            filenames,
        )
        assert old_incoming["marks"]["On"]["filename"] == "000.png"
        assert old_incoming["marks"]["On"]["frame_index"] == 1
        assert old_incoming["marks"]["Off"] is None
        assert old_incoming["point_data"] is None
        assert old_incoming["remarks"] == "Example, with comma"

        # Missing explicit filenames remain unresolved, not index-guessed.
        missing = imported_timestamp(
            {
                "On": "087",
                "Timestamp::On::Filename": "087.png",
                "Timestamp::On::FrameIndex": "1",
            },
            "On",
            {
                "Filename": "Timestamp::On::Filename",
                "FrameIndex": "Timestamp::On::FrameIndex",
            },
            filenames,
        )
        assert missing["filename"] == "087.png"
        assert missing["frame_index"] is None
        assert missing["legacy_unresolved"]

        # Old accumulated blank column groups do not create phantom structures.
        sparse_row = dict(records[0]["row"])
        sparse_columns = list(columns)
        extra = "Point::Former structure::MeasurementID"
        sparse_columns.append(extra)
        sparse_row[extra] = ""
        sparse_data = parse_point_data(
            sparse_row, sparse_columns, filenames
        )
        assert len(sparse_data["measurements"]) == 2

        # Missing third set still allows valid pair 1–2.
        saved_a_end, saved_b_end = a["end"], b["end"]
        a["end"] = None
        b["end"] = None

        partial_row = app.export_row()
        assert partial_row[prefix + "Pair12::Status"] == "complete"
        assert partial_row[prefix + "Pair23::Status"] == "incomplete"
        assert partial_row[prefix + "Pair13::AngleC_px_deg"] is None

        a["end"], b["end"] = saved_a_end, saved_b_end

        # Zero-length lines do not fabricate angles.
        saved_b_middle = b["middle"]
        b["middle"] = copy.deepcopy(a["middle"])
        zero_row = app.export_row()
        assert (
            zero_row[prefix + "Pair12::Status"]
            == "zero_length_line_angle_undefined"
        )
        assert zero_row[prefix + "Pair12::AngleC_px_deg"] is None
        b["middle"] = saved_b_middle

        # Conflicting A/B frames must fail.
        saved_filename = b["middle"]["filename"]
        b["middle"]["filename"] = filenames[0]
        try:
            app.export_row()
        except ValueError:
            pass
        else:
            raise AssertionError("Conflicting point frames were accepted.")
        finally:
            b["middle"]["filename"] = saved_filename

        # Version 3 migration preserves Start/End and adds empty Middle.
        legacy_trial = copy.deepcopy(trial)
        for structure in legacy_trial["measurements"]:
            structure.pop("middle", None)
        legacy_trial["frame_links"].pop("middle", None)

        legacy_project = new_project("Legacy")
        legacy_project["version"] = 3
        legacy_project.pop("point_pair", None)
        legacy_project["trials"] = {trial_key: legacy_trial}

        original_end = copy.deepcopy(
            legacy_trial["measurements"][0]["end"]
        )
        migrated = normalize_project(legacy_project, "Legacy")
        migrated_trial = migrated["trials"][trial_key]

        assert migrated["version"] == THREE_FRAME_VERSION
        assert migrated_trial["measurements"][0]["end"] == original_end
        assert migrated_trial["measurements"][0]["middle"] is None
        assert migrated_trial["frame_links"]["middle"] == ""
        assert legacy_project["version"] == 3
        assert "middle" not in legacy_trial["measurements"][0]

        reopened = normalize_project(
            copy.deepcopy(project), "SelfTest"
        )
        assert (
            reopened["trials"][trial_key]["measurements"][1]["middle"]
            == saved_b_middle
        )

        middle_only = new_trial()
        middle_only["measurements"][0]["middle"] = point(
            filenames[1], 10, 20
        )
        assert trial_has_work(middle_only)

        # Confirmed source aliases permit safe overwrite matching.
        old_source = "/old/dataset/" + folder.name
        foreign_source = "/unrelated/dataset/" + folder.name

        candidate = {
            "Trial": folder.name,
            "Project": "SelfTest",
            "SourceFolder": old_source,
        }

        assert not app.csv_row_belongs_to_current_trial(candidate)
        add_source_alias(trial, old_source, trial_key)
        assert app.csv_row_belongs_to_current_trial(candidate)

        candidate["SourceFolder"] = foreign_source
        assert not app.csv_row_belongs_to_current_trial(candidate)

        candidate["SourceFolder"] = old_source
        candidate["Project"] = "AnotherProject"
        assert not app.csv_row_belongs_to_current_trial(candidate)

        assert same_saved_path(
            r"Z:\dataset\01", "z:/dataset/01"
        )
        assert not same_saved_path("/data/A", "/data/a")

    print(
        "Three-frame geometry, export, CSV parsing/import reconstruction, "
        "leading-zero handling, missing-frame handling, source matching, "
        "partial-data validation and migration self-tests passed."
    )


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_three_frame_self_tests()
    else:
        root = tk.Tk()
        app = UltrasoundAnnotator(root)
        root.mainloop()
