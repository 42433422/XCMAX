# Sync market dist to server (host path used by xiu-ci.com nginx)
param(
  [string]$SshHost = 'tencent-cvm',
  [string]$RemoteDist = '/root/modstore-git/MODstore_deploy/market/dist'
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Market = Join-Path $Root 'market'

Push-Location $Market
$env:VITE_XCAGI_DOWNLOAD_VERSION = '8.0.0'
$env:VITE_XCAGI_DOWNLOAD_BASE_URL = 'https://dl.xiu-ci.com/xcagi-v8.0.0'
npm run build
Pop-Location

$dist = Join-Path $Market 'dist'
if (-not (Test-Path (Join-Path $dist 'index.html'))) {
  throw "build failed: no dist/index.html"
}

Write-Host "Uploading dist to ${SshHost}:${RemoteDist} ..."
ssh $SshHost "mkdir -p $RemoteDist"
scp -r "$dist\*" "${SshHost}:${RemoteDist}/"
Write-Host "Done. Hard-refresh workbench download page (Ctrl+F5)."
