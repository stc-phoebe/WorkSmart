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

        # --- Branding & Icon Section ---
        self.load_branding()

        tk.Label(self.root, text="Select a Tool to Begin", font=("Arial", 13), bg="#f5f5f5", fg="#666").pack(pady=5)
        
        # --- App Registry ---
        # Format: "Display Name": ("filename.py", ["required_package1", "required_package2"])
        self.apps = {
            "Group Randomization": ("grouprand.py", ["numpy"]),
            "Trial Randomization": ("trialrand.py", ["pandas"]),
            "Crop and Blind": ("cropandblind.py", ["numpy"]),
            "Trial Judgement": ("judge.py", ["PIL"]),
            "Timestamper": ("timestamper.py", ["PIL"]),
        }

        self.create_buttons()

        # Footer
        tk.Label(self.root, text="v1.0 | Work Smart, Play Hard", font=("Arial", 8), bg="#f5f5f5", fg="#aaa").pack(side="bottom", pady=15)

    def load_branding(self):
        """Loads the logo for the dashboard and sets the window icon."""
        try:
            from PIL import Image, ImageTk
            if os.path.exists(self.logo_path):
                img = Image.open(self.logo_path)
                
                # Set Window Icon (the small icon in the title bar)
                self.icon_photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(False, self.icon_photo)

                # Set Dashboard Logo (the large image)
                display_img = img.resize((120, 120), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(display_img)
                
                logo_label = tk.Label(self.root, image=self.logo_img, bg="#f5f5f5")
                logo_label.pack(pady=20)
            else:
                raise FileNotFoundError
        except Exception:
            # Fallback if logo is missing or PIL fails
            tk.Label(self.root, text="WORK SMART", font=("Arial", 26, "bold"), 
                     bg="#f5f5f5", fg="#2c3e50").pack(pady=30)

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
                command=lambda n=app_name, s=script, d=deps: self.launch_app(n, s, d)
            )
            btn.pack(pady=10)
            # Subtle hover effects
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#f0f0f0"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#ffffff"))

    def check_dependencies(self, packages):
        """Verifies if the required packages are installed in the environment."""
        missing = []
        for pkg in packages:
            # Check for PIL specifically as it's the import name for Pillow
            search_name = "PIL" if pkg.lower() == "pillow" else pkg
            if importlib.util.find_spec(search_name) is None:
                missing.append(pkg)
        return missing

    def launch_app(self, name, script_name, dependencies):
        # 1. Check for missing libraries
        missing = self.check_dependencies(dependencies)
        if missing:
            messagebox.showerror(
                "Missing Dependencies", 
                f"The tool '{name}' requires: {', '.join(missing)}.\n\n"
                "Please update your conda environment."
            )
            return

        # 2. Check if the file exists in the apps folder
        script_path = os.path.join(self.apps_path, script_name)
        if not os.path.exists(script_path):
            messagebox.showerror("Error", f"Could not find '{script_name}' in the apps folder.")
            return

        # 3. Launch the app and hide the Hub
        self.root.withdraw() 
        try:
            # Runs the specific script using the current Python interpreter
            subprocess.run([sys.executable, script_path], check=True)
        except Exception as e:
            messagebox.showerror("Execution Error", f"Failed to run {name}:\n{e}")
        finally:
            # 4. Bring the Hub back once the sub-app is closed
            self.root.deiconify() 

if __name__ == "__main__":
    root = tk.Tk()
    app = WorkSmartHub(root)
    root.mainloop()