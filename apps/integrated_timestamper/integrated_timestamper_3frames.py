"""
WorkSmart Integrated Timestamper — Three-Frame Extension

Required companion:
    integrated_timestamper.py
    (the original script, unchanged, in this same folder)

Run:
    python integrated_timestamper_3frames.py

Run geometry/export/migration tests:
    python integrated_timestamper_3frames.py --self-test

Frame sets:
    Set 1 = Start
    Set 2 = Middle
    Set 3 = End

Point-marking hotkeys:
    S = Start
    M = Middle
    E = End

The selected pair controls the live comparison and triangle viewer.
CSV submission ALWAYS exports all three pairs.

Existing Start/End data and original CSV columns retain their meaning:
    legacy Start–End results = Set 1–Set 3.
"""

import copy
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path


# ----------------------------------------------------------------------
# Load the original application without running its main block.
# ----------------------------------------------------------------------

ORIGINAL_SCRIPT = Path(__file__).resolve().with_name(
    "integrated_timestamper.py"
)

if not ORIGINAL_SCRIPT.is_file():
    raise SystemExit(
        "Required original script was not found:\n"
        f"{ORIGINAL_SCRIPT}\n\n"
        "Save your original, unchanged script as "
        "'integrated_timestamper.py' in this same folder."
    )

