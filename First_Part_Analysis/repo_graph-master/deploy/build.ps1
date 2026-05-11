#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build a static deploy of gephi-lite with the SWE-bench graph baked in.

.DESCRIPTION
    Produces a self-contained static site that loads one of the GEXFs in
    exports/: exports/swe_bench_graph.gexf when no ?repo= is given, or
    exports/repo_<id>.gexf when ?repo=<id> is set. The layout to apply is
    selected via ?layout=<radial|hierarchical>.

    Prerequisite: exports/ must already be populated. Run `.\generate.ps1`
    first (locally or in CI) to produce the per-repo GEXFs.

    Run by GitHub Actions on push to main. Can also be run locally to test.

.PARAMETER OutputDir
    Directory where the final static site lands. Default: deploy\dist.

.PARAMETER BasePath
    Vite BASE_URL — the path prefix the deploy will be served from.
    For TFG_public deployed at /repo-graph/ that's "/TFG_public/repo-graph/".

.PARAMETER GephiRepo
    Git URL of the gephi-lite repo to clone.

.PARAMETER GephiRef
    Branch / tag of gephi-lite to check out. Pin to a tag for reproducibility.

.PARAMETER GephiSrc
    If supplied, use this existing gephi-lite checkout instead of cloning.
    Useful for local testing (e.g. -GephiSrc ..\gephi-lite).

.EXAMPLE
    .\deploy\build.ps1
    .\deploy\build.ps1 -BasePath "/TFG_public/repo-graph/"
    .\deploy\build.ps1 -GephiSrc ..\gephi-lite -OutputDir .\deploy\dist-test
#>
param(
    [string]$OutputDir,
    [string]$BasePath  = "/TFG_public/repo-graph/",
    [string]$GephiRepo = "https://github.com/gephi/gephi-lite.git",
    [string]$GephiRef  = "main",
    [string]$GephiSrc  = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$here     = $PSScriptRoot
$repoRoot = Split-Path -Parent $here

if (-not $OutputDir) { $OutputDir = Join-Path $here "dist" }
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

Write-Host "── Build configuration ──────────────────────────────────────────────"
Write-Host "  Source        : $repoRoot"
Write-Host "  Output        : $OutputDir"
Write-Host "  BASE_URL      : $BasePath"
if ($GephiSrc) {
    Write-Host "  gephi-lite    : $GephiSrc  (provided)"
} else {
    Write-Host "  gephi-lite    : $GephiRepo @ $GephiRef  (will clone)"
}
Write-Host ""

# ── Locate Python ─────────────────────────────────────────────────────────────
$py = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $ver = & $cmd --version 2>&1
        if ("$ver" -match "Python 3") { $py = $cmd; break }
    }
}
if (-not $py) { Write-Error "Python 3 not found."; exit 1 }
Write-Host "Python: $((& $py --version))"

# ── Regenerate per-layout session JSONs ──────────────────────────────────────
Write-Host "`nGenerating session JSONs..."
& $py (Join-Path $repoRoot "generate_sessions.py")
if ($LASTEXITCODE -ne 0) { Write-Error "generate_sessions.py failed."; exit 1 }

# ── Verify per-repo pre-filtered GEXFs exist ─────────────────────────────────
# The deploy ships every .gexf in exports/. Two kinds of files live there:
#   - exports/swe_bench_graph.gexf       → served as the no-?repo= default
#   - exports/repo_<id>.gexf             → served when ?repo=<id> is set
$exportsDir = Join-Path $repoRoot "exports"
if (-not (Test-Path $exportsDir)) {
    Write-Error @"
Per-repo pre-filtered GEXFs not found at: $exportsDir

Run `.\generate.ps1` first to produce them.
"@
    exit 1
}
$exportFiles = @(Get-ChildItem -Path $exportsDir -Filter "*.gexf" -File)
if ($exportFiles.Count -eq 0) {
    Write-Error "No .gexf files found in $exportsDir. Run `.\generate.ps1` first."
    exit 1
}
$defaultGexfName = "swe_bench_graph.gexf"
if (-not ($exportFiles | Where-Object { $_.Name -eq $defaultGexfName })) {
    Write-Error "Expected '$defaultGexfName' in $exportsDir (served as the no-?repo= default). Run `.\generate.ps1` first."
    exit 1
}
Write-Host "Found $($exportFiles.Count) GEXFs in $exportsDir (including the default $defaultGexfName)"

# ── Prepare gephi-lite checkout ──────────────────────────────────────────────
if ($GephiSrc) {
    $gephiDir = [System.IO.Path]::GetFullPath($GephiSrc)
    if (-not (Test-Path $gephiDir)) {
        Write-Error "GephiSrc directory not found: $gephiDir"
        exit 1
    }
    Write-Host "`nUsing existing gephi-lite checkout: $gephiDir"
} else {
    $gephiDir = Join-Path $here "_gephi-lite-src"
    if (Test-Path $gephiDir) {
        Write-Host "`nUpdating gephi-lite checkout..."
        Push-Location $gephiDir
        git fetch --depth 1 origin $GephiRef
        git checkout FETCH_HEAD
        Pop-Location
    } else {
        Write-Host "`nCloning gephi-lite ($GephiRef)..."
        git clone --depth 1 --branch $GephiRef $GephiRepo $gephiDir
        if ($LASTEXITCODE -ne 0) { Write-Error "git clone failed."; exit 1 }
    }
}

