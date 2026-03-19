#!/bin/bash

# 1. Dynamically find where this folder is
PARENT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$PARENT_DIR"

# 2. Find your Conda base path automatically
# This handles both Intel and Apple Silicon (M1/M2/M3) default paths
if [ -f "$HOME/opt/anaconda3/bin/activate" ]; then
    CONDA_PATH="$HOME/opt/anaconda3"
elif [ -f "$HOME/anaconda3/bin/activate" ]; then
    CONDA_PATH="$HOME/anaconda3"
elif [ -f "$HOME/miniconda3/bin/activate" ]; then
    CONDA_PATH="$HOME/miniconda3"
else
    # If you installed conda elsewhere, paste the path to the folder containing 'bin' here:
    CONDA_PATH="/opt/homebrew/Conda" 
fi

# 3. THE CRITICAL FIX: Source the conda.sh directly to enable 'conda activate'
source "$CONDA_PATH/etc/profile.d/conda.sh"

# 4. Activate the specific environment
conda activate WorkSmart

# 5. Run the hub using the environment's python
python main.py