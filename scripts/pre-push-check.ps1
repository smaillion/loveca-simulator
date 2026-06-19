param(
    [switch] $All
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Find-Python {
    if ($env:PYTHON) {
        $candidate = Get-Command $env:PYTHON -ErrorAction SilentlyContinue
        if ($candidate) {
            return @($candidate.Source)
        }
        if (Test-Path $env:PYTHON) {
            return @($env:PYTHON)
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @($pyLauncher.Source, "-3")
    }

    throw "Python was not found. Set PYTHON to the Python executable used for this repo."
}

function Git-Lines {
    param([string[]] $Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git @Arguments 2>$null
        if ($LASTEXITCODE -ne 0 -or $null -eq $output) {
            return @()
        }
        return @($output | Where-Object { $_ })
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Changed-Files {
    $files = New-Object System.Collections.Generic.HashSet[string]
    $upstream = (& git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $upstream) {
        foreach ($file in Git-Lines @("diff", "--name-only", "$upstream...HEAD")) {
            [void] $files.Add($file)
        }
    }
    foreach ($file in Git-Lines @("diff", "--name-only", "--cached")) {
        [void] $files.Add($file)
    }
    foreach ($file in Git-Lines @("diff", "--name-only")) {
        [void] $files.Add($file)
    }
    return @($files)
}

$manifestSensitivePatterns = @(
    "^data/loveca\.sqlite3$",
    "^data/loveca-db-manifest\.json$",
    "^data_sources/effect-registry\.v0\.json$",
    "^scripts/card-db-manifest\.py$",
    "^src/loveca/simulation/online\.py$",
    "^src/loveca/simulation/effects\.py$",
    "^src/loveca/db/bootstrap\.py$"
)

$changed = if ($All) { @("__all__") } else { Changed-Files }
$shouldVerifyManifest = $All
foreach ($file in $changed) {
    $normalized = $file -replace "\\", "/"
    foreach ($pattern in $manifestSensitivePatterns) {
        if ($normalized -match $pattern) {
            $shouldVerifyManifest = $true
            break
        }
    }
    if ($shouldVerifyManifest) {
        break
    }
}

if ($shouldVerifyManifest) {
    $python = @(Find-Python)
    $pythonExe = $python[0]
    $pythonArgs = if ($python.Count -gt 1) { $python[1..($python.Count - 1)] } else { @() }
    Write-Host "Verifying locked card database manifest..."
    & $pythonExe @pythonArgs scripts/card-db-manifest.py verify
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} else {
    Write-Host "Skipping card database manifest verify; no manifest-sensitive changes detected."
}

Write-Host "Pre-push checks passed."
