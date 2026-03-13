import os
import csv
import random
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

class TrialRandomizer:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Trial Randomization")
        self.root.geometry("800x750")
        
        # --- State Data (Persistent Storage) ---
        self.proj_code = ""
        self.num_subjects = 0
        self.sections = [] 
        self.config_list = []
        self.matrix_vars = {} 

        self.setup_stage1()

    def clear_screen(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    # --- STAGE 1: DEFINITIONS ---
    def setup_stage1(self):
        self.clear_screen()
        container = tk.Frame(self.root, padx=30, pady=20)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="Stage 1: Define Project Structure", font=("Arial", 14, "bold")).pack(pady=10)

        # Basic Info
        info_frame = tk.LabelFrame(container, text="Project Info", padx=10, pady=10)
        info_frame.pack(fill="x", pady=5)

        tk.Label(info_frame, text="Project Code:").grid(row=0, column=0, sticky="w")
        self.ent_proj = tk.Entry(info_frame); self.ent_proj.insert(0, self.proj_code)
        self.ent_proj.grid(row=0, column=1, padx=5, pady=2)

        tk.Label(info_frame, text="Total Subjects:").grid(row=1, column=0, sticky="w")
        self.ent_subj = tk.Entry(info_frame); self.ent_subj.insert(0, str(self.num_subjects))
        self.ent_subj.grid(row=1, column=1, padx=5, pady=2)

        # Trial Configurations
        config_frame = tk.LabelFrame(container, text="Trial Configurations (comma separated; e.g.: lv1_10ml, lv1_5ml...)", padx=10, pady=10)
        config_frame.pack(fill="x", pady=5)
        self.ent_configs = tk.Entry(config_frame)
        self.ent_configs.insert(0, ",".join(self.config_list))
        self.ent_configs.pack(fill="x", pady=5)

        # Sections
        sec_frame = tk.LabelFrame(container, text="Sections (comma separated with alternate name and number of trials)", padx=10, pady=10)
        sec_frame.pack(fill="both", expand=True, pady=5)
        self.ent_sections = tk.Entry(sec_frame)
        # Reconstruct string for display if returning from Stage 2
        sec_str = ", ".join([f"{n}, {c}" for n, c in self.sections])
        self.ent_sections.insert(0, sec_str)
        self.ent_sections.pack(fill="x", pady=5)

        tk.Button(container, text="Next: Configure Matrix >>", 
                  command=self.process_stage1).pack(pady=20)

    def process_stage1(self):
        # --- CRITICAL FIX: Save values to variables BEFORE clearing screen ---
        try:
            self.proj_code = self.ent_proj.get().strip()
            self.num_subjects = int(self.ent_subj.get())
            self.config_list = [c.strip() for c in self.ent_configs.get().split(",") if c.strip()]
            
            raw_sec = [s.strip() for s in self.ent_sections.get().split(",") if s.strip()]
            if len(raw_sec) % 2 != 0: raise ValueError("Section pairs incomplete")
            
            self.sections = []
            for i in range(0, len(raw_sec), 2):
                self.sections.append((raw_sec[i], int(raw_sec[i+1])))
                
        except ValueError as e:
            messagebox.showerror("Input Error", f"Check your numbers and sections:\n{e}")
            return

        self.setup_stage2()

    # --- STAGE 2: THE MATRIX ---
    def setup_stage2(self):
        self.clear_screen()
        # Scrollable container for many configs/sections
        main_canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        scrollable_frame = tk.Frame(main_canvas, padx=30, pady=20)

        scrollable_frame.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        main_canvas.pack(side="left", fill="both", expand=True)

        tk.Label(scrollable_frame, text="Stage 2: Select Trials per Section", font=("Arial", 14, "bold")).pack(pady=10)

        # Matrix Table
        matrix_frame = tk.Frame(scrollable_frame)
        matrix_frame.pack(pady=10)

        # Header Row
        tk.Label(matrix_frame, text="Section \\ Config", font=("Arial", 9, "bold")).grid(row=0, column=0, padx=5)
        for c_idx, config in enumerate(self.config_list):
            tk.Label(matrix_frame, text=config, font=("Arial", 9, "bold")).grid(row=0, column=c_idx+1, padx=5)

        # Rows
        self.matrix_vars = {}
        for r_idx, (sec_name, sec_count) in enumerate(self.sections):
            tk.Label(matrix_frame, text=f"{sec_name} ({sec_count} trials)").grid(row=r_idx+1, column=0, sticky="w", pady=2)
            self.matrix_vars[sec_name] = {}
            for c_idx, config in enumerate(self.config_list):
                var = tk.BooleanVar()
                tk.Checkbutton(matrix_frame, variable=var).grid(row=r_idx+1, column=c_idx+1)
                self.matrix_vars[sec_name][config] = var

        btn_frame = tk.Frame(scrollable_frame)
        btn_frame.pack(fill="x", pady=20)
        tk.Button(btn_frame, text="<< Back", command=self.setup_stage1).pack(side="left")
        tk.Button(btn_frame, text="Generate Randomized CSV", 
                  command=self.generate_csv).pack(side="right")

    # --- FINAL PROCESSING ---
    def generate_csv(self):
        # Now uses self.proj_code and self.num_subjects (saved from Stage 1)
        output_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not output_path: return

        header = ["subject code"]
        for sec_name, count in self.sections:
            for i in range(1, count + 1):
                header.append(f"{sec_name}-{str(i).zfill(2)}")

        random.seed(24)
        rows = []

        for s in range(1, self.num_subjects + 1):
            subject_row = [f"{self.proj_code}_{str(s).zfill(3)}"]
            
            for sec_name, count in self.sections:
                allowed_configs = [c for c, var in self.matrix_vars[sec_name].items() if var.get()]
                
                if not allowed_configs:
                    messagebox.showerror("Error", f"No configurations selected for section: {sec_name}")
                    return

                pool = []
                while len(pool) < count:
                    temp_chunk = allowed_configs.copy()
                    random.shuffle(temp_chunk)
                    pool.extend(temp_chunk)
                
                subject_row.extend(pool[:count])
            rows.append(subject_row)

        try:
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)
            messagebox.showinfo("Success", f"File created: {os.path.basename(output_path)}")
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = TrialRandomizer(root)
    root.mainloop()