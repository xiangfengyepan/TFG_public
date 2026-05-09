#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Add a solid background colour to one or more PNG files.

.PARAMETER Path
    Path to a single .png file or a folder containing *.png files.
    Default: .\exports

.PARAMETER OutputDir
    Folder where the results are saved.
    Default: same folder as each input file.

.PARAMETER Color
    Background colour name or hex string (#RRGGBB).  Default: Black

.PARAMETER Replace
    Overwrite the original files in place instead of writing new ones.
    By default a '_bg' suffix is added before the extension.

.PARAMETER Suffix
    Suffix appended before the .png extension on output files.
    Default: '_bg'  (ignored when -Replace is set)

.EXAMPLE
    .\add_background.ps1 .\exports\repo_OpenHands.png
    .\add_background.ps1 .\exports\
    .\add_background.ps1 .\exports\ -Color "#1a1a2e" -OutputDir .\exports_dark\
    .\add_background.ps1 .\exports\ -Replace
#>
param(
    [Parameter(Position = 0)]
    [string] $Path = ".\exports",

    [string] $OutputDir = "",
    [string] $Color     = "Black",
    [string] $Suffix    = "_bg",
    [switch] $Replace
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

# ── Resolve background colour ─────────────────────────────────────────────────

function Resolve-Color([string]$c) {
    if ($c -match '^#([0-9a-fA-F]{6})$') {
        $hex = $Matches[1]
        return [System.Drawing.Color]::FromArgb(
            [Convert]::ToInt32($hex.Substring(0,2),16),
            [Convert]::ToInt32($hex.Substring(2,2),16),
            [Convert]::ToInt32($hex.Substring(4,2),16)
        )
    }
    $known = [System.Drawing.Color]::FromName($c)
    if (-not $known.IsKnownColor) {
        Write-Error "Unknown colour '$c'. Use a .NET colour name or #RRGGBB."
        exit 1
    }
    return $known
}

$bgColor = Resolve-Color $Color

# ── Collect input files ───────────────────────────────────────────────────────

$resolved = Resolve-Path $Path -ErrorAction Stop

if (Test-Path $resolved -PathType Container) {
    $files = Get-ChildItem -Path $resolved -Filter "*.png" -File
} else {
    $files = @(Get-Item $resolved)
    if ($files[0].Extension -ne ".png") {
        Write-Error "Input file is not a .png: $resolved"
        exit 1
    }
}

if ($files.Count -eq 0) {
    Write-Warning "No PNG files found in: $resolved"
    exit 0
}

Write-Host "Processing $($files.Count) file(s) with background: $Color"

# ── Create output dir if specified ───────────────────────────────────────────

if ($OutputDir -ne "") {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $OutputDir = (Resolve-Path $OutputDir).Path
}

# ── Process each file ─────────────────────────────────────────────────────────

$ok   = 0
$fail = 0

foreach ($file in $files) {
    try {
        # Determine output path
        if ($Replace) {
            $outPath = $file.FullName
        } elseif ($OutputDir -ne "") {
            $outPath = Join-Path $OutputDir $file.Name
        } else {
            $base    = $file.BaseName
            $outPath = Join-Path $file.DirectoryName "$base$Suffix.png"
        }

        # Load source, composite onto solid background
        $src = [System.Drawing.Image]::FromFile($file.FullName)
        $bmp = New-Object System.Drawing.Bitmap($src.Width, $src.Height,
                   [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g   = [System.Drawing.Graphics]::FromImage($bmp)
        $g.Clear($bgColor)
        $g.DrawImage($src, 0, 0, $src.Width, $src.Height)
        $g.Dispose()
        $src.Dispose()

        # Save — use a temp file when overwriting in place to avoid read/write clash
        if ($Replace) {
            $tmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), ".png")
            $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
            $bmp.Dispose()
            Move-Item -Force $tmp $outPath
        } else {
            $bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
            $bmp.Dispose()
        }

        Write-Host "  OK  $($file.Name) -> $(Split-Path $outPath -Leaf)" -ForegroundColor Green
        $ok++
    } catch {
        Write-Warning "  FAIL $($file.Name): $_"
        $fail++
    }
}

Write-Host "`n══ Done: $ok processed, $fail failed ══"
