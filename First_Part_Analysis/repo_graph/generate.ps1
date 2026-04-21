#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Generate a filtered GEXF file for each repo node using open_gephi.py.

.PARAMETER OutputDir
    Directory where the exported GEXF files are saved. Default: .\exports

.PARAMETER Layout
    Gephi Lite layout name passed to open_gephi.py. Default: radial

.PARAMETER Repos
    Comma-separated list of repo node IDs to process.
    If omitted, all repo nodes found in config\dataset.json are used.
    Example: -Repos "repo_OpenHands,repo_Prometheus"

.PARAMETER Replace
    Overwrite output files that already exist. By default existing files are skipped.

.EXAMPLE
    .\generate.ps1
    .\generate.ps1 -OutputDir ".\exports" -Layout radial
    .\generate.ps1 -Repos "repo_OpenHands,repo_Prometheus"
    .\generate.ps1 -Replace
#>
param(
    [string]   $OutputDir = ".\exports",
    [string]   $Layout    = "radial",
    [string]   $Repos     = "",
    [switch]   $Replace               # Overwrite existing .gexf files; skip them by default
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
$ok    = 0
$fail  = 0

$skipped = 0

foreach ($repo in $repoList) {
    Write-Host "`n── $repo ─────────────────────────────────"

    # Skip if file already exists and -Replace was not requested
    $exportFile = Join-Path $outDir "$repo.gexf"
    if ((Test-Path $exportFile) -and -not $Replace) {
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
    & $py (Join-Path $here "open_gephi.py") `
        --layout $Layout `
        --filter repo `
        --export-path $exportFile `
        --no-interaction

    if (Test-Path $exportFile) {
        Write-Host "  Saved: $exportFile" -ForegroundColor Green
        $ok++
    } else {
        Write-Warning "  Export file not found: $exportFile"
        $fail++
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host "`n══ Done: $ok exported, $skipped skipped, $fail failed ══"
