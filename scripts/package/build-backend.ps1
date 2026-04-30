param(
  [string]$Version = "7.0.0",
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Version = $Version.TrimStart("v", "V")

if (-not $SkipFrontend) {
  Push-Location (Join-Path $Root "frontend")
  if (-not (Test-Path "node_modules")) {
    npm install
  }
  npm run build
  Pop-Location
}

python -m pip install --upgrade pip
$RuntimeRequirements = Join-Path $env:TEMP "xcagi-runtime-requirements.txt"
Get-Content "XCAGI\requirements.txt" |
  Where-Object { $_ -notmatch '^\s*pytest($|[-=<>])' } |
  Set-Content -Path $RuntimeRequirements -Encoding UTF8
python -m pip install -r $RuntimeRequirements
python -m pip install "pyinstaller>=6.0" appdirs

$env:XCAGI_VERSION = $Version
& "$PSScriptRoot\write-version.ps1" -Version $Version
python -m PyInstaller --noconfirm --clean "scripts\package\xcagi_backend.spec"

Write-Host "Backend build complete: dist\xcagi-backend"
