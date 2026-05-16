$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$RepoRoot = $PSScriptRoot
$VenvDir  = Join-Path $RepoRoot "evomas\venv"
$PythonEvomas = Join-Path $VenvDir "Scripts\python.exe"
$EvomasExe    = Join-Path $VenvDir "Scripts\evomas.exe"

function Test-Cli($name, $hint) {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Host "[setup] missing prerequisite: $name" -ForegroundColor Yellow
        Write-Host "        $hint"
        return $false
    }
    Write-Host "[setup] found $name -> $($found.Source)"
    return $true
}

# --- 1. Prerequisite checks --------------------------------------------------
Write-Host "[setup] checking prerequisites" -ForegroundColor Cyan
$pythonOk = Test-Cli "python" "Install Python 3.12+ from https://www.python.org/downloads/ (Python 3.12.6 is the dev baseline)."
$ollamaOk = Test-Cli "ollama" "Install Ollama from https://ollama.com/download."
$dockerOk = Test-Cli "docker" "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ (required for SWE-bench evaluation)."
$npmOk    = Test-Cli "npm"    "Install Node.js 18+ from https://nodejs.org/ (needed for the Angular frontend)."

if (-not $pythonOk) {
    Write-Host "[setup] python is mandatory; aborting." -ForegroundColor Red
    exit 1
}
if (-not $ollamaOk) {
    Write-Host "[setup] continuing without ollama -- `evomas ollama *` will fail until you install it."
}
if (-not $dockerOk) {
    Write-Host "[setup] continuing without docker -- `evomas run evaluation` will fail until you install it."
}
if (-not $npmOk) {
    Write-Host "[setup] continuing without npm -- `evomas web` will fail until you install Node.js."
}

# --- 2. Ensure the venv exists -----------------------------------------------
# `setup.ps1` is non-destructive: we never delete an existing venv, since
# that wipes any in-flight work or manually-installed extras. If something
# in the venv is broken, the user should remove it themselves and rerun
# setup -- see the troubleshooting section in README.md.
if (Test-Path $VenvDir) {
    Write-Host "[setup] reusing existing venv at $VenvDir (pass through pip resolves any drift)" -ForegroundColor Cyan
} else {
    Write-Host "[setup] creating venv at $VenvDir" -ForegroundColor Cyan
    python -m venv $VenvDir
}

Write-Host "[setup] upgrading pip + wheel" -ForegroundColor Cyan
& $PythonEvomas -m pip install --upgrade pip wheel

# --- 3. Install the project --------------------------------------------------
# `-e .` reads pyproject.toml; deps are pinned there and an `evomas` console
# script is registered against `evomas.cli:main`. No more hand-maintained
# `pip install langchain langgraph ...` list.
Write-Host "[setup] installing evomas (editable) + dependencies + dev extras" -ForegroundColor Cyan
& $PythonEvomas -m pip install -e ".[dev]"

# Snapshot exact resolved versions to requirements.txt for reproducibility /
# recovery if a downstream package ships a breaking release. pyproject.toml
# stays the canonical input; this file is a regenerated lockfile.
Write-Host "[setup] freezing pinned versions to requirements.txt" -ForegroundColor Cyan
& $PythonEvomas -m pip freeze | Out-File -Encoding utf8 (Join-Path $RepoRoot "requirements.txt")

# --- 4. Install npm deps for the Angular frontend ---------------------------
# Without this, `npx ng serve` (invoked by `evomas web` / start_frontend.ps1)
# resolves `ng` against the global npm registry, fetches the wrong package,
# and exits with "could not determine executable to run". `npm install`
# populates app\node_modules so npx finds the Angular CLI locally.
if ($npmOk) {
    Write-Host "[setup] installing app\ npm dependencies (Angular CLI + project deps)" -ForegroundColor Cyan
    Push-Location (Join-Path $RepoRoot "app")
    try {
        npm install --no-audit --no-fund
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[setup] skipping npm install -- node/npm not available." -ForegroundColor Yellow
}

# --- 5. PowerShell $PROFILE wrapper -----------------------------------------
# pip install -e . registers `evomas.exe` inside the venv. To call it from
# anywhere without activating the venv first, append a function to the
# user's PowerShell profile that delegates to the venv's exe.
$ProfilePath = $PROFILE
$ProfileDir  = Split-Path -Parent $ProfilePath
if (-not (Test-Path $ProfileDir)) { New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null }
if (-not (Test-Path $ProfilePath)) { New-Item -ItemType File -Path $ProfilePath -Force | Out-Null }

$Marker = "# >>> evomas-cli >>>"
$EndMarker = "# <<< evomas-cli <<<"
$existing = Get-Content $ProfilePath -Raw -ErrorAction SilentlyContinue
if ($existing -and $existing.Contains($Marker)) {
    Write-Host "[setup] refreshing existing evomas function in $ProfilePath" -ForegroundColor Cyan
    $pattern = "(?ms)" + [regex]::Escape($Marker) + ".*?" + [regex]::Escape($EndMarker)
    $existing = [regex]::Replace($existing, $pattern, "").TrimEnd() + "`r`n"
    Set-Content -Path $ProfilePath -Value $existing -Encoding utf8
}

$Block = @"
$Marker
function evomas {
    & "$EvomasExe" @args
}
$EndMarker
"@
Add-Content -Path $ProfilePath -Value $Block -Encoding utf8
Write-Host "[setup] appended evomas function to $ProfilePath" -ForegroundColor Green

# --- 6. .env scaffolding hint ------------------------------------------------
if (-not (Test-Path (Join-Path $RepoRoot "evomas\.env"))) {
    Write-Host "[setup] reminder: copy evomas\.env.example -> evomas\.env and fill in OLLAMA_BASE_URL" -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $RepoRoot "api\.env"))) {
    Write-Host "[setup] reminder: copy api\.env.example -> api\.env if you need to override API_HOST / API_PORT" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[setup] done." -ForegroundColor Green
Write-Host "        Open a fresh PowerShell window so the new \$PROFILE function loads, then:"
Write-Host ""
Write-Host "          evomas --help                                  # uses the venv automatically via the profile function"
Write-Host ""
Write-Host "        For interactive dev work (running pytest, importing evomas modules, etc.)"
Write-Host "        activate the venv directly:"
Write-Host ""
Write-Host "          .\evomas\venv\Scripts\Activate.ps1             # then `python`, `pytest`, `pip` target the venv"
Write-Host "          deactivate                                     # leaves the venv"
