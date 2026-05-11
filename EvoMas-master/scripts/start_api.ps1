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

Write-Host "Starting EvoMas API server on http://$($apiHost):$($apiPort)"
& "$RepoRoot\evomas\venv\Scripts\uvicorn.exe" --app-dir "$RepoRoot\api" server:app --host $apiHost --port $apiPort --reload
