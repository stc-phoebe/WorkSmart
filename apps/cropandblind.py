import os
import cv2
import csv
import random
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from datetime import datetime

class CropAndBlind:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Crop & Blind Tool")
        self.root.geometry("1100x900")

        # Logic State
        self.input_dir = ""
        self.output_dir = ""
        self.file_type = tk.StringVar(value="avi")
        self.target_files = []
        self.crop_rect = None 
        
        # UI State
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        
        self.setup_stage1()

    def setup_stage1(self):
        for widget in self.root.winfo_children(): widget.destroy()
        
        container = tk.Frame(self.root, padx=30, pady=30)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="Step 1: File & Folder Selection", font=("Arial", 16, "bold")).pack(pady=10)

        # File Type Selection
        type_frame = tk.LabelFrame(container, text="1. Select Data Format", padx=10, pady=10)
        type_frame.pack(fill="x", pady=10)
        tk.Radiobutton(type_frame, text="Video Files (.AVI) - Directly in folder", variable=self.file_type, value="avi").pack(anchor="w")
        tk.Radiobutton(type_frame, text="Image Folders (.PNG) - Inside trial subfolders", variable=self.file_type, value="png").pack(anchor="w")

        # Path Selection
        path_frame = tk.LabelFrame(container, text="2. Select Locations", padx=10, pady=10)
        path_frame.pack(fill="x", pady=10)
        
        tk.Button(path_frame, text="Browse Parent Folder (Source)", command=self.select_input, width=30).grid(row=0, column=0, pady=5)
        self.lbl_input = tk.Label(path_frame, text="No folder selected", fg="gray", wraplength=500)
        self.lbl_input.grid(row=0, column=1, padx=10, sticky="w")

        tk.Button(path_frame, text="Browse Output Folder (Destination)", command=self.select_output, width=30).grid(row=1, column=0, pady=5)
        self.lbl_output = tk.Label(path_frame, text="No folder selected", fg="gray", wraplength=500)
        self.lbl_output.grid(row=1, column=1, padx=10, sticky="w")

        tk.Button(container, text="PROCEED TO CROP >>", bg="#3498db", fg="white", 
                  font=("Arial", 12, "bold"), height=2, command=self.setup_stage2).pack(pady=30)

    def select_input(self):
        self.input_dir = filedialog.askdirectory()
        if self.input_dir: self.lbl_input.config(text=self.input_dir, fg="black")

    def select_output(self):
        self.output_dir = filedialog.askdirectory()
        if self.output_dir: self.lbl_output.config(text=self.output_dir, fg="black")

    def setup_stage2(self):
        if not self.input_dir or not self.output_dir:
            messagebox.showerror("Error", "Please select both source and destination folders.")
            return

        # Identification
        if self.file_type.get() == "avi":
            self.target_files = sorted([f for f in os.listdir(self.input_dir) if f.lower().endswith('.avi')])
        else:
            self.target_files = sorted([d for d in os.listdir(self.input_dir) if os.path.isdir(os.path.join(self.input_dir, d))])
        
        if not self.target_files:
            messagebox.showerror("Error", "No valid files found in the source folder.")
            return

        self.show_cropper()

    def show_cropper(self):
        for widget in self.root.winfo_children(): widget.destroy()
        
        preview_img = self.get_preview_image()
        if not preview_img:
            messagebox.showerror("Error", "Could not load preview. Ensure the folder contains valid data.")
            return

        self.orig_w, self.orig_h = preview_img.size
        
        # Header with Hotkey info
        header = tk.Frame(self.root, pady=10)
        header.pack(fill="x")
        tk.Label(header, text=f"Step 2: Draw Crop Box ({self.orig_w}x{self.orig_h})", font=("Arial", 14, "bold")).pack()
        tk.Label(header, text="DRAG MOUSE to draw | Press 'R' to Reset | Confirm to process batch", fg="#e67e22").pack()
        
        # Canvas with Scrollbars
        container = tk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=20, pady=10)

        canvas_h = min(self.orig_h, 550)
        self.canvas = tk.Canvas(container, width=self.orig_w, height=canvas_h, 
                               bg="#2c3e50", scrollregion=(0, 0, self.orig_w, self.orig_h))
        
        v_scroll = tk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        h_scroll = tk.Scrollbar(container, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        v_scroll.pack(side="right", fill="y")
        h_scroll.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.tk_preview = ImageTk.PhotoImage(preview_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_preview)
        
        # Interaction
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<r>", lambda e: self.reset_box())
        self.root.bind("<R>", lambda e: self.reset_box())

        # Progress UI (Hidden until processing)
        self.progress_frame = tk.Frame(self.root, pady=10)
        self.progress_frame.pack(fill="x", padx=50)
        
        self.prog_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
        self.prog_bar.pack(fill="x")
        
        self.lbl_status = tk.Label(self.progress_frame, text="Ready to process.", font=("Arial", 10))
        self.lbl_status.pack()

        tk.Button(self.root, text="START PROCESSING BATCH", bg="#2ecc71", fg="white", 
                  font=("Arial", 12, "bold"), height=2, command=self.process_all).pack(pady=15)

    def get_preview_image(self):
        first = self.target_files[0]
        try:
            if self.file_type.get() == "avi":
                cap = cv2.VideoCapture(os.path.join(self.input_dir, first))
                ret, frame = cap.read()
                cap.release()
                if ret: return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            else:
                sub_path = os.path.join(self.input_dir, first)
                pngs = [f for f in os.listdir(sub_path) if f.lower().endswith('.png')]
                if pngs: return Image.open(os.path.join(sub_path, pngs[0]))
        except: return None

    def on_button_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=3)

    def on_move_press(self, event):
        cur_x, cur_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        cur_x, cur_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.crop_rect = [int(min(self.start_x, cur_x)), int(min(self.start_y, cur_y)),
                          int(max(self.start_x, cur_x)), int(max(self.start_y, cur_y))]

    def reset_box(self):
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.crop_rect = None

    def process_all(self):
        if not self.crop_rect:
            messagebox.showwarning("Warning", "Please draw a crop box first.")
            return

        # Prepare Randomized Mapping (Seed 24)
        random.seed(24)
        shuffled = list(self.target_files)
        random.shuffle(shuffled)
        blind_map = {name: str(idx).zfill(3) for idx, name in enumerate(shuffled)}
        
        total = len(self.target_files)
        self.prog_bar["maximum"] = total
        log_entries = []

        for i, original_name in enumerate(self.target_files):
            new_name = blind_map[original_name]
            self.lbl_status.config(text=f"Processing {i+1}/{total}: {original_name} -> {new_name}")
            self.prog_bar["value"] = i + 1
            self.root.update_idletasks() # Keep UI responsive

            src = os.path.join(self.input_dir, original_name)
            if self.file_type.get() == "avi":
                success = self.crop_video(src, os.path.join(self.output_dir, f"{new_name}.avi"))
            else:
                success = self.crop_png_folder(src, os.path.join(self.output_dir, new_name))
            
            log_entries.append({
                "original_name": original_name,
                "blinded_name": new_name,
                "status": "Success" if success else "Failed",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        # Save Log
        with open(os.path.join(self.output_dir, "log.csv"), 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["original_name", "blinded_name", "status", "timestamp"])
            writer.writeheader()
            writer.writerows(log_entries)

        messagebox.showinfo("Complete", "Batch Processing Finished!\nLog generated in output folder.")
        self.setup_stage1()

    def crop_video(self, src, dst):
        cap = cv2.VideoCapture(src)
        if not cap.isOpened(): return False
        
        true_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        true_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Clamping to prevent 7KB error
        x1, y1, x2, y2 = self.crop_rect
        x1, y1 = max(0, min(x1, true_w - 1)), max(0, min(y1, true_h - 1))
        x2, y2 = max(x1 + 1, min(x2, true_w)), max(y1 + 1, min(y2, true_h))
        
        out_w, out_h = x2 - x1, y2 - y1
        
        # Use DIVX for maximum Windows compatibility
        fourcc = cv2.VideoWriter_fourcc(*'DIVX')
        out = cv2.VideoWriter(dst, fourcc, fps, (out_w, out_h))

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None: break
            
            cropped = frame[y1:y2, x1:x2]
            
            # Force size check to avoid dropped frames
            if cropped.shape[1] != out_w or cropped.shape[0] != out_h:
                cropped = cv2.resize(cropped, (out_w, out_h))
            
            out.write(cropped)
            
        cap.release()
        out.release()
        return os.path.exists(dst) and os.path.getsize(dst) > 10000 # Verify file is > 10KB

    def crop_png_folder(self, src_folder, dst_folder):
        if not os.path.exists(dst_folder): os.makedirs(dst_folder)
        x1, y1, x2, y2 = self.crop_rect
        try:
            for file in os.listdir(src_folder):
                if file.lower().endswith('.png'):
                    img = cv2.imread(os.path.join(src_folder, file))
                    if img is not None:
                        cv2.imwrite(os.path.join(dst_folder, file), img[y1:y2, x1:x2])
            return True
        except: return False

if __name__ == "__main__":
    root = tk.Tk()
    app = CropAndBlind(root)
    root.mainloop()