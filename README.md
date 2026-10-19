# WorkSmart 1.3

Work smarter, play harder.

## **Quick Setup (for mac)**

1. Download the Project

Scroll to the top of this GitHub page.
Click the green "<> Code" button.
Select "Download ZIP".
Find the downloaded ZIP file and double-click it to extract the folder. Move this extracted folder to a permanent spot (like your Documents folder).

The project root is the folder containing `main.py` and `environment.yml`.

The Integrated Timestamper folder should be located at:

```text
WorkSmart/
├── main.py
├── environment.yml
├── requirements.txt
└── apps/
    └── integrated_timestamper/
```

Keep the other existing project files and app folders in place.

2. Install Python & Conda

The app needs a specific "environment" to run properly.

If Conda is not already installed:

- Download a macOS installer for Miniconda or Anaconda from its official website. Choose an installer compatible with your Mac.
- Follow the installation instructions, including terminal initialization.
- Close and reopen Terminal after installation.

If you already have a working Conda installation, you do not need to install another one.

Check that Conda is available:

```bash
conda --version
```

Open Terminal and navigate to the project folder:

```bash
cd "/full/path/to/WorkSmart"
```

Replace `/full/path/to/WorkSmart` with the actual folder path.

Before creating the environment, open `environment.yml`. If it contains the following machine-specific line, remove that line so the environment can be installed on your own computer:

```yaml
prefix: /Users/fib./anaconda3/envs/WorkSmart
```

Create the environment using the provided file:

```bash
conda env create -f environment.yml
```

Activate it:

```bash
conda activate WorkSmart
```

The supplied environment file includes Python 3.14, Tcl/Tk, OpenCV, pandas, NumPy, Ghostscript, and Pillow 12.1.1.

The Barcode Generator also requires `python-barcode`. Install it after activating the environment:

```bash
python -m pip install python-barcode
```

If `python-barcode` has already been added to the `pip:` section of `environment.yml`, this separate installation step is not needed.

Start the main dashboard:

```bash
python main.py
```

Click **Integrated Timestamper** to open the integrated timestamping app.

The original **Timestamper** remains available as a separate option.

### Dependencies and requirements.txt

The project's Python dependency list is:

```text
numpy
pandas
opencv-python
pillow==12.1.1
python-barcode
```

Save this list as `requirements.txt` in the project root.

This list is based on the supplied environment file and main dashboard. Additional dependencies specific to the Integrated Timestamper still need to be checked against its source code.

`requirements.txt` does not install Python, the Tcl/Tk runtime, or the Ghostscript executable. The Conda setup handles these separately.

**Use one of the following installation routes, not both:**

- **Recommended:** Follow the `environment.yml` setup above. You do not also need to install the complete `requirements.txt`.
- **Alternative:** Create a separate environment with Python and the system dependencies, then install the Python packages from `requirements.txt`:

```bash
cd "/full/path/to/WorkSmart"
conda create -n WorkSmart-pip -c conda-forge python=3.14 tk tcl ghostscript pip
conda activate WorkSmart-pip
python -m pip install -r requirements.txt
python main.py
```

If you choose the alternative route, use `WorkSmart-pip` instead of `WorkSmart` in the launch and shortcut instructions below.

3. Create a Desktop Shortcut

Instead of typing code every time, let's make a "Double-Click" icon for your desktop.

For Mac Users:

1. Open Terminal and find your Conda installation folder:

```bash
conda info --base
```

2. Open the Automator app (found in Applications).
3. Select New Document > Application.
4. Search for "Run Shell Script" and drag it into the window.
5. Select `/bin/zsh` as the shell.
6. Paste the following inside, adjusting both paths:

```bash
source "/full/path/to/conda/etc/profile.d/conda.sh"
conda activate WorkSmart
cd "/full/path/to/WorkSmart"
python main.py
```

Replace `/full/path/to/conda` with the path returned by `conda info --base`.

Replace `/full/path/to/WorkSmart` with your project folder.

7. Save it to your Desktop as "WorkSmart".
8. Launch: Double-click your new desktop icon.
9. Click **Integrated Timestamper** in the main dashboard.

This shortcut opens the main dashboard rather than launching the original timestamper directly.

### Launch from terminal (run line by line):

After completing the first-time setup:

```bash
cd "/full/path/to/WorkSmart"
conda activate WorkSmart
python main.py
```

You only need to create the environment during the initial setup, not every time you launch the app.

## 🚀 Integrated Timestamper

The integrated timestamping app is available from the main dashboard.

1. Launch `main.py`.
2. Click **Integrated Timestamper**.

Its application folder is:

```text
apps/integrated_timestamper/
```

The `apps` folder is located directly under the project root, alongside `main.py`.

The original **Timestamper** remains available as a separate dashboard option.

## 🚀 Group Randomization

Inputs needed: Name of groups, Project code, total number of subjects, output folder 

Assign groups to subjects. Randomize using seed 24. Output to target folder as csv. 

## 🚀 Trial Randomization

Allowing creation of blocks and by block configuration of included trial types, output to target folder as csv. 

## 🚀 Crop and Blind 

Allowing cropping and blinding of avi files. 

1. **Hotkeys:**
   | Key | Action | 
   | :--- | :--- | 
   | **R** | Reset bounding box during crop | 

## 🚀 Timestamper (png, one trial = one folder of pngs)
0. **Project Setup**
Create a new project configuration for your own project timestamping needs:
   | Configs | Action | 
   | :--- | :--- | 
   | Project name | Name of the project, save as json that can be reopened when you reopen app next time. | 
   | Timestamps | Allowing maximum of ten, comma separated. Auto assigning hotkeys 1-9 and 0. | 
   | Var | Text input variables for project, comma separated. Auto input "nil" if none is typed in. | 
   | FPS | Frame per second, can roughly set align with dataset for easy play/pause. |
   | Parent folder | The folder that you store all folders of pngs. | 
   | Output csv | Where you store the data. | 

1. **Hotkeys:**
   | Key | Action | 
   | :--- | :--- | 
   | **Space** | Play/Pause Video |
   | **Left/Right Arrows** | Step 1 frame back/forward |
   | **1 - 6** | Marking of frames |
   | **R** | Return to Frame 0 |
   | **Enter** | Submit Data & Load Next Trial |

Enable hotkeys by clicking on the ultrasound image to re-enable them.

2. **Natvigation**
    Use the "Go to" dropdown to skip to specific trials.
    When you reach the end, the app will automatically tell you if any trials were missed by checking the folder names inside the parent folder against the trials on the csv file. 

## 🚀 Trial Judgment (avi)
1. **Hotkeys:**
   | Key | Action | 
   | :--- | :--- | 
   | **Space** | Play/Pause Video |
   | **1** | Success |
   | **0** | Failure |
   | **R** | Return to Frame 0 |
   | **Enter** | Submit Data & Load Next Trial |

Enable hotkeys by clicking on the ultrasound image to re-enable them.

2. **Natvigation**
    Use the "Go to" dropdown to skip to specific trials.
    When you reach the end, the app will automatically tell you if any trials were missed by checking the folder names inside the parent folder against the trials on the csv file.
