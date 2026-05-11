<#
.SYNOPSIS
  Generate the SWE-bench graph and open it in Gephi Lite (local or online).

.PARAMETER Mode
  Where to open Gephi Lite: 'local' (default) starts the local dev server
  from ./gephi-lite, 'online' uses the public https://lite.gephi.org/ instance.

.PARAMETER Layout
  Layout name to use: radial (default) or hierarchical.

.PARAMETER SkipGenerate
  Skip GEXF and session generation (jump straight to Gephi Lite).

.EXAMPLE
  .\run.ps1
  .\run.ps1 -Mode online
  .\run.ps1 -Layout hierarchical
  .\run.ps1 -Mode online -Layout hierarchical
  .\run.ps1 -SkipGenerate
#>
param(
    [ValidateSet("local", "online")]
    [string]$Mode = "local",
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

# ── Local-mode prerequisites: gephi-lite clone + node_modules ────────────────
if ($Mode -eq "local") {
    $GephiDir = Join-Path $ScriptDir "gephi-lite"
    if (-not (Test-Path $GephiDir)) {
        Write-Error @"
Local mode requires the gephi-lite repo cloned at: $GephiDir

Run:
  git clone https://github.com/gephi/gephi-lite.git "$GephiDir"
  cd "$GephiDir"
  npm install

Or use online mode instead: .\run.ps1 -Mode online
"@
        exit 1
    }
    if (-not (Test-Path (Join-Path $GephiDir "node_modules"))) {
        Write-Error @"
gephi-lite is cloned but dependencies are not installed.

Run:
  cd "$GephiDir"
  npm install

Or use online mode instead: .\run.ps1 -Mode online
"@
        exit 1
    }
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
Write-Host "`nLaunching Gephi Lite (mode=$Mode, layout=$Layout)..."
if ($Mode -eq "local") {
    & $pythonCmd "$ScriptDir\open_gephi.py" --layout $Layout --local --start-server
} else {
    & $pythonCmd "$ScriptDir\open_gephi.py" --layout $Layout
}
