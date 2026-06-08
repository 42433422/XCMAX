param(
  [string]$OutputDir = "desktop\resources"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

# 位图、icon.png / icon.ico（及 macOS 上 icon.icns）统一由 Python 生成
$py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
& $py -m pip install "Pillow>=10.2.0" -q
& $py (Join-Path $PSScriptRoot "generate-desktop-resources.py")

Write-Host "Installer + icon assets generated (see $OutputDir)."
