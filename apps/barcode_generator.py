import os
import tkinter as tk
from tkinter import filedialog, messagebox
import barcode
from barcode.writer import ImageWriter

class BarcodeGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WorkSmart | Barcode Generator")
        self.root.geometry("450x350")
        self.root.resizable(False, False)

        # Main Frame
        frame = tk.Frame(self.root, padx=25, pady=25)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="WorkSmart Barcode Generator", font=("Arial", 16, "bold")).pack(pady=(0, 20))

        # Project Code Input
        f1 = tk.Frame(frame)
        f1.pack(fill="x", pady=8)
        tk.Label(f1, text="Project Code (e.g. ABC):", width=20, anchor="w", font=("Arial", 10)).pack(side="left")
        self.ent_proj = tk.Entry(f1, font=("Arial", 11), width=15)
        self.ent_proj.pack(side="left")
        self.ent_proj.insert(0, "ABC")

        # Number of Participants Input
        f2 = tk.Frame(frame)
        f2.pack(fill="x", pady=8)
        tk.Label(f2, text="Total Participants:", width=20, anchor="w", font=("Arial", 10)).pack(side="left")
        self.ent_count = tk.Entry(f2, font=("Arial", 11), width=15)
        self.ent_count.pack(side="left")
        self.ent_count.insert(0, "300")

        # Status Label
        self.lbl_status = tk.Label(frame, text="", fg="blue", font=("Arial", 9))
        self.lbl_status.pack(pady=5)

        # Generate Button
        tk.Button(frame, text="Generate Batch PNGs", bg="#2ecc71", fg="black", font=("Arial", 11, "bold"), pady=5, command=self.generate_barcodes).pack(fill="x", pady=15)

    def generate_barcodes(self):
        proj_code = self.ent_proj.get().strip().upper()
        try:
            count = int(self.ent_count.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid integer for total participants.")
            return

        if not proj_code:
            messagebox.showerror("Error", "Project code cannot be empty.")
            return

        # Ask user where to save the batch folder
        save_dir = filedialog.askdirectory(title="Select Output Folder for Barcodes")
        if not save_dir:
            return

        # Create a subfolder for this batch
        batch_folder = os.path.join(save_dir, f"{proj_code}_Barcodes")
        if not os.path.exists(batch_folder):
            os.makedirs(batch_folder)

        try:
            # Code 128 supports alphanumeric text (letters + numbers)
            code_class = barcode.get_barcode_class('code128')
            
            for i in range(1, count + 1):
                # Format with zero padding (e.g., ABC001, ABC002... ABC300)
                participant_id = f"{proj_code}{i:d}"
                
                # Generate barcode image using ImageWriter
                barcode_obj = code_class(participant_id, writer=ImageWriter())
                
                # Save as PNG
                file_path_base = os.path.join(batch_folder, participant_id)
                barcode_obj.save(file_path_base)
                
                if i % 50 == 0 or i == count:
                    self.lbl_status.config(text=f"Generated {i}/{count} barcodes...")
                    self.root.update_idletasks()

            messagebox.showinfo("Success", f"Successfully generated {count} barcodes inside:\n{batch_folder}")
            self.lbl_status.config(text="Done!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate barcodes: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = BarcodeGeneratorApp(root)
    root.mainloop()