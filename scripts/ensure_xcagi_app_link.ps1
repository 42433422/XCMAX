# Creates XCAGI\app as a directory junction -> ..\app (same volume).
# Safe with XCAGI/.gitignore rule `/app` so the link is never committed into the XCAGI git tree.
# Run from repo root:  powershell -ExecutionPolicy Bypass -File scripts/ensure_xcagi_app_link.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$xcagi = Join-Path $repoRoot "XCAGI"
$target = Join-Path $repoRoot "app"
$link = Join-Path $xcagi "app"

if (-not (Test-Path $target)) {
    Write-Error "Missing repo-root app package: $target"
}
if (-not (Test-Path $xcagi)) {
    Write-Error "Missing XCAGI directory: $xcagi"
}

if (Test-Path $link) {
    Remove-Item -LiteralPath $link -Force -Recurse
}

New-Item -ItemType Junction -Path $link -Target $target | Out-Null
Write-Host "OK: $link -> $target"
