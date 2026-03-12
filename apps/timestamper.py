import os
import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from datetime import datetime

class UltrasoundAnnotator:
    def __init__(self, root):
        self.root = root
        self.root.title("Ultrasound Timeframe Stamping - WORKSMART")
        
        # Insert logo
        try:
            logo_img = Image.open("assets/worksmart.png")
            self.logo_icon = ImageTk.PhotoImage(logo_img)
            self.root.iconphoto(False, self.logo_icon)
        except Exception as e:
            print(f"Could not load logo: {e}")

        # Data State
        self.parent_folder = ""
        self.trial_folders = []
        self.current_trial_idx = 0
        self.folder_path = ""
        self.csv_path = ""
        self.images = []
        self.current_idx = 0
        self.is_playing = False
        
        self.mark_keys = ["GH_on", "GH_Max", "GH_off", "TB_on", "TB_Max", "TB_Off"]
        self.marks = {key: "" for key in self.mark_keys}
        self.fieldnames = ["Trial"] + self.mark_keys + ["Remarks"] + ["RecordTime"]

        self.setup_ui()
        self.setup_hotkeys()

    def setup_ui(self):
        # --- File Selection Section ---
        file_frame = tk.Frame(self.root)
        file_frame.pack(pady=10, fill="x", padx=10)

        tk.Button(file_frame, text="Parent Folder", command=self.load_parent_folder).pack(side="left", padx=2)
        tk.Button(file_frame, text="Select CSV", command=self.load_csv).pack(side="left", padx=2)
        tk.Button(file_frame, text="Create CSV", command=self.create_new_csv).pack(side="left", padx=2)
        
        tk.Label(file_frame, text=" | Go to:").pack(side="left", padx=5)
        self.trial_selector = ttk.Combobox(file_frame, state="readonly", width=20)
        self.trial_selector.pack(side="left", padx=5)
        self.trial_selector.bind("<<ComboboxSelected>>", self.jump_to_trial)

        self.lbl_progress = tk.Label(file_frame, text="Progress: 0/0", font=('Arial', 10))
        self.lbl_progress.pack(side="right", padx=10)

        # --- Trial Info Bar (UPDATED) ---
        info_frame = tk.Frame(self.root, bg="#f0f0f0")
        info_frame.pack(fill="x", padx=10, pady=2)
        
        self.lbl_parent = tk.Label(info_frame, text="Project: None", font=('Arial', 10), bg="#f0f0f0")
        self.lbl_parent.pack(side="left", padx=5)
        
        tk.Label(info_frame, text=" > ", font=('Arial', 10), bg="#f0f0f0").pack(side="left")
        
        self.lbl_trial = tk.Label(info_frame, text="Current Trial: None", font=('Arial', 10, 'bold'), fg="darkgreen", bg="#f0f0f0")
        self.lbl_trial.pack(side="left")

        # --- Image Display Section ---
        self.canvas = tk.Label(self.root, bg="black", width=800, height=600)
        self.canvas.pack(pady=5)

        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())

        # --- Navigation Section ---
        nav_frame = tk.Frame(self.root)
        nav_frame.pack(fill="x", padx=10)

        self.btn_play = tk.Button(nav_frame, text="▶ Play (Space)", width=15, command=self.toggle_play)
        self.btn_play.pack(side="left", padx=5)

        self.slider = tk.Scale(nav_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_move)
        self.slider.pack(side="left", fill="x", expand=True, padx=5)

        self.lbl_frame_num = tk.Label(nav_frame, text="Frame: 000", font=('Courier', 12))
        self.lbl_frame_num.pack(side="left", padx=10)

        # --- Annotation Buttons Section ---
        anno_frame = tk.Frame(self.root)
        anno_frame.pack(pady=10)

        self.mark_labels = {}
        for i, key in enumerate(self.mark_keys, 1):
            btn_subframe = tk.Frame(anno_frame)
            btn_subframe.pack(side="left", padx=5)
            tk.Button(btn_subframe, text=f"Mark {key}\n({i})", width=12, command=lambda k=key: self.set_mark(k)).pack()
            self.mark_labels[key] = tk.Label(btn_subframe, text="-", fg="blue")
            self.mark_labels[key].pack()

        # --- Remarks and Actions ---
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(pady=10, fill="x", padx=10)

        tk.Label(bottom_frame, text="Observations:").pack(side="left")
        self.txt_remarks = tk.Entry(bottom_frame)
        self.txt_remarks.pack(side="left", fill="x", expand=True, padx=10)

        tk.Button(bottom_frame, text="SKIP TRIAL", bg="#ff9800", command=self.skip_trial, width=12).pack(side="left", padx=5)
        tk.Button(bottom_frame, text="SUBMIT & NEXT", bg="#00ace6", fg="#00ace6", command=self.submit_data, width=15, height=2).pack(side="right")

    def setup_hotkeys(self):
        # Bind movement and control keys
        self.root.bind("<space>", self.handle_hotkeys)
        self.root.bind("<Left>", self.handle_hotkeys)
        self.root.bind("<Right>", self.handle_hotkeys)
        self.root.bind("<Return>", self.handle_hotkeys)
        self.root.bind("r", self.handle_hotkeys)
        self.root.bind("R", self.handle_hotkeys) # Catch capital R too
        
        # Bind keys 1-6 for markers
        for i in range(1, 7):
            self.root.bind(str(i), self.handle_hotkeys)
    
    def handle_hotkeys(self, event):
        # Check if the user is currently typing in the Remarks box
        if self.root.focus_get() == self.txt_remarks:
            # If the user presses Enter while in Remarks, you might still want it to submit.
            # If so, uncomment the next two lines:
            # if event.keysym == 'Return':
            #     self.submit_data()
            return

        # Mapping keysyms to their respective functions
        key = event.keysym
        
        if key == 'space':
            self.toggle_play()
        elif key in ['r', 'R']:
            self.jump_to_start()
        elif key == 'Return':
            self.submit_data()
        elif key == 'Left':
            self.step_frame(-1)
        elif key == 'Right':
            self.step_frame(1)
        elif key in ['1', '2', '3', '4', '5', '6']:
            # Map '1'-'6' to the correct mark key index
            idx = int(key) - 1
            mark_key = self.mark_keys[idx]
            self.set_mark(mark_key)
    
    def check_completion_status(self):
        """Checks the CSV to see which folders haven't been recorded yet."""
        if not self.csv_path or not self.trial_folders:
            return

        recorded_trials = set()
        try:
            with open(self.csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    recorded_trials.add(row["Trial"])
        except Exception:
            pass # File might be empty or not yet created

        all_trial_names = [os.path.basename(d) for d in self.trial_folders]
        missing_trials = [name for name in all_trial_names if name not in recorded_trials]

        if not missing_trials:
            messagebox.showinfo("Status", "🎉 All trials COMPLETED!")
        else:
            missing_str = "\n".join(missing_trials[:10]) # Show first 10
            if len(missing_trials) > 10:
                missing_str += f"\n...and {len(missing_trials)-10} more."
            
            messagebox.showwarning("Incomplete", 
                f"Missing Records for {len(missing_trials)} trials:\n\n{missing_str}")

    # --- Logic Methods ---

    def load_parent_folder(self):
        self.parent_folder = filedialog.askdirectory()
        if self.parent_folder:
            dirs = [d for d in os.listdir(self.parent_folder) if os.path.isdir(os.path.join(self.parent_folder, d))]
            dirs.sort()
            if not dirs:
                messagebox.showwarning("No Folders", "The selected parent folder has no sub-folders.")
                return
            
            # Update Parent Folder Display
            self.lbl_parent.config(text=f"Project: {os.path.basename(self.parent_folder)}")
            
            self.trial_folders = [os.path.join(self.parent_folder, d) for d in dirs]
            self.trial_selector['values'] = dirs
            self.current_trial_idx = 0
            self.load_current_trial()

    def jump_to_trial(self, event=None):
        selection = self.trial_selector.get()
        if selection in [os.path.basename(d) for d in self.trial_folders]:
            self.current_trial_idx = [os.path.basename(d) for d in self.trial_folders].index(selection)
            self.load_current_trial()

    def jump_to_start(self):
        """Moves the video back to the first frame (index 0)"""
        if self.images:
            self.current_idx = 0
            self.show_image()

    def load_current_trial(self):
        if 0 <= self.current_trial_idx < len(self.trial_folders):
            self.folder_path = self.trial_folders[self.current_trial_idx]
            files = [f for f in os.listdir(self.folder_path) if f.lower().endswith('.png')]
            files.sort()
            self.images = files
            trial_name = os.path.basename(self.folder_path)
            csv_name = os.path.basename(self.csv_path)
            self.lbl_trial.config(text=f"Current Trial: {trial_name}")
            self.lbl_trial.config(text=f"Current CSV: {csv_name}")
            self.trial_selector.set(trial_name)
            self.lbl_progress.config(text=f"Progress: {self.current_trial_idx + 1}/{len(self.trial_folders)}")
            self.slider.config(to=len(self.images)-1 if self.images else 0)
            self.current_idx = 0
            self.reset_form()
            self.show_image()
        else:
            self.check_completion_status()

    def skip_trial(self):
        if messagebox.askyesno("Skip", "Move to next trial without saving?"):
            self.current_trial_idx += 1
            self.load_current_trial()

    def create_new_csv(self):
        new_file = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if new_file:
            try:
                with open(new_file, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                    writer.writeheader()
                self.csv_path = new_file
                messagebox.showinfo("Success", f"Created: {os.path.basename(new_file)}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not create file: {e}")

    def load_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if path:
            self.csv_path = path
            messagebox.showinfo("Success", f"Recording to: {os.path.basename(path)}")

    def show_image(self):
        if not self.images: return
        img_name = self.images[self.current_idx]
        img_path = os.path.join(self.folder_path, img_name)
        clean_name = os.path.splitext(img_name)[0]
        img = Image.open(img_path).resize((800, 600), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.config(image=self.photo)
        self.lbl_frame_num.config(text=f"Frame: {clean_name}")
        self.slider.set(self.current_idx)

    def step_frame(self, direction):
        new_idx = self.current_idx + direction
        if 0 <= new_idx < len(self.images):
            self.current_idx = new_idx
            self.show_image()

    def on_slider_move(self, val):
        self.current_idx = int(val)
        self.show_image()

    def toggle_play(self):
        if not self.images: return
        self.is_playing = not self.is_playing
        self.btn_play.config(text="⏸ Pause (Space)" if self.is_playing else "▶ Play (Space)")
        if self.is_playing: self.play_loop()

    def play_loop(self):
        if self.is_playing and self.current_idx < len(self.images) - 1:
            self.current_idx += 1
            self.show_image()
            self.root.after(33, self.play_loop)
        else:
            self.is_playing = False
            self.btn_play.config(text="▶ Play (Space)")

    def set_mark(self, key):
        if not self.images: return
        clean_name = os.path.splitext(self.images[self.current_idx])[0]
        self.marks[key] = clean_name
        self.mark_labels[key].config(text=clean_name)

    def submit_data(self):
        if not self.csv_path or not self.folder_path:
            messagebox.showerror("Error", "Select Folder and CSV first!")
            return

        obs = self.txt_remarks.get().strip() or "nil"
        row_data = {"Trial": os.path.basename(self.folder_path), **self.marks, "Remarks": obs, "recordtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        try:
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writerow(row_data)

            self.current_trial_idx += 1
            self.load_current_trial()
        except Exception as e:
            messagebox.showerror("File Error", f"Error: {e}")
        self.root.focus_set()

    def reset_form(self):
        for key in self.marks:
            self.marks[key] = ""
            self.mark_labels[key].config(text="-")
        self.txt_remarks.delete(0, tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = UltrasoundAnnotator(root)
    root.mainloop()