if ORIGINAL_SCRIPT == Path(__file__).resolve():
    raise SystemExit(
        "The extension and original script must have different filenames."
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


# ----------------------------------------------------------------------
# Extend the original data helpers.
#
# These assignments change the imported module only in memory.
# The original Python file is never modified.
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

    # Historical snapshots remain untouched until recalled. The original
    # recall function calls this normalizer when restoring a snapshot.
    return trial


def normalize_project(raw, name):
    if not isinstance(raw, dict):
        raise ValueError("The project file must contain a JSON object.")

    incoming = copy.deepcopy(raw)

    if incoming.get("application") == base.APP_ID:
        version = incoming.get("version")

        if version not in (2, 3, THREE_FRAME_VERSION):
            raise ValueError("Unsupported integrated project version.")

        # Reuse the original validator, which recognizes versions 2 and 3.
        # It does not discard the new fields.
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
# Shared three-frame helpers
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
        point_1["width"],
        point_1["height"],
    ) != (
        point_2["width"],
        point_2["height"],
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

    if len({
        (point["width"], point["height"])
        for point in points
    }) != 1:
        return "dimension_mismatch"

    return "complete"


def comparison_status(a, b, pair, result):
    if result is not None:
        if result["px"]["AngleC"] is None:
            return "zero_length_line_angle_undefined"
        return "complete"

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
# Extended application
# ----------------------------------------------------------------------

class UltrasoundAnnotator(base.UltrasoundAnnotator):

    # ------------------------------------------------------------------
    # Project migration
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
                "Load failed",
                str(exc),
                parent=self.root,
            )

    # The inherited import_project() uses the patched normalizer above.
    # It still creates a new project and leaves the source JSON unchanged.

    # ------------------------------------------------------------------
    # Pair selection and UI
    # ------------------------------------------------------------------

    @property
    def current_pair(self):
        identifier = (
            self.project.get("point_pair", DEFAULT_PAIR_ID)
            if self.project
            else DEFAULT_PAIR_ID
        )

        return PAIR_BY_ID.get(
            identifier,
            PAIR_BY_ID[DEFAULT_PAIR_ID],
        )[1]

    def setup_main_ui(self):
        super().setup_main_ui()

        self.root.title(
            "WorkSmart | Timestamps + Three-Frame Point Marker"
        )

        # Update the original help label without rebuilding the rest of
        # the existing interface.
        def update_help(widget):
            if isinstance(widget, ttk.Label):
                text = str(widget.cget("text"))

                if "Point Marking: S = start, E = end" in text:
                    widget.configure(
                        text=text.replace(
                            "Point Marking: S = start, E = end",
                            "Point Marking: S = start, M = middle, E = end",
                        )
                    )

            for child in widget.winfo_children():
                update_help(child)

        update_help(self.sidebar)

    def build_point_ui(self):
        pair_box = ttk.LabelFrame(
            self.point_tab,
            text="Displayed frame-set pair",
            padding=7,
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
            "<<ComboboxSelected>>",
            self.pair_selected,
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
                link_box,
                text=f"{label} / frame set {number}:",
            ).pack(anchor="w")

            combo = ttk.Combobox(
                link_box,
                state="readonly",
            )
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

        self.button_row(structure_box, [
            ("Add", self.add_structure),
            ("Rename", self.rename_structure),
            ("Delete", self.delete_structure),
        ])

        self.point_vars = {}
        hotkeys = {
            "start": "S",
            "middle": "M",
            "end": "E",
        }

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
                box,
                textvariable=variable,
                wraplength=315,
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
        # Keep all original dialog validation and save behavior.
        # Only extend the explanatory label.
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
            item["id"]: item
            for item in self.trial["measurements"]
        }

        a = structures.get(comparison["a_id"])
        b = structures.get(comparison["b_id"])

        if a is None or b is None:
            raise ValueError(
                "A comparison references a missing structure."
            )

        if a["id"] == b["id"]:
            raise ValueError("Choose two different structures.")

        return a, b

    def comparison_result(self, comparison, pair=None):
        pair = self.current_pair if pair is None else pair
        first, second = pair

        a, b = self.comparison_structures(comparison)

        # Even an incomplete pair must not silently contain conflicting
        # A/B frame assignments within an already marked line.
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
            a.get(first),
            b.get(first),
            a.get(second),
            b.get(second),
        ]

        # Missing annotations are permitted. Other complete pairs remain
        # available and incomplete pair results are exported as blank.
        if any(point is None for point in points):
            return None

        if len({
            (point["width"], point["height"])
            for point in points
        }) != 1:
            raise ValueError(
                "All four points need matching image dimensions."
            )

        if any(
            point["filename"] not in self.frames
            for point in points
        ):
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
                base.geometry_from_points(
                    a1, b1, a2, b2, sx, sy
                )
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

        # Retain original timestamp labels, trial progress, selectors,
        # point labels, calibration display, and history information.
        super().refresh_panels()

        structure = self.measurement

        if structure is None:
            self.displacement_var.set(
                "Add a structure to annotate points."
            )
        else:
            lines = ["Structure displacement:"]

            for _identifier, _label, pair, _csv_label in PAIR_SPECS:
                lines.append("")
                lines.append(pair_title(pair))

                try:
                    distance = self.structure_distance(
                        structure,
                        pair,
                    )

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
                        lines.append(
                            f"Distance = {millimeters:.3f} mm"
                        )

                except (ValueError, KeyError, TypeError) as exc:
                    lines.append(f"Cannot calculate: {exc}")

            self.displacement_var.set("\n".join(lines))

        if self.comparison is None:
            self.geometry_var.set(
                "Add a comparison to calculate geometry."
            )
            return

        pair = self.current_pair

        try:
            a, b = self.comparison_structures(self.comparison)
            result = self.comparison_result(
                self.comparison,
                pair,
            )

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
                    "",
                    "Missing points:",
                    *missing,
                    "",
                    "Other complete pairs can still be exported.",
                ])

                self.geometry_var.set("\n".join(lines))
                return

            first, second = pair
            first_number = SET_INFO[first]["number"]
            second_number = SET_INFO[second]["number"]

            for unit in ("px", "mm"):
                values = result[unit]

                if values is None:
                    continue

                lines.extend([
                    "",
                    (
                        "Pixel results"
                        if unit == "px"
                        else "Calibrated results"
                    ),
                    (
                        f"L1 — set {first_number} = "
                        f"{base.fmt(values['L1'])} {unit}"
                    ),
                    (
                        f"L2 — set {second_number} = "
                        f"{base.fmt(values['L2'])} {unit}"
                    ),
                    f"a = {base.fmt(values['AngleA'])}°",
                    f"b = {base.fmt(values['AngleB'])}°",
                    f"c = {base.fmt(values['AngleC'])}°",
                    (
                        "Signed rotation = "
                        f"{base.fmt(values['SignedRotation'])}°"
                    ),
                    (
                        "Aligned opposite side = "
                        f"{base.fmt(values['OppositeSide'])} {unit}"
                    ),
                ])

            lines.extend([
                "",
                "CSV exports every pair, not only this selection.",
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

        ox = (cw - dw) / 2
        oy = (ch - dh) / 2

        sx = dw / width
        sy = dh / height

        self.transform = (ox, oy, sx, sy)

        key = (id(self.image), dw, dh)

        if key != self.render_key:
            self.photo = ImageTk.PhotoImage(
                self.image.resize(
                    (dw, dh),
                    Image.Resampling.LANCZOS,
                )
            )
            self.render_key = key

        self.canvas.create_image(
            ox,
            oy,
            image=self.photo,
            anchor="nw",
        )

        current_filename = self.frames[self.frame_index]

        show_references = self.reference_var.get()
        show_lines = self.show_lines_var.get()
        show_points = self.show_points_var.get()

        def visible(point):
            return (
                point is not None
                and (
                    point["width"],
                    point["height"],
                ) == (
                    width,
                    height,
                )
                and point["filename"] in self.frames
                and (
                    point["filename"] == current_filename
                    or show_references
                )
            )

        def position(point):
            return (
                ox + point["x"] * sx,
                oy + point["y"] * sy,
            )

        selected_structure = self.measurement
        selected_pair = self.current_pair

        # Yellow displacement line follows the selected frame-set pair.
        if show_lines and selected_structure:
            first, second = selected_pair

            p1 = selected_structure.get(first)
            p2 = selected_structure.get(second)

            if visible(p1) and visible(p2):
                self.canvas.create_line(
                    *position(p1),
                    *position(p2),
                    fill="#ffff66",
                    width=2,
                    dash=(5, 4),
                )

        # Show the selected comparison's available A–B lines on all three
        # frame sets. The selected pair receives greater line weight.
        if show_lines and self.comparison:
            by_id = {
                item["id"]: item
                for item in self.trial["measurements"]
            }

            a = by_id.get(self.comparison["a_id"])
            b = by_id.get(self.comparison["b_id"])

            if a is not None and b is not None:
                for endpoint, label, number, color in FRAME_SETS:
                    p1 = a.get(endpoint)
                    p2 = b.get(endpoint)

                    if not (
                        visible(p1)
                        and visible(p2)
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

                    self.canvas.create_line(
                        x1,
                        y1,
                        x2,
                        y2,
                        **style,
                    )

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

        label_offsets = {
            "start": -16,
            "middle": 0,
            "end": 16,
        }

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
                    x - length,
                    y,
                    x + length,
                    y,
                    **style,
                )

                self.canvas.create_line(
                    x,
                    y - length,
                    x,
                    y + length,
                    **style,
                )

                frame_number = (
                    self.frames.index(point["filename"]) + 1
                )

                label = (
                    f"{structure['name']} {number}"
                    f" | F{frame_number}"
                    + ("" if current else " [ref]")
                )

                self.canvas.create_text(
                    x + 11,
                    y + label_offsets[endpoint],
                    text=label,
                    fill=color,
                    anchor="w",
                    font=(
                        "Arial",
                        10,
                        "bold" if selected else "normal",
                    ),
                )

    # ------------------------------------------------------------------
    # Aligned triangle
    # ------------------------------------------------------------------

    def show_triangle(self):
        if self.comparison is None:
            return

        pair = self.current_pair

        try:
            result = self.comparison_result(
                self.comparison,
                pair,
            )

            if result is None:
                raise ValueError(
                    "Mark both structures on both selected frame sets."
                )

        except (ValueError, KeyError, TypeError) as exc:
            messagebox.showinfo(
                "Triangle unavailable",
                str(exc),
                parent=self.root,
            )
            return

        self.stop_playback()

        first, second = pair

        first_info = SET_INFO[first]
        second_info = SET_INFO[second]

        first_number = first_info["number"]
        second_number = second_info["number"]

        color_1 = first_info["color"]
        color_2 = second_info["color"]

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
                f"Opposite side="
                f"{base.fmt(values['OppositeSide'])} {unit}"
            ),
            padding=10,
            justify="center",
        ).pack(fill="x")

        canvas = tk.Canvas(
            window,
            background="#151515",
            highlightthickness=0,
        )
        canvas.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=10,
        )

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

            points = [
                (0.0, 0.0),
                values["vector_1"],
                values["vector_2"],
            ]

            xs = [point[0] for point in points]
            ys = [point[1] for point in points]

            width = max(100, canvas.winfo_width())
            height = max(100, canvas.winfo_height())

            scale = min(
                max(1, width - 100)
                / max(max(xs) - min(xs), 1e-9),

                max(1, height - 100)
                / max(max(ys) - min(ys), 1e-9),
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

            canvas.create_line(
                *origin,
                *end_1,
                fill=color_1,
                width=3,
            )

            canvas.create_line(
                *origin,
                *end_2,
                fill=color_2,
                width=3,
            )

            canvas.create_line(
                *end_1,
                *end_2,
                fill="#ffff66",
                width=2,
                dash=(5, 3),
            )

            for (x, y), label, color in [
                (
                    origin,
                    f"A{first_number} = A{second_number}",
                    "white",
                ),
                (
                    end_1,
                    f"B{first_number}",
                    color_1,
                ),
                (
                    end_2,
                    f"B{second_number} aligned",
                    color_2,
                ),
            ]:
                canvas.create_line(
                    x - 5,
                    y,
                    x + 5,
                    y,
                    fill=color,
                    width=2,
                )

                canvas.create_line(
                    x,
                    y - 5,
                    x,
                    y + 5,
                    fill=color,
                    width=2,
                )

                canvas.create_text(
                    x,
                    y + 17,
                    text=label,
                    fill=color,
                )

        canvas.bind("<Configure>", render)

    # ------------------------------------------------------------------
    # Export validation
    # ------------------------------------------------------------------

    def validate_trial_for_export(self):
        sx = self.trial.get("spacing_x")
        sy = self.trial.get("spacing_y")

        if (sx is None) != (sy is None):
            raise ValueError(
                "Both calibration values are required."
            )

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

            if (
                mark
                and self.timestamp_filename(name) not in self.frames
            ):
                raise ValueError(
                    f"Timestamp '{name}' has a missing or unresolved frame.\n"
                    "Re-mark it or clear it before submitting."
                )

        size_cache = {}

        for structure in self.trial["measurements"]:
            for endpoint, label, _number, _color in FRAME_SETS:
                point = structure.get(endpoint)

                # Partial annotation is allowed. Missing pairwise results
                # receive an explicit status and blank numerical values.
                if point is None:
                    continue

                self.validate_point(point, size_cache)

                linked = self.trial["frame_links"].get(
                    endpoint,
                    "",
                )

                if linked:
                    if linked not in timestamp_names:
                        raise ValueError(
                            f"Link '{linked}' is not configured. "
                            "Switch it to Manual or add the category "
                            "in Config."
                        )

                    if (
                        self.timestamp_filename(linked)
                        != point["filename"]
                    ):
                        raise ValueError(
                            f"'{structure['name']}' {label} does not "
                            f"match timestamp '{linked}'."
                        )

            for _identifier, _label, pair, _csv_label in PAIR_SPECS:
                if all(
                    structure.get(endpoint) is not None
                    for endpoint in pair
                ):
                    if self.structure_distance(structure, pair) is None:
                        raise ValueError(
                            f"'{structure['name']}', "
                            f"pair {pair_title(pair)}: "
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
    # Combined CSV row
    #
    # Original timestamp, notes, calibration and identity columns remain.
    # Original point/comparison columns still mean Start → End.
    # New Pair12/Pair23/Pair13 columns are added for all pairwise results.
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

            row[name] = (
                Path(filename).stem
                if filename
                else "nil"
            )

        for name in self.project["custom_fields"]:
            value = self.trial["custom"].get(name, "")
            row[name] = str(value).strip() or "nil"

        row["Remarks"] = (
            self.trial.get("remarks", "").strip() or "nil"
        )

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
                if filename in self.frames
                else None
            )

        for structure in self.trial["measurements"]:
            prefix = f"Point::{structure['name']}::"
            row[prefix + "MeasurementID"] = structure["id"]

            # Retain original Start/End column names and add Middle.
            for endpoint, label, number, _color in FRAME_SETS:
                point = structure.get(endpoint)

                values = {
                    "Filename": (
                        point["filename"] if point else None
                    ),
                    "FrameIndex": (
                        self.frames.index(point["filename"]) + 1
                        if point
                        else None
                    ),
                    "X_px": point["x"] if point else None,
                    "Y_px": point["y"] if point else None,
                    "ImageWidth_px": (
                        point["width"] if point else None
                    ),
                    "ImageHeight_px": (
                        point["height"] if point else None
                    ),
                    "TimestampLink": (
                        self.trial["frame_links"].get(endpoint, "")
                    ),
                    "SetNumber": number,
                }

                for suffix, value in values.items():
                    row[prefix + label + suffix] = value

            # Preserve the meaning of original displacement columns.
            legacy_distance = self.structure_distance(
                structure,
                LEGACY_PAIR,
            )

            for index, label in enumerate(DISTANCE_FIELDS):
                row[prefix + label] = (
                    legacy_distance[index]
                    if legacy_distance is not None
                    else None
                )

            # Export every pair, regardless of the displayed selection.
            for _identifier, _label, pair, csv_label in PAIR_SPECS:
                first, second = pair
                pair_prefix = prefix + csv_label + "::"

                row[pair_prefix + "FromSet"] = (
                    SET_INFO[first]["number"]
                )
                row[pair_prefix + "ToSet"] = (
                    SET_INFO[second]["number"]
                )
                row[pair_prefix + "Status"] = distance_status(
                    structure,
                    pair,
                )

                distance = self.structure_distance(
                    structure,
                    pair,
                )

                for index, label in enumerate(DISTANCE_FIELDS):
                    row[pair_prefix + label] = (
                        distance[index]
                        if distance is not None
                        else None
                    )

        for comparison in self.trial["comparisons"]:
            prefix = f"Comparison::{comparison['name']}::"

            a, b = self.comparison_structures(comparison)

            # Explicitly use Start → End for original columns.
            # Changing the live selector never changes their meaning.
            legacy_result = self.comparison_result(
                comparison,
                LEGACY_PAIR,
            )

            metadata = {
                "ComparisonID": comparison["id"],
                "StructureA": a["name"],
                "StructureB": b["name"],
                "StructureA_ID": a["id"],
                "StructureB_ID": b["id"],
                "Status": comparison_status(
                    a,
                    b,
                    LEGACY_PAIR,
                    legacy_result,
                ),
            }

            for label, value in metadata.items():
                row[prefix + label] = value

            for endpoint, label in [
                ("start", "Start"),
                ("end", "End"),
            ]:
                point = (
                    a.get(endpoint)
                    if legacy_result is not None
                    else None
                )

                row[prefix + label + "Filename"] = (
                    point["filename"] if point else None
                )
                row[prefix + label + "FrameIndex"] = (
                    self.frames.index(point["filename"]) + 1
                    if point
                    else None
                )

            add_geometry_columns(
                row,
                prefix,
                legacy_result,
            )

            # New explicitly labeled pairwise columns.
            for _identifier, _label, pair, csv_label in PAIR_SPECS:
                first, second = pair
                pair_prefix = prefix + csv_label + "::"

                result = self.comparison_result(
                    comparison,
                    pair,
                )

                row[pair_prefix + "FromSet"] = (
                    SET_INFO[first]["number"]
                )
                row[pair_prefix + "ToSet"] = (
                    SET_INFO[second]["number"]
                )
                row[pair_prefix + "Status"] = comparison_status(
                    a,
                    b,
                    pair,
                    result,
                )

                for endpoint, label in [
                    (first, "From"),
                    (second, "To"),
                ]:
                    # If only one structure is marked on a set, retain
                    # its frame metadata while leaving geometry blank.
                    point = a.get(endpoint) or b.get(endpoint)

                    row[pair_prefix + label + "Filename"] = (
                        point["filename"] if point else None
                    )
                    row[pair_prefix + label + "FrameIndex"] = (
                        self.frames.index(point["filename"]) + 1
                        if point
                        else None
                    )

                add_geometry_columns(
                    row,
                    pair_prefix,
                    result,
                )

        # The inherited submit() adds DecisionID/DecisionRevision and
        # retains its existing append/overwrite, backup and history logic.
        return row

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def handle_key(self, event):
        # Add M only in the Point Marking tab.
        # In the Timestamp tab, M keeps its configured timestamp behavior.
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
# Self-tests
# ----------------------------------------------------------------------

def run_three_frame_self_tests():
    # Retain the original numerical geometry tests.
    base.run_geometry_self_tests()

    with tempfile.TemporaryDirectory(
        prefix="worksmart_three_frame_test_"
    ) as temporary:
        folder = Path(temporary).resolve()

        filenames = [
            "frame_1.png",
            "frame_2.png",
            "frame_3.png",
        ]

        for filename in filenames:
            Image.new(
                "RGB",
                (32, 32),
                color="black",
            ).save(folder / filename)

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

        # Cartesian line vectors are:
        # Set 1: (10, 0)
        # Set 2: (0, 10)
        # Set 3: (-10, 0)
        for index, (endpoint, _label, _number, _color) in enumerate(
            FRAME_SETS
        ):
            a[endpoint] = point(
                filenames[index],
                10,
                20,
            )

        b["start"] = point(filenames[0], 20, 20)
        b["middle"] = point(filenames[1], 10, 10)
        b["end"] = point(filenames[2], 0, 20)

        trial["spacing_x"] = 2.0
        trial["spacing_y"] = 1.0

        project = new_project("SelfTest")
        trial_key = str(folder)
        project["trials"][trial_key] = trial

        # Deliberately select 1–2: legacy CSV columns must still be 1–3.
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
            result = app.comparison_result(
                comparison,
                pair,
            )

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

            assert (
                row[prefix + csv_label + "::Status"]
                == "complete"
            )

        # Legacy comparison remains Start → End, not selected pair 1–2.
        assert math.isclose(
            row[prefix + "AngleC_px_deg"],
            180.0,
            abs_tol=1e-10,
        )

        # Calibration: horizontal length 10 px * 2 mm/px = 20 mm.
        assert math.isclose(
            row[prefix + "Pair12::L1_mm"],
            20.0,
        )

        # Vertical length 10 px * 1 mm/px = 10 mm.
        assert math.isclose(
            row[prefix + "Pair12::L2_mm"],
            10.0,
        )

        assert math.isclose(
            row["Point::Structure B::Pair13::Distance_px"],
            20.0,
        )

        assert math.isclose(
            row["Point::Structure B::Distance_px"],
            20.0,
        )

        # Test a real CSV round trip using the original writer/reader.
        csv_path = folder / "self_test.csv"

        base.write_csv_table(
            csv_path,
            list(row),
            [row],
        )

        columns, saved_rows = base.read_csv_table(csv_path)

        assert prefix + "Pair23::AngleC_px_deg" in columns
        assert len(saved_rows) == 1
        assert math.isclose(
            float(saved_rows[0][prefix + "Pair13::AngleC_px_deg"]),
            180.0,
        )

        # Missing third set must not block the valid 1–2 pair.
        saved_a_end = a["end"]
        saved_b_end = b["end"]

        a["end"] = None
        b["end"] = None

        partial_row = app.export_row()

        assert (
            partial_row[prefix + "Pair12::Status"]
            == "complete"
        )
        assert (
            partial_row[prefix + "Pair23::Status"]
            == "incomplete"
        )
        assert (
            partial_row[prefix + "Pair13::AngleC_px_deg"]
            is None
        )

        a["end"] = saved_a_end
        b["end"] = saved_b_end

        # Zero-length lines have undefined angles, not fabricated zeroes.
        saved_b_middle = b["middle"]
        b["middle"] = copy.deepcopy(a["middle"])

        zero_row = app.export_row()

        assert (
            zero_row[prefix + "Pair12::Status"]
            == "zero_length_line_angle_undefined"
        )
        assert (
            zero_row[prefix + "Pair12::AngleC_px_deg"]
            is None
        )

        b["middle"] = saved_b_middle

        # Mismatched A/B frames within one set must be rejected.
        saved_filename = b["middle"]["filename"]
        b["middle"]["filename"] = filenames[0]

        try:
            app.export_row()
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Conflicting within-set frames were not rejected."
            )
        finally:
            b["middle"]["filename"] = saved_filename

        # Migration preserves Start/End and leaves Middle empty.
        legacy_trial = copy.deepcopy(trial)

        for structure in legacy_trial["measurements"]:
            structure.pop("middle", None)

        legacy_trial["frame_links"].pop("middle", None)

        legacy_project = new_project("Legacy")
        legacy_project["version"] = 3
        legacy_project.pop("point_pair", None)
        legacy_project["trials"] = {
            trial_key: legacy_trial,
        }

        original_end = copy.deepcopy(
            legacy_trial["measurements"][0]["end"]
        )

        migrated = normalize_project(
            legacy_project,
            "Legacy",
        )

        migrated_trial = migrated["trials"][trial_key]

        assert migrated["version"] == THREE_FRAME_VERSION
        assert (
            migrated_trial["measurements"][0]["end"]
            == original_end
        )
        assert (
            migrated_trial["measurements"][0]["middle"]
            is None
        )
        assert (
            migrated_trial["frame_links"]["middle"]
            == ""
        )

        # Normalization must not alter its input project.
        assert legacy_project["version"] == 3
        assert (
            "middle"
            not in legacy_project["trials"][trial_key]["measurements"][0]
        )

        # Version 4 projects must reopen successfully.
        reopened = normalize_project(
            copy.deepcopy(project),
            "SelfTest",
        )

        assert (
            reopened["trials"][trial_key]["measurements"][1]["middle"]
            == saved_b_middle
        )

        # A Middle-only trial must count as existing work during imports.
        middle_only = new_trial()
        middle_only["measurements"][0]["middle"] = point(
            filenames[1],
            10,
            20,
        )

        assert trial_has_work(middle_only)

    print(
        "Three-frame geometry, calibration, CSV, partial-data, "
        "validation, and migration self-tests passed."
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