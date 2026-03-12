import os
import csv
import cv2
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from datetime import datetime

class TrialJudge:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Trial Judgement")
        self.root.geometry("900x850")

        # Path Setup
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.logo_path = os.path.abspath(os.path.join(self.base_path, "..", "assets", "worksmart.png"))

        # Data State
        self.video_folder = ""
        self.video_files = []
        self.current_video_idx = 0
        self.csv_path = ""
        self.judgment = ""
        
        # Video Playback State
        self.cap = None
        self.is_playing = False
        self.total_frames = 0
        self.fieldnames = ["filename", "judgment", "remarks", "recordtime"]

        self.setup_ui()
        self.setup_hotkeys()

    def setup_ui(self):
        # --- File Section ---
        file_frame = tk.Frame(self.root)
        file_frame.pack(pady=10, fill="x", padx=20)

        try:
            logo_img = Image.open(self.logo_path).resize((40, 40), Image.Resampling.LANCZOS)
            self.logo_icon = ImageTk.PhotoImage(logo_img)
            tk.Label(file_frame, image=self.logo_icon).pack(side="left", padx=5)
            self.root.iconphoto(False, self.logo_icon)
        except: pass

        tk.Button(file_frame, text="Select AVI Folder", command=self.load_folder).pack(side="left", padx=5)
        tk.Button(file_frame, text="Select/Create CSV", command=self.setup_csv).pack(side="left", padx=5)
        
        self.lbl_progress = tk.Label(file_frame, text="Progress: 0/0", font=("Arial", 10))
        self.lbl_progress.pack(side="right")

        # --- Video Canvas (Fixed Container) ---
        self.canvas_container = tk.Frame(self.root, bg="black", width=800, height=450)
        self.canvas_container.pack_propagate(False)
        self.canvas_container.pack(pady=5)
        
        self.canvas = tk.Label(self.canvas_container, bg="black")
        self.canvas.pack(expand=True)
        self.canvas.bind("<Button-1>", lambda e: self.root.focus_set())

        # --- Slider Section ---
        self.slider = tk.Scale(self.root, from_=0, to=100, orient="horizontal", 
                              command=self.manual_seek, showvalue=False, length=800)
        self.slider.pack(pady=5)

        # --- Playback Control ---
        self.btn_play = tk.Button(self.root, text="▶ Play (Space)", width=20, command=self.toggle_play)
        self.btn_play.pack()

        self.lbl_filename = tk.Label(self.root, text="No Video Loaded", font=("Courier", 12, "bold"), fg="blue")
        self.lbl_filename.pack(pady=5)

        # --- Judgment Section ---
        judge_frame = tk.Frame(self.root)
        judge_frame.pack(pady=5)

        tk.Label(judge_frame, text="Judgment:", font=("Arial", 11)).pack(side="left", padx=5)
        self.lbl_current_judge = tk.Label(judge_frame, text="-", font=("Arial", 14, "bold"), fg="red", width=5)
        self.lbl_current_judge.pack(side="left")
        tk.Label(judge_frame, text="(Press 1 or 0)", fg="gray").pack(side="left")

        # --- Remarks ---
        remark_frame = tk.Frame(self.root)
        remark_frame.pack(fill="x", padx=50, pady=5)
        tk.Label(remark_frame, text="Remarks:").pack(side="left")
        self.txt_remarks = tk.Entry(remark_frame)
        self.txt_remarks.pack(side="left", fill="x", expand=True, padx=10)

        # --- Submit ---
        tk.Button(self.root, text="SUBMIT & NEXT (Enter)", bg="#2ecc71", fg="white", 
                  font=("Arial", 12, "bold"), height=2, width=25, command=self.submit_data).pack(pady=10)

    def setup_hotkeys(self):
        self.root.bind("<space>", self.handle_hotkeys)
        self.root.bind("1", self.handle_hotkeys)
        self.root.bind("0", self.handle_hotkeys)
        self.root.bind("<Return>", self.handle_hotkeys)

    def handle_hotkeys(self, event):
        if self.root.focus_get() == self.txt_remarks:
            if event.keysym == 'Return': self.submit_data()
            return
        if event.keysym == 'space': self.toggle_play()
        elif event.char == '1': self.set_judgment("1")
        elif event.char == '0': self.set_judgment("0")
        elif event.keysym == 'Return': self.submit_data()

    def setup_csv(self):
        # Changed to askopenfilename so it doesn't prompt for overwrite
        path = filedialog.askopenfilename(defaultextension=".csv", 
                                          filetypes=[("CSV files", "*.csv")],
                                          title="Select or Create CSV")
        if not path:
            # If user cancels, try asking for a "new" filename
            path = filedialog.asksaveasfilename(defaultextension=".csv", 
                                               filetypes=[("CSV files", "*.csv")])
        
        if path:
            self.csv_path = path
            if not os.path.exists(path):
                with open(path, 'w', newline='') as f:
                    csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()
            messagebox.showinfo("Success", f"Target CSV: {os.path.basename(path)}")

    def load_folder(self):
        self.video_folder = filedialog.askdirectory()
        if self.video_folder:
            self.video_files = [f for f in os.listdir(self.video_folder) if f.lower().endswith('.avi')]
            self.video_files.sort()
            self.current_video_idx = 0
            self.load_video()

    def load_video(self):
        if self.cap: self.cap.release()
        if self.current_video_idx < len(self.video_files):
            vid_path = os.path.join(self.video_folder, self.video_files[self.current_video_idx])
            self.cap = cv2.VideoCapture(vid_path)
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Update Slider Range
            self.slider.config(to=self.total_frames - 1)
            self.slider.set(0)
            
            self.lbl_filename.config(text=f"File: {self.video_files[self.current_video_idx]}")
            self.lbl_progress.config(text=f"Progress: {self.current_video_idx+1}/{len(self.video_files)}")
            self.reset_form()
            self.show_frame(0)
        else:
            self.check_completion()

    def show_frame(self, frame_no):
        if not self.cap: return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = self.cap.read()
        if ret:
            self.display_frame(frame)

    def display_frame(self, frame):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = frame.shape
        
        # Calculate Aspect Ratio Fit
        max_w, max_h = 800, 450
        scaling = min(max_w/w, max_h/h)
        new_w, new_h = int(w * scaling), int(h * scaling)
        
        img = Image.fromarray(frame).resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image=img)
        self.canvas.config(image=self.photo)

    def manual_seek(self, val):
        if not self.is_playing:
            self.show_frame(int(val))

    def toggle_play(self):
        if not self.cap: return
        self.is_playing = not self.is_playing
        self.btn_play.config(text="⏸ Pause (Space)" if self.is_playing else "▶ Play (Space)")
        if self.is_playing: self.play_loop()

    def play_loop(self):
        if self.is_playing and self.cap:
            ret, frame = self.cap.read()
            if ret:
                curr_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.slider.set(curr_frame) # Update slider visually
                self.display_frame(frame)
                self.root.after(30, self.play_loop)
            else:
                self.is_playing = False
                self.btn_play.config(text="▶ Play (Space)")
                self.slider.set(0)
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def set_judgment(self, val):
        self.judgment = val
        self.lbl_current_judge.config(text=val, fg="#2ecc71")

    def submit_data(self):
        if not self.csv_path or not self.video_files:
            messagebox.showerror("Error", "Setup Folder and CSV first!")
            return
        if not self.judgment:
            messagebox.showwarning("Incomplete", "Please enter a judgment (1 or 0).")
            return

        row = {
            "filename": self.video_files[self.current_video_idx],
            "judgment": self.judgment,
            "remarks": self.txt_remarks.get() or "nil",
            "recordtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        with open(self.csv_path, 'a', newline='') as f:
            csv.DictWriter(f, fieldnames=self.fieldnames).writerow(row)
        
        self.current_video_idx += 1
        self.root.focus_set()
        self.load_video()

    def reset_form(self):
        self.judgment = ""
        self.lbl_current_judge.config(text="-", fg="red")
        self.txt_remarks.delete(0, tk.END)

    def check_completion(self):
        recorded = set()
        if os.path.exists(self.csv_path):
            with open(self.csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader: recorded.add(row['filename'])
        
        missing = [f for f in self.video_files if f not in recorded]
        if not missing:
            messagebox.showinfo("WorkSmart", "🎉 ALL TRIALS COMPLETED!")
        else:
            messagebox.showwarning("Incomplete", f"Missing {len(missing)} files:\n" + "\n".join(missing[:5]))

if __name__ == "__main__":
    root = tk.Tk()
    app = TrialJudge(root)
    root.mainloop()