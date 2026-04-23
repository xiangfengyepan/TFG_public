# ==========================================================
# MAS-AutoRepair Setup (Windows PowerShell)
# ==========================================================

# Set PYTHONPATH to the current directory
Write-Host "Setting PYTHONPATH..." -ForegroundColor Cyan
$env:PYTHONPATH = "$($PWD.Path)"

# Step 1: Create Python virtual environment
Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
python -m venv venv_win

# Step 2: Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.\venv_win\Scripts\Activate.ps1

# Step 3: Upgrade pip and install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
