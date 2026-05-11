# `$PSScriptRoot` now points at `scripts/`; the Angular app lives at the
# repo root, so step up one directory before resolving the path.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Starting EvoMas Angular frontend on http://localhost:4200"
Push-Location "$RepoRoot\app"
try {
    npx ng serve --open
} finally {
    Pop-Location
}
