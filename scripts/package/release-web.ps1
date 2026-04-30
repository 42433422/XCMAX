param(
  [string]$Version = "7.0.0",
  [string]$Registry = "ghcr.io/42433422/xcagi"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

docker build -t "$Registry/backend:$Version" -t "$Registry/backend:latest" -f "XCAGI\Dockerfile" "XCAGI"
docker build -t "$Registry/frontend:$Version" -t "$Registry/frontend:latest" -f "frontend\Dockerfile" "frontend"

Write-Host "Web images built:"
Write-Host "  $Registry/backend:$Version"
Write-Host "  $Registry/frontend:$Version"
