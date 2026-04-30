param(
  [string]$Version = "7.0.0",
  [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Version = $Version.TrimStart("v", "V")

if (-not $SkipBackend) {
  & "$PSScriptRoot\build-backend.ps1" -Version $Version
} else {
  python -m pip install "Pillow>=10.2.0" -q
}

& "$PSScriptRoot\create-installer-assets.ps1"

Push-Location (Join-Path $Root "desktop")
if (-not (Test-Path "node_modules")) {
  npm install
}
npm version $Version --no-git-tag-version
npm run dist:win
$outDir = Join-Path $Root "release\desktop-designed-final2"
$artifact = Get-ChildItem $outDir -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if ($artifact) {
  node (Join-Path $Root "scripts\package\generate-update-metadata.mjs") $artifact.FullName $Version win
}
Pop-Location

Write-Host "Windows installer build complete: release\desktop-designed-final2"
