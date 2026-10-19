import tkinter as tk
from tkinter import messagebox
import subprocess
import importlib.util
import os
import sys


class WorkSmartHub:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart Research Suite")
        self.root.geometry("500x900")
        self.root.configure(bg="#f5f5f5")

        # --- Path Configuration ---
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.assets_path = os.path.join(self.base_path, "assets")
        self.apps_path = os.path.join(self.base_path, "apps")
        self.logo_path = os.path.join(self.assets_path, "worksmart.png")

        # Track running tools to prevent accidental duplicate launches.
        self.running_apps = {}

        # --- Branding & Icon Section ---
        self.load_branding()

        tk.Label(
            self.root,
            text="Select a Tool to Begin",
            font=("Arial", 13),
            bg="#f5f5f5",
            fg="#666",
        ).pack(pady=5)

        # --- App Registry ---
        # Format:
        # "Display Name": ("path relative to apps/ or absolute path",
        #                  ["required imports"])
        self.apps = {
            "Group Randomization": ("grouprand.py", ["numpy"]),
            "Trial Randomization": ("trialrand.py", ["pandas"]),
            "Crop and Blind": ("cropandblind.py", ["numpy"]),
            "Trial Judgement": ("judge.py", ["PIL"]),
            "Timestamper": ("timestamper/timestamper.py", ["PIL"]),
            "Integrated Timestamper": (
                os.path.join(
                    self.base_path,
                    "apps",
                    "integrated_timestamper",
                    "integrated_timestamper.py",
                ),
                ["PIL"],
            ),
            "Ultrasound Point Marker": (
                "ultrasound_point_marker.py",
                ["PIL"],
            ),
            "Barcode Generator": ("barcode_generator.py", ["barcode"]),
        }

        # Reserve footer space before adding the buttons.
        tk.Label(
            self.root,
            text="v1.1 | Work Smart, Play Hard",
            font=("Arial", 8),
            bg="#f5f5f5",
            fg="#aaa",
        ).pack(side="bottom", pady=15)

        self.create_buttons()

    def load_branding(self):
        """Load the dashboard logo and window icon."""
        try:
            from PIL import Image, ImageTk

            if not os.path.isfile(self.logo_path):
                raise FileNotFoundError(self.logo_path)

            with Image.open(self.logo_path) as source:
                img = source.convert("RGBA")

            # Window icon.
            self.icon_photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(False, self.icon_photo)

            # Dashboard logo.
            display_img = img.resize(
                (120, 120),
                Image.Resampling.LANCZOS,
            )
            self.logo_img = ImageTk.PhotoImage(display_img)

            tk.Label(
                self.root,
                image=self.logo_img,
                bg="#f5f5f5",
            ).pack(pady=20)

        except Exception:
            # Fallback if the logo is missing or Pillow is unavailable.
            tk.Label(
                self.root,
                text="WORK SMART",
                font=("Arial", 26, "bold"),
                bg="#f5f5f5",
                fg="#2c3e50",
            ).pack(pady=30)

    def create_buttons(self):
        btn_frame = tk.Frame(self.root, bg="#f5f5f5")
        btn_frame.pack(expand=True)

        for app_name, (script, deps) in self.apps.items():
            btn = tk.Button(
                btn_frame,
                text=app_name,
                width=28,
                height=2,
                font=("Arial", 12, "bold"),
                bg="#ffffff",
                fg="#333",
                relief="flat",
                highlightbackground="#cccccc",
                highlightthickness=1,
                command=lambda n=app_name, s=script, d=deps: (
                    self.launch_app(n, s, d)
                ),
            )
            btn.pack(pady=8)

            # Subtle hover effects.
            btn.bind(
                "<Enter>",
                lambda event, b=btn: b.configure(bg="#f0f0f0"),
            )
            btn.bind(
                "<Leave>",
                lambda event, b=btn: b.configure(bg="#ffffff"),
            )

    def check_dependencies(self, packages):
        """Return required imports missing from this Python environment."""
        missing = []

        for package in packages:
            search_name = (
                "PIL" if package.lower() == "pillow" else package
            )

            try:
                available = importlib.util.find_spec(search_name) is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                available = False

            if not available:
                missing.append(package)

        return missing

    def launch_app(self, name, script_name, dependencies):
        # 1. Avoid launching another copy of an already-running tool.
        existing = self.running_apps.get(name)
        if existing is not None and existing.poll() is None:
            messagebox.showinfo(
                "Tool Already Running",
                f"'{name}' is already open.\n\n"
                "Switch to its window to continue.",
                parent=self.root,
            )
            return

        # 2. Check the script path.
        script_path = os.path.join(self.apps_path, script_name)

        if not os.path.isfile(script_path):
            messagebox.showerror(
                "Tool Not Found",
                f"Could not find '{name}'.\n\n"
                f"Expected file:\n{script_path}",
                parent=self.root,
            )
            return

        # 3. Check required libraries.
        missing = self.check_dependencies(dependencies)
        if missing:
            # Import names can differ from installation package names.
            install_names = {
                "PIL": "pillow",
                "barcode": "python-barcode",
            }
            packages = [
                install_names.get(package, package)
                for package in missing
            ]

            messagebox.showerror(
                "Missing Dependencies",
                f"The tool '{name}' requires: {', '.join(packages)}.\n\n"
                "Install these packages in the Python/conda environment "
                "used to launch this hub.\n\n"
                f"Python interpreter:\n{sys.executable}",
                parent=self.root,
            )
            return

        # 4. Launch without blocking or hiding the hub.
        try:
            process = subprocess.Popen(
                [sys.executable, script_path]
            )
        except Exception as exc:
            messagebox.showerror(
                "Execution Error",
                f"Failed to launch {name}:\n\n{exc}",
                parent=self.root,
            )
            return

        self.running_apps[name] = process
        self.root.after(
            500,
            lambda: self.monitor_app(name, process),
        )

    def monitor_app(self, name, process):
        """Check completion without blocking Tkinter's event loop."""
        return_code = process.poll()

        if return_code is None:
            self.root.after(
                500,
                lambda: self.monitor_app(name, process),
            )
            return

        # Do not remove a newer instance from the registry.
        if self.running_apps.get(name) is process:
            del self.running_apps[name]

        if return_code != 0:
            messagebox.showerror(
                "Tool Closed With an Error",
                f"'{name}' exited with code {return_code}.\n\n"
                "If you started the hub from a terminal, check that "
                "terminal for the error details.",
                parent=self.root,
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = WorkSmartHub(root)
    root.mainloop()
