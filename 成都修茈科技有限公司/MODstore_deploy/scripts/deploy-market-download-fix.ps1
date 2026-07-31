# Sync market dist to server (host path used by xiu-ci.com nginx)
# 注意：此脚本仅作历史兼容；正式构建路径走 docker-compose.yml build args
# （VITE_XCAGI_DOWNLOAD_VERSION / VITE_XCAGI_DOWNLOAD_BASE_URL 默认值已对齐 1.0.0.1）
param(
  [string]$SshHost = 'tencent-cvm',
  [string]$RemoteDist = '/root/modstore-git/MODstore_deploy/market/dist'
)

$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Market = Join-Path $Root 'market'

Push-Location $Market
$env:VITE_XCAGI_DOWNLOAD_VERSION = '1.0.0.1'
$env:VITE_XCAGI_DOWNLOAD_BASE_URL = 'https://xiu-ci.com/xcagi-v1.0.0.1'
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
