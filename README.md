# WorkSmart 1.1

Work smarter, sleep earlier. 

1. **Setup Environment:**
   ```bash
   conda env create -f environment.yml
   conda activate WorkSmart
2. **Run App:**
   ```bash
    python worksmart.py

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

## 🚀 Timestamper

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