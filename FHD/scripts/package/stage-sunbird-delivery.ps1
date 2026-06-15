param(
  [string]$Version = "10.0.0",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build-sunbird-installer.ps1") -Version $Version -SkipBuild:$SkipBuild
