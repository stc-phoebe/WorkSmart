import os
import csv
import random
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

class GroupRandomizer:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Group Randomization")
        self.root.geometry("500x600")
        self.root.configure(bg="#f5f5f5")

        # Path Setup
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.logo_path = os.path.abspath(os.path.join(self.base_path, "..", "assets", "worksmart.png"))

        self.setup_ui()

    def setup_ui(self):
        # Branding
        try:
            img = Image.open(self.logo_path).resize((50, 50), Image.Resampling.LANCZOS)
            self.logo_icon = ImageTk.PhotoImage(img)
            tk.Label(self.root, image=self.logo_icon, bg="#f5f5f5").pack(pady=10)
        except: pass

        tk.Label(self.root, text="Pre-Randomization Generator", font=("Arial", 14, "bold"), bg="#f5f5f5").pack()

        # Input Fields
        container = tk.Frame(self.root, bg="#f5f5f5")
        container.pack(pady=20, padx=40, fill="x")

        # Project Code
        tk.Label(container, text="Project Code (e.g., STC):", bg="#f5f5f5").pack(anchor="w")
        self.ent_proj = tk.Entry(container)
        self.ent_proj.pack(fill="x", pady=5)

        # Total Subjects
        tk.Label(container, text="Total Number of Subjects:", bg="#f5f5f5").pack(anchor="w")
        self.ent_total = tk.Entry(container)
        self.ent_total.pack(fill="x", pady=5)

        # Group Names
        tk.Label(container, text="Group Names (comma separated):", bg="#f5f5f5").pack(anchor="w")
        self.ent_groups = tk.Entry(container)
        self.ent_groups.pack(fill="x", pady=5)

        # Output Folder
        tk.Label(container, text="Output Folder:", bg="#f5f5f5").pack(anchor="w")
        folder_frame = tk.Frame(container, bg="#f5f5f5")
        folder_frame.pack(fill="x", pady=5)
        
        self.out_path = tk.StringVar()
        tk.Entry(folder_frame, textvariable=self.out_path).pack(side="left", fill="x", expand=True)
        tk.Button(folder_frame, text="Browse", command=self.browse_folder).pack(side="right", padx=5)

        # Generate Button
        tk.Button(self.root, text="GENERATE CSV", bg="#3498db", fg="white", 
                  font=("Arial", 12, "bold"), height=2, width=20, 
                  command=self.generate_randomization).pack(pady=30)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.out_path.set(folder)

    def generate_randomization(self):
        # 1. Validation
        proj_code = self.ent_proj.get().strip()
        groups = [g.strip() for g in self.ent_groups.get().split(",") if g.strip()]
        output_dir = self.out_path.get()
        
        try:
            total_n = int(self.ent_total.get())
        except ValueError:
            messagebox.showerror("Error", "Total subjects must be a number.")
            return

        if not proj_code or not groups or not output_dir:
            messagebox.showerror("Error", "All fields are required.")
            return

        # 2. Logic: Create the full list of groups to be shuffled
        # We need to distribute total_n across the groups as evenly as possible
        raw_assignment = []
        for i in range(total_n):
            raw_assignment.append(groups[i % len(groups)])

        # 3. Randomize with Seed 24s
        random.seed(24)
        random.shuffle(raw_assignment)

        # 4. Process with Cumulative Counts
        final_data = []
        counts = {group: 0 for group in groups}
        
        for i in range(total_n):
            sub_id = f"{proj_code}_{str(i+1).zfill(3)}"
            group_name = raw_assignment[i]
            counts[group_name] += 1
            assigned_val = f"{group_name}_{str(counts[group_name]).zfill(2)}"
            
            final_data.append([sub_id, assigned_val])

        # 5. Export to CSV
        file_path = os.path.join(output_dir, "grouprand.csv")
        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["subject code", "assigned group"])
                writer.writerows(final_data)
            
            messagebox.showinfo("Success", f"File saved successfully at:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = GroupRandomizer(root)
    root.mainloop()