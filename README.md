# WorkSmart 1.2

Work smarter, play harder.

## **Quick Setup (for mac)**

(1) Download the Project
Scroll to the top of this GitHub page.
Click the green "<> Code" button.
Select "Download ZIP".
Find the downloaded folder in your computer, right-click it, and select "Extract All". Move this extracted folder to a permanent spot (like your Documents folder).

(2) Install Python & Conda
The app needs a specific "environment" to run properly.
Open your terminal (Command Prompt on Windows, or Terminal on Mac).
Navigate to the folder you just extracted:
Bash
cd (copy your folder path here)

Create the environment using the provided file:
Bash
conda env create -f environment.yml

(3) Create a Desktop Shortcut
Instead of typing code every time, let's make a "Double-Click" icon for your desktop.

For Mac Users:

Open the Automator app (found in Applications).

Select New Document > Application.

Search for "Run Shell Script" and drag it into the window.

Paste the following inside (adjust the path to your folder):

Bash
source ~/anaconda3/bin/activate WorkSmart
python ~/Documents/WorkSmart/apps/timestamper/timestamper.py
Save it to your Desktop as "WorkSmart Timestamper".

(4) How to Use
Launch: Double-click your new desktop icon.

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
