<#
.SYNOPSIS
  Run the prompt analysis script and write prompt_analysis.csv.

.PARAMETER InputFolder
  Folder containing the per-repo agent CSVs (default: agents_csv).

.PARAMETER OutputFile
  Path for the output CSV (default: prompt_analysis.csv).

.EXAMPLE
  .\run.ps1
  .\run.ps1 -InputFolder my_csvs -OutputFile out.csv
#>
param(
    [string]$InputFolder = "agents_csv",
    [string]$OutputFile  = "prompt_analysis.csv"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# ── Locate Python 3 ───────────────────────────────────────────────────────────
Write-Host "Checking Python..."
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $v = & $cmd --version 2>&1
        if ("$v" -match "Python 3") { $pythonCmd = $cmd; break }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Error "Python 3 not found. Install it and ensure it is on PATH."
    exit 1
}
Write-Host "  $((& $pythonCmd --version 2>&1))"

# ── Validate input folder ──────────────────────────────────────────────────────
$resolvedInput = Join-Path $ScriptDir $InputFolder
if (-not (Test-Path $resolvedInput)) {
    Write-Error "Input folder not found: $resolvedInput"
    exit 1
}
Write-Host "  Input folder : $resolvedInput"
Write-Host "  Output file  : $(Join-Path $ScriptDir $OutputFile)"

# ── Run analysis ───────────────────────────────────────────────────────────────
Write-Host "`nRunning prompt_analysis.py..."
& $pythonCmd "$ScriptDir\prompt_analysis.py" `
    --input-folder $InputFolder `
    --output-file  $OutputFile
if ($LASTEXITCODE -ne 0) { Write-Error "prompt_analysis.py failed."; exit 1 }

Write-Host "`nDone. Output written to $(Join-Path $ScriptDir $OutputFile)"
