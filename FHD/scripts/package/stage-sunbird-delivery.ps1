param(
  [string]$Version = "",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build-sunbird-installer.ps1") -Version $Version -SkipBuild:$SkipBuild
