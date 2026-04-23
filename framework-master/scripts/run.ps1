# ==========================================================
# MAS-AutoRepair Run (Windows PowerShell)
# ==========================================================

# Set PYTHONPATH so the tests folder can import from your root project folders
Write-Host "Setting PYTHONPATH..." -ForegroundColor Cyan
$env:PYTHONPATH = "$($PWD.Path)"

# Step 1: Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
.\venv_win\Scripts\Activate.ps1

# Step 2: Run the Star Topology main script
Write-Host "Running core/workflow.py..." -ForegroundColor Cyan
python app/src/core/workflow.py