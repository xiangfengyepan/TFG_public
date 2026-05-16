# `$PSScriptRoot` now points at `scripts/`; the Angular app lives at the
# repo root, so step up one directory before resolving the path.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir   = Join-Path $RepoRoot "app"

# Self-heal: if a contributor invokes `evomas web` without running setup
# first (or just `git pull`ed and forgot), `npx ng serve` will fetch the
# wrong `ng` package from npmjs and exit with "could not determine
# executable to run". Install local deps once if node_modules is absent.
if (-not (Test-Path (Join-Path $AppDir "node_modules"))) {
    Write-Host "[start_frontend] app\node_modules missing -- running 'npm install' first" -ForegroundColor Yellow
    Push-Location $AppDir
    try {
        npm install --no-audit --no-fund
    } finally {
        Pop-Location
    }
}

Write-Host "Starting EvoMas Angular frontend on http://localhost:4200"
Push-Location $AppDir
try {
    npx ng serve --open
} finally {
    Pop-Location
}
