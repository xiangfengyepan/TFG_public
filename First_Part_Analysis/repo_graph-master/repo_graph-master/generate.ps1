#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Generate filtered GEXF (and optionally PNG) files for each repo node using open_gephi.py.

.PARAMETER OutputDir
    Directory where the exported files are saved. Default: .\exports

.PARAMETER Layout
    Gephi Lite layout name passed to open_gephi.py. Default: radial

.PARAMETER Repos
    Comma-separated list of repo node IDs to process.
    If omitted, all repo nodes found in config\dataset.json are used.
    Example: -Repos "repo_OpenHands,repo_Prometheus"

.PARAMETER Replace
    Overwrite output files that already exist. By default existing files are skipped.

.PARAMETER ExportPng
    Also export a PNG snapshot (2480x3508 px) for each repo.

.PARAMETER PngWidth
    PNG export width in pixels. Default: 2480

.PARAMETER PngHeight
    PNG export height in pixels. Default: 3508

.PARAMETER PngLayout
    Layout name used for the PNG snapshot. Default: hierarchical.
    Pass the same value as -Layout to reuse the main layout for the PNG.

.EXAMPLE
    .\generate.ps1
    .\generate.ps1 -OutputDir ".\exports" -Layout radial
    .\generate.ps1 -Repos "repo_OpenHands,repo_Prometheus"
    .\generate.ps1 -Replace
    .\generate.ps1 -ExportPng
    .\generate.ps1 -ExportPng -PngWidth 1920 -PngHeight 1080
#>
param(
    [string]   $OutputDir  = ".\exports",
    [string]   $Layout     = "radial",
    [string]   $Repos      = "",
    [switch]   $Replace,               # Overwrite existing files; skip them by default
    [switch]   $ExportPng,             # Also export a PNG snapshot
    [int]      $PngWidth   = 2480,
    [int]      $PngHeight  = 3508,
    [string]   $PngLayout  = "hierarchical"   # Layout for PNG export
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# When exporting PNG without an explicit -Layout, default to hierarchical.
if ($ExportPng -and -not $PSBoundParameters.ContainsKey('Layout')) {
    $Layout = "hierarchical"
}

$here = $PSScriptRoot

# ── Detect Python ─────────────────────────────────────────────────────────────

$py = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $py = $cmd
            break
        }
    }
}
if (-not $py) {
    Write-Error "Python 3 not found. Install it and add it to PATH."
    exit 1
}
Write-Host "Using Python: $py"

# ── Resolve repo list ──────────────────────────────────────────────────────────

if ($Repos -ne "") {
    $repoList = $Repos -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
} else {
    Write-Host "Reading repo nodes from config\dataset.json..."
    $repoListRaw = & $py -c @"
import json
from pathlib import Path
data = json.loads(Path('config/dataset.json').read_text(encoding='utf-8'))
repos = [k for k, v in data['nodeData'].items() if isinstance(v, dict) and v.get('node_type') == 'repo']
print('\n'.join(repos))
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to read repo nodes from dataset.json"
        exit 1
    }
    $repoList = $repoListRaw -split "`n" | Where-Object { $_.Trim() -ne "" }
}

Write-Host "Repos to process ($($repoList.Count)): $($repoList -join ', ')"

# ── Prepare output dir ────────────────────────────────────────────────────────

$outDir = Join-Path $here $OutputDir
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# ── Process each repo ─────────────────────────────────────────────────────────

$nodeJsPath = Join-Path $here "filters\repo\node.js"
$ok      = 0
$fail    = 0
$skipped = 0

foreach ($repo in $repoList) {
    Write-Host "`n── $repo ─────────────────────────────────"

    $exportFile = Join-Path $outDir "$repo.gexf"
    $pngFile    = Join-Path $outDir "$repo.png"

    # Skip if all requested output files already exist and -Replace was not requested
    $gexfExists = Test-Path $exportFile
    $pngExists  = (-not $ExportPng) -or (Test-Path $pngFile)
    if ($gexfExists -and $pngExists -and -not $Replace) {
        Write-Host "  Skipped (already exists). Use -Replace to overwrite." -ForegroundColor Cyan
        $skipped++
        continue
    }

    # 1. Patch REPO_NODE in filters/repo/node.js
    $content = [System.IO.File]::ReadAllText($nodeJsPath)
    $patched = $content -replace '(const REPO_NODE\s*=\s*")[^"]*(")', "`${1}$repo`${2}"
    if ($patched -eq $content) {
        Write-Warning "  REPO_NODE constant not found in node.js — skipping $repo"
        $fail++
        continue
    }
    [System.IO.File]::WriteAllText($nodeJsPath, $patched)
    Write-Host "  Patched REPO_NODE = `"$repo`""

    # 2. Regenerate config/filters_repo.json
    & $py (Join-Path $here "generate_filters.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "  generate_filters.py failed — skipping $repo"
        $fail++
        continue
    }

    # 3. Run open_gephi.py with export + no-interaction
    $openGephiArgs = @(
        (Join-Path $here "open_gephi.py"),
        "--layout", $Layout,
        "--filter", "repo",
        "--export-path", $exportFile,
        "--no-interaction"
    )
    if ($ExportPng) {
        $openGephiArgs += @(
            "--export-png-path", $pngFile,
            "--png-width",       $PngWidth,
            "--png-height",      $PngHeight,
            "--png-layout",      $PngLayout
        )
    }
    & $py @openGephiArgs

    $repoOk = $true
    if (Test-Path $exportFile) {
        Write-Host "  Saved GEXF: $exportFile" -ForegroundColor Green
    } else {
        Write-Warning "  GEXF not found: $exportFile"
        $repoOk = $false
    }
    if ($ExportPng) {
        if (Test-Path $pngFile) {
            Write-Host "  Saved PNG:  $pngFile" -ForegroundColor Green
        } else {
            Write-Warning "  PNG not found: $pngFile"
            $repoOk = $false
        }
    }

    if ($repoOk) { $ok++ } else { $fail++ }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host "`n══ Done: $ok exported, $skipped skipped, $fail failed ══"
