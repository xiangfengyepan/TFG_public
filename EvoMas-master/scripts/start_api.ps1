# `$PSScriptRoot` now points at `scripts/`; the API server lives at the
# repo root, so step up one directory before resolving sibling paths.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$envFile = Join-Path $RepoRoot "api\.env"
$apiHost = "0.0.0.0"
$apiPort = "8000"

# Parse api/.env for API_HOST / API_PORT (skip blanks and comments).
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#")) { continue }
        $kv = $trim -split "=", 2
        if ($kv.Length -ne 2) { continue }
        $k = $kv[0].Trim()
        $v = $kv[1].Trim().Trim('"').Trim("'")
        switch ($k) {
            "API_HOST" { $apiHost = $v }
            "API_PORT" { $apiPort = $v }
        }
    }
}

# Venv installed by setup.ps1 to `~\.evomas-venv` (in the user's home so
# the repo stays free of build artefacts).
$VenvDir = Join-Path $HOME ".evomas-venv"
$Uvicorn = Join-Path $VenvDir "Scripts\uvicorn.exe"
if (-not (Test-Path $Uvicorn)) {
    Write-Host "[start_api] uvicorn not found at $Uvicorn -- run setup.ps1 first." -ForegroundColor Red
    exit 1
}
Write-Host "Starting EvoMas API server on http://$($apiHost):$($apiPort)"
& $Uvicorn --app-dir "$RepoRoot\api" server:app --host $apiHost --port $apiPort --reload
