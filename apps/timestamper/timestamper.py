import os
import csv
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from datetime import datetime

class UltrasoundAnnotator:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Timestamper")
        
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.projects_dir = os.path.join(self.script_dir, "projects")
        if not os.path.exists(self.projects_dir):
            os.makedirs(self.projects_dir)

        # --- State ---
        self.current_project_name = ""
        self.parent_folder = ""
        self.csv_path = ""
        self.current_trial_idx = 0
        self.fps = 30
        
        # Updated: Initialize markers as 4 separate category rows
        self.mark_rows = [["On", "Max", "Off"], [], [], []] 
        self.custom_field_names = []
        
        self.ROW_KEYS = [
            list("1234567890"),  # Row 1
            list("qwertyuiop"),  # Row 2
            list("asdfghjkl"),   # Row 3
            list("zxcvbnm")      # Row 4
        ]
        self.flattened_keys = [k for row in self.ROW_KEYS for k in row]

        self.trial_folders = []
        self.images = []
        self.current_idx = 0
        self.is_playing = False
        self.marks = {}
        self.custom_entries = {}

        self.show_project_selection()

    def show_project_selection(self):
        for widget in self.root.winfo_children(): widget.destroy()
        self.root.geometry("600x500") 
        self.root.resizable(False, False)
        
        frame = tk.Frame(self.root, padx=30, pady=30)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(frame, text="WorkSmart | Timestamper", font=("Arial", 22, "bold")).pack(pady=15)
        
        new_frame = tk.LabelFrame(frame, text="Create New Project", padx=15, pady=15)
        new_frame.pack(fill="x", pady=5)
        self.ent_new_project = tk.Entry(new_frame, width=25, font=("Arial", 11))
        self.ent_new_project.pack(side="left", padx=5)
        tk.Button(new_frame, text="Create", command=self.create_project, bg="#2ecc71", fg="black").pack(side="left")

        existing = [f.replace(".json", "") for f in os.listdir(self.projects_dir) if f.endswith(".json")]
        if existing:
            load_frame = tk.LabelFrame(frame, text="Load Project", padx=15, pady=15)
            load_frame.pack(fill="x", pady=10)
            self.project_list = ttk.Combobox(load_frame, values=existing, state="readonly", font=("Arial", 11))
            self.project_list.pack(side="left", padx=5)
            tk.Button(load_frame, text="Launch", command=self.load_project, bg="#3498db", fg="black").pack(side="left")

    def setup_main_ui(self):
        for widget in self.root.winfo_children(): widget.destroy()
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        header = tk.Frame(self.root, bg="#2c3e50")
        header.pack(fill="x")
        tk.Label(header, text=f"PROJ: {self.current_project_name}", fg="white", bg="#2c3e50", font=("Arial", 9, "bold")).pack(side="left", padx=10)
        tk.Button(header, text="⚙ Config", font=("Arial", 8), command=self.toggle_settings).pack(side="left", padx=5)
        tk.Button(header, text="Menu", command=self.show_project_selection, font=("Arial", 8)).pack(side="right", padx=10)

        # --- CONFIG RIBBON (Updated for 4 Row Inputs) ---
        self.cfg_ribbon = tk.Frame(self.root, bg="#ecf0f1", padx=10, pady=10)

        self.path_bar = tk.Frame(self.root, bg="#dee2e6")
        self.path_bar.pack(fill="x")
        self.lbl_src = tk.Label(self.path_bar, text=f"Src: {self.parent_folder}", bg="#dee2e6", font=("Arial", 7), anchor="w")
        self.lbl_src.pack(side="left", padx=5)
        self.lbl_out = tk.Label(self.path_bar, text=f"Out: {self.csv_path}", bg="#dee2e6", font=("Arial", 7), anchor="w")
        self.lbl_out.pack(side="right", padx=5)

        main_container = tk.Frame(self.root)
        main_container.pack(fill="both", expand=True)

      # --- SCROLLABLE SIDEBAR SETUP ---
        # 1. Outer container for sidebar
        sidebar_container = tk.Frame(main_container, width=350)
        sidebar_container.pack(side="right", fill="y")
        sidebar_container.pack_propagate(False)

        # 2. Scrollbar
        scrollbar = tk.Scrollbar(sidebar_container, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        # 3. Canvas that will hold the content
        self.sidebar_canvas = tk.Canvas(sidebar_container, width=350, bd=0, highlightthickness=0)
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)

        # 4. The actual Frame that holds your widgets
        self.sidebar = tk.Frame(self.sidebar_canvas)
        
        # Create a window inside the canvas to hold the sidebar frame
        self.sidebar_window = self.sidebar_canvas.create_window((0, 0), window=self.sidebar, anchor="nw")

        # 5. Link Canvas and Scrollbar
        self.sidebar_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.sidebar_canvas.yview)

        # 6. Bind resizing to update scroll region
        def on_sidebar_configure(event):
            # Update scroll region to encompass the inner frame
            self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))
            # Ensure the frame stays the width of the canvas
            self.sidebar_canvas.itemconfig(self.sidebar_window, width=event.width)

        self.sidebar.bind("<Configure>", on_sidebar_configure)
        
        # Allow mousewheel scrolling
        def _on_mousewheel(event):
            self.sidebar_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        self.sidebar_canvas.bind_all("<MouseWheel>", _on_mousewheel) # Windows/macOS
        self.left_pane = tk.Frame(main_container)
        self.left_pane.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Label(self.left_pane, bg="black")
        self.canvas.pack(pady=5, expand=True)
        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())

        nav_frame = tk.Frame(self.left_pane)
        nav_frame.pack(fill="x", padx=10, pady=5)
        self.btn_play = tk.Button(nav_frame, text="▶", command=self.toggle_play, width=5)
        self.btn_play.pack(side="left")
        self.slider = tk.Scale(nav_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_move)
        self.slider.pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_frame = tk.Label(nav_frame, text="F: 0", font=("Arial", 10)); self.lbl_frame.pack(side="left")

        self.trial_selector = ttk.Combobox(self.sidebar, state="readonly"); self.trial_selector.pack(fill="x", pady=(10, 2))
        self.trial_selector.bind("<<ComboboxSelected>>", self.jump_to_trial)
        
        tk.Button(self.sidebar, text="Select Parent Folder", command=self.load_parent_folder, font=("Arial", 10)).pack(fill="x", pady=2)
        tk.Button(self.sidebar, text="Select Output CSV", command=self.load_csv, font=("Arial", 10)).pack(fill="x", pady=2)

        self.custom_container = tk.LabelFrame(self.sidebar, text="Custom Variables", padx=5, pady=5)
        self.custom_container.pack(fill="x", pady=10)
        
        self.marker_container = tk.LabelFrame(self.sidebar, text="Timestamp Categories", padx=5, pady=5)
        self.marker_container.pack(fill="x", pady=10)

        tk.Label(self.sidebar, text="Observations:", font=("Arial", 10, "bold")).pack(anchor="w")
        self.txt_remarks = tk.Entry(self.sidebar, font=("Arial", 10))
        self.txt_remarks.pack(fill="x", pady=5)

        btn_f = tk.Frame(self.sidebar)
        btn_f.pack(fill="x", pady=15)
        tk.Button(btn_f, text="SKIP", bg="#27ae60", fg="white", font=("Arial", 11), command=self.skip_trial).pack(side="left", fill="x", expand=True, padx=(0,5))
        tk.Button(btn_f, text="SUBMIT", bg="#27ae60", fg="white", font=("Arial", 11, "bold"), height=2, command=self.submit_data).pack(side="left", fill="x", expand=True)
        
        self.lbl_prog_side = tk.Label(self.sidebar, text="0/0", font=("Arial", 14, "bold"))
        self.lbl_prog_side.pack(side="bottom", pady=20)

        self.rebuild_dynamic_ui()
        self.setup_hotkeys()
        self.root.focus_force()

    def toggle_settings(self):
        """Displays 4 separate entry rows for marker categorization."""
        if self.cfg_ribbon.winfo_ismapped():
            self.cfg_ribbon.pack_forget()
        else:
            self.cfg_ribbon.pack(after=self.path_bar, fill="x")
            for w in self.cfg_ribbon.winfo_children(): w.destroy()
            
            self.row_entries = []
            row_labels = ["Row 1 (1-0):", "Row 2 (Q-P):", "Row 3 (A-L):", "Row 4 (Z-M):"]
            
            # Create 4 category rows
            for i in range(4):
                f = tk.Frame(self.cfg_ribbon, bg="#ecf0f1")
                f.pack(fill="x", pady=2)
                tk.Label(f, text=row_labels[i], width=12, anchor="w", bg="#ecf0f1", font=("Arial", 10, "bold")).pack(side="left")
                ent = tk.Entry(f); ent.pack(side="left", fill="x", expand=True, padx=5)
                ent.insert(0, ", ".join(self.mark_rows[i]))
                self.row_entries.append(ent)

            f_bot = tk.Frame(self.cfg_ribbon, bg="#ecf0f1")
            f_bot.pack(fill="x", pady=5)
            tk.Label(f_bot, text="FPS:", bg="#ecf0f1").pack(side="left")
            self.ent_fps = tk.Entry(f_bot, width=5); self.ent_fps.pack(side="left", padx=5); self.ent_fps.insert(0, str(self.fps))
            tk.Label(f_bot, text="Custom Vars:", bg="#ecf0f1").pack(side="left")
            self.ent_custom_fields = tk.Entry(f_bot); self.ent_custom_fields.pack(side="left", fill="x", expand=True, padx=5)
            self.ent_custom_fields.insert(0, ", ".join(self.custom_field_names))
            
            tk.Button(f_bot, text="APPLY", bg="#2ecc71", command=self.apply_settings).pack(side="right")

    # --- UPDATED: CATEGORIZED UI REBUILD ---
    def rebuild_dynamic_ui(self):
        for w in self.marker_container.winfo_children(): w.destroy()
        for w in self.custom_container.winfo_children(): w.destroy()
        
        self.mark_labels = {}
        # Flattened for internal logic, but UI will be grouped
        all_keys_flat = [item for sublist in self.mark_rows for item in sublist]
        self.marks = {k: "" for k in all_keys_flat}
        
        for r_idx, row_content in enumerate(self.mark_rows):
            if not row_content: continue
            
            # Category Header
            tk.Label(self.marker_container, text=f"Category {r_idx+1}", font=("Arial", 10, "bold"), fg="grey").pack(anchor="w", pady=(5,0))
            
            for c_idx, key in enumerate(row_content):
                if c_idx >= 10: break
                hotkey = self.ROW_KEYS[r_idx][c_idx]
                
                f = tk.Frame(self.marker_container)
                f.pack(fill="x", pady=1)
                
                btn = tk.Button(f, text=f"({hotkey.upper()}) {key}", font=("Arial", 8), 
                                anchor="w", command=lambda k=key: self.set_mark(k))
                btn.pack(side="left", fill="x", expand=True)
                
                self.mark_labels[key] = tk.Label(f, text="-", fg="blue", width=8, font=("Arial", 10))
                self.mark_labels[key].pack(side="right")

        self.custom_entries = {}
        for field in self.custom_field_names:
            f = tk.Frame(self.custom_container); f.pack(fill="x", pady=1)
            tk.Label(f, text=f"{field}:", font=("Arial", 10)).pack(anchor="w")
            ent = tk.Entry(f, font=("Arial", 10)); ent.pack(fill="x"); self.custom_entries[field] = ent

        self.sidebar.update_idletasks()
        self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))

    def setup_hotkeys(self):
        for k in ["<space>", "<Left>", "<Right>", "<Return>"]: self.root.unbind(k)
        self.root.bind("<space>", lambda e: not self.is_typing() and self.toggle_play())
        self.root.bind("<Left>", lambda e: not self.is_typing() and self.step_frame(-1))
        self.root.bind("<Right>", lambda e: not self.is_typing() and self.step_frame(1))
        self.root.bind("<Return>", lambda e: not self.is_typing() and self.submit_data())
        
        for char in self.flattened_keys:
            self.root.bind(char.lower(), self.handle_marker_hotkey)
            self.root.bind(char.upper(), self.handle_marker_hotkey)

    def handle_marker_hotkey(self, e):
        if self.is_typing(): return
        char = e.char.lower()
        # Find which row and column the key belongs to
        for r_idx, row in enumerate(self.ROW_KEYS):
            if char in row:
                c_idx = row.index(char)
                if c_idx < len(self.mark_rows[r_idx]):
                    self.set_mark(self.mark_rows[r_idx][c_idx])

    def skip_trial(self):
        if messagebox.askyesno("Skip", "Move to next trial without saving?"):
            self.current_trial_idx += 1; self.save_project_config(); self.load_current_trial()

    def create_project(self):
        name = self.ent_new_project.get().strip()
        if name: self.current_project_name = name; self.setup_main_ui()

    def load_project(self):
        name = self.project_list.get()
        if not name: return
        self.current_project_name = name
        try:
            with open(os.path.join(self.projects_dir, f"{name}.json"), "r") as f:
                config = json.load(f)
            self.parent_folder, self.csv_path = config.get("parent_folder", ""), config.get("csv_path", "")
            self.current_trial_idx, self.fps = config.get("last_trial_idx", 0), config.get("fps", 30)
            # Load as list of rows
            self.mark_rows = config.get("mark_rows", [["On", "Max", "Off"], [], [], []])
            self.custom_field_names = config.get("custom_fields", [])
            self.setup_main_ui(); self.refresh_parent_data(reset_idx=False)
        except Exception as e: messagebox.showerror("Error", f"Failed: {e}")

    def save_project_config(self):
        if not self.current_project_name: return
        config = {"parent_folder": self.parent_folder, "csv_path": self.csv_path, "last_trial_idx": self.current_trial_idx,
                  "fps": self.fps, "mark_rows": self.mark_rows, "custom_fields": self.custom_field_names}
        with open(os.path.join(self.projects_dir, f"{self.current_project_name}.json"), "w") as f: json.dump(config, f, indent=4)

    def apply_settings(self):
        """Processes 4 rows of marker inputs."""
        try:
            self.fps = int(self.ent_fps.get())
            new_rows = []
            for ent in self.row_entries:
                new_rows.append([x.strip() for x in ent.get().split(",") if x.strip()][:10])
            self.mark_rows = new_rows
            self.custom_field_names = [x.strip() for x in self.ent_custom_fields.get().split(",") if x.strip()][:10]
            self.rebuild_dynamic_ui(); self.setup_hotkeys(); self.save_project_config(); self.cfg_ribbon.pack_forget()
        except: messagebox.showerror("Error", "Invalid inputs")

    def is_typing(self): return isinstance(self.root.focus_get(), tk.Entry)

    def show_image(self):
        if not self.images: return
        img = Image.open(os.path.join(self.folder_path, self.images[self.current_idx]))
        self.photo = ImageTk.PhotoImage(img); self.canvas.config(image=self.photo)
        self.lbl_frame.config(text=f"F: {os.path.splitext(self.images[self.current_idx])[0]}"); self.slider.set(self.current_idx)

    def submit_data(self):
        if not self.csv_path or not self.folder_path: return
        row = {"Trial": os.path.basename(self.folder_path), "RecordTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Remarks": self.txt_remarks.get().strip() or "nil"}
        all_keys = [item for sublist in self.mark_rows for item in sublist]
        for k in all_keys: row[k] = self.marks.get(k) or "nil"
        for k, ent in self.custom_entries.items(): row[k] = ent.get().strip() or "nil"
        fieldnames = ["Trial", "RecordTime"] + all_keys + self.custom_field_names + ["Remarks"]
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not os.path.isfile(self.csv_path) or os.path.getsize(self.csv_path) == 0: writer.writeheader()
            writer.writerow(row)
        self.current_trial_idx += 1; self.save_project_config(); self.load_current_trial()

    def load_parent_folder(self):
        f = filedialog.askdirectory()
        if f: self.parent_folder = f; self.lbl_src.config(text=f"Src: {f}"); self.refresh_parent_data(); self.save_project_config()

    def load_csv(self):
        f = filedialog.asksaveasfilename(defaultextension=".csv")
        if f: self.csv_path = f; self.lbl_out.config(text=f"Out: {f}"); self.save_project_config()

    def refresh_parent_data(self, reset_idx=True):
        if not self.parent_folder or not os.path.exists(self.parent_folder): return
        dirs = sorted([d for d in os.listdir(self.parent_folder) if os.path.isdir(os.path.join(self.parent_folder, d))])
        self.trial_folders = [os.path.join(self.parent_folder, d) for d in dirs]
        self.trial_selector['values'] = dirs
        if reset_idx: self.current_trial_idx = 0
        self.load_current_trial()

    def load_current_trial(self):
        if 0 <= self.current_trial_idx < len(self.trial_folders):
            self.folder_path = self.trial_folders[self.current_trial_idx]
            self.images = sorted([f for f in os.listdir(self.folder_path) if f.lower().endswith('.png') and not f.startswith('.') and not f.startswith('~')])
            if not self.images:
                self.current_trial_idx += 1; self.load_current_trial(); return
            self.trial_selector.set(os.path.basename(self.folder_path))
            self.lbl_prog_side.config(text=f"{self.current_trial_idx+1} / {len(self.trial_folders)}")
            self.slider.config(to=len(self.images)-1); self.current_idx = 0; self.reset_form(); self.show_image()
        else: messagebox.showinfo("Done", "End of folder reached!")
            
    def on_slider_move(self, v): self.current_idx = int(v); self.show_image()
    def toggle_play(self):
        self.is_playing = not self.is_playing
        if self.is_playing: self.play_loop()
    def play_loop(self):
        if self.is_playing and self.current_idx < len(self.images)-1:
            self.current_idx += 1; self.show_image(); self.root.after(int(1000/self.fps), self.play_loop)
        else: self.is_playing = False
    def set_mark(self, k): 
        if self.images: self.marks[k] = os.path.splitext(self.images[self.current_idx])[0]; self.mark_labels[k].config(text=self.marks[k])
    def reset_form(self):
        all_keys = [item for sublist in self.mark_rows for item in sublist]
        self.marks = {k: "" for k in all_keys}; [l.config(text="-") for l in self.mark_labels.values() if l.winfo_exists()]
        self.txt_remarks.delete(0, tk.END); [e.delete(0, tk.END) for e in self.custom_entries.values()]
    def step_frame(self, d): self.current_idx = max(0, min(len(self.images)-1, self.current_idx+d)); self.show_image()
    def jump_to_trial(self, e): self.current_trial_idx = self.trial_selector.current(); self.load_current_trial()
    def on_closing(self): self.save_project_config(); self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk(); app = UltrasoundAnnotator(root); root.mainloop()