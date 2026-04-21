<#
.SYNOPSIS
  Generate the SWE-bench graph and open it in Gephi Lite.

.PARAMETER Layout
  Layout name to use: radial (default) or hierarchical.

.PARAMETER SkipGenerate
  Skip GEXF and session generation (jump straight to Gephi Lite).

.EXAMPLE
  .\run.ps1
  .\run.ps1 -Layout hierarchical
  .\run.ps1 -SkipGenerate
#>
param(
    [string]$Layout = "radial",
    [switch]$SkipGenerate
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

# ── Ensure selenium ───────────────────────────────────────────────────────────
Write-Host "Checking selenium..."
$seleniumVer = & $pythonCmd -c "import selenium; print(selenium.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Not found. Installing..."
    & $pythonCmd -m pip install --quiet selenium
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install selenium failed."; exit 1 }
    Write-Host "  Installed."
} else {
    Write-Host "  OK (v$seleniumVer)"
}

if (-not $SkipGenerate) {
    # ── Generate GEXF ──────────────────────────────────────────────────────────
    Write-Host "`nGenerating GEXF..."
    & $pythonCmd "$ScriptDir\generate_gexf.py"
    if ($LASTEXITCODE -ne 0) { Write-Error "generate_gexf.py failed."; exit 1 }

    # ── Generate per-layout session JSON files ─────────────────────────────────
    Write-Host "`nGenerating session files..."
    & $pythonCmd "$ScriptDir\generate_sessions.py"
    if ($LASTEXITCODE -ne 0) { Write-Error "generate_sessions.py failed."; exit 1 }
}

# ── Open Gephi Lite ───────────────────────────────────────────────────────────
Write-Host "`nLaunching Gephi Lite (layout=$Layout)..."
& $pythonCmd "$ScriptDir\open_gephi.py" --layout $Layout
