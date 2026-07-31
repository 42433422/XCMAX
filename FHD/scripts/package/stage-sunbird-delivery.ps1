param(
  [string]$Version = "1.0.0.1",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build-sunbird-installer.ps1") -Version $Version -SkipBuild:$SkipBuild