# ── Install npm deps if missing ──────────────────────────────────────────────
if (-not (Test-Path (Join-Path $gephiDir "node_modules"))) {
    Write-Host "Installing npm dependencies (this can take a few minutes)..."
    Push-Location $gephiDir
    npm ci
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        Write-Error "npm ci failed."
        exit 1
    }
    Pop-Location
}

# ── Build the repo -> filename map from exports/ ─────────────────────────────
# Only include "repo_<id>.gexf" entries; the default GEXF is handled separately.
$repoMap = @{}
foreach ($f in $exportFiles) {
    if ($f.BaseName -like "repo_*") {
        $repoMap[$f.BaseName] = $f.Name
    }
}
$repoMapJson = $repoMap | ConvertTo-Json -Depth 3 -Compress
# ConvertTo-Json renders an empty hashtable as "" rather than "{}", protect that.
if (-not $repoMapJson -or $repoMapJson -eq '""') { $repoMapJson = '{}' }

# ── Inline session + repo map into boot.js ───────────────────────────────────
Write-Host "`nGenerating boot.js..."
$bootTemplate  = [System.IO.File]::ReadAllText((Join-Path $here "boot.template.js"))
$sessionRadial = [System.IO.File]::ReadAllText((Join-Path $repoRoot "config\session_radial.json"))
$sessionHier   = [System.IO.File]::ReadAllText((Join-Path $repoRoot "config\session_hierarchical.json"))

$bootJs = $bootTemplate
$bootJs = $bootJs.Replace("/*__SESSION_RADIAL__*/        null",       $sessionRadial)
$bootJs = $bootJs.Replace("/*__SESSION_HIERARCHICAL__*/  null",       $sessionHier)
$bootJs = $bootJs.Replace('/*__REPO_GEXF_MAP__*/ {}',                 $repoMapJson)
$bootJs = $bootJs.Replace('/*__DEFAULT_GEXF__*/ "swe_bench_graph.gexf"', '"swe_bench_graph.gexf"')

# ── Place boot.js + GEXFs in gephi-lite's public/ folder ─────────────────────
$pkgDir    = Join-Path $gephiDir "packages\gephi-lite"
$publicDir = Join-Path $pkgDir "public"
New-Item -ItemType Directory -Force -Path $publicDir | Out-Null
[System.IO.File]::WriteAllText((Join-Path $publicDir "boot.js"), $bootJs)

# Every .gexf in exports/ (default + per-repo)
foreach ($f in $exportFiles) {
    Copy-Item -Force $f.FullName (Join-Path $publicDir $f.Name)
}
Write-Host "  Wrote boot.js + $($exportFiles.Count) GEXFs to public\ (1 default + $($repoMap.Count) per-repo)"

# ── Patch index.html to load boot.js BEFORE the module bundle ────────────────
$indexHtml = Join-Path $pkgDir "index.html"
$html      = [System.IO.File]::ReadAllText($indexHtml)
$injection = '<script src="./boot.js"></script>'
if ($html -notmatch [regex]::Escape($injection)) {
    if ($html -notmatch '<script\s+type="module"\s+src=') {
        Write-Error "Could not find module script tag in $indexHtml — gephi-lite layout changed?"
        exit 1
    }
    $html = $html -replace '(<script\s+type="module"\s+src=)', "$injection`r`n    `$1"
    [System.IO.File]::WriteAllText($indexHtml, $html)
    Write-Host "  Patched index.html (injected boot.js)"
} else {
    Write-Host "  index.html already patched"
}

# ── Build ────────────────────────────────────────────────────────────────────
Write-Host "`nRunning npm build (BASE_URL=$BasePath)..."
$env:BASE_URL = $BasePath
Push-Location $gephiDir
npm run build --workspace=@gephi/gephi-lite
$buildExit = $LASTEXITCODE
Pop-Location
if ($buildExit -ne 0) { Write-Error "npm run build failed."; exit 1 }

# ── Copy build output to $OutputDir ──────────────────────────────────────────
$buildSrc = Join-Path $pkgDir "build"
if (-not (Test-Path $buildSrc)) {
    Write-Error "Expected build output not found: $buildSrc"
    exit 1
}
if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $buildSrc "*") $OutputDir

Write-Host "`n══ Build complete ═══════════════════════════════════════════════════"
Write-Host "  Static site : $OutputDir"
Write-Host "  Served at   : https://xiangfengyepan.github.io$BasePath"
Write-Host "  Example URL : https://xiangfengyepan.github.io${BasePath}?repo=repo_OpenHands&layout=hierarchical"
