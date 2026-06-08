param(
  [Parameter(Mandatory = $true)]
  [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$VersionFile = Join-Path $Root "release\VERSION"
New-Item -ItemType Directory -Force -Path (Split-Path $VersionFile) | Out-Null
Set-Content -Path $VersionFile -Value $Version -Encoding UTF8
Write-Host "Wrote version marker: $VersionFile"
