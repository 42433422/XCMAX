<#
.SYNOPSIS
  在服务器上 git pull + npm ci + build market（VITE_PUBLIC_BASE=/market/），产物即 Nginx 指向的 dist。

.PARAMETER GitPush
  先在本地仓库根执行 git push origin <Branch>（需已 commit）。

.EXAMPLE
  .\scripts\push-market-to-server.ps1
  .\scripts\push-market-to-server.ps1 -GitPush
#>
param(
    [switch] $GitPush,
    [string] $SshTarget = $env:DEPLOY_SSH,
    [string] $RemoteRepo = $env:DEPLOY_REMOTE_REPO,
    [string] $Branch = $env:DEPLOY_GIT_BRANCH
)

$ErrorActionPreference = "Stop"
if (-not $SshTarget) { $SshTarget = "root@119.27.178.147" }
if (-not $RemoteRepo) { $RemoteRepo = "/root/成都修茈科技有限公司" }
if (-not $Branch) { $Branch = "main" }

$ModstoreRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoRoot = Split-Path -Parent $ModstoreRoot

if ($GitPush) {
    Write-Host "[push-market] GitPush：git push origin $Branch …"
    Push-Location $RepoRoot
    try { git push "origin" $Branch }
    finally { Pop-Location }
}

Write-Host "[push-market] SSH $SshTarget → $RemoteRepo（分支 $Branch）"
$remote = $RemoteRepo.Replace("'", "'\''")
# clean + reset --hard：清未跟踪、对齐 origin，避免服务器上残留导致 merge/检出失败
$cmd = "set -euo pipefail; cd '$remote' && git rev-parse --git-dir >/dev/null && git fetch origin '$Branch' && (git clean -fd -- MODstore_deploy/market 2>/dev/null || true) && git reset --hard 'origin/$Branch' && cd MODstore_deploy/market && export VITE_PUBLIC_BASE=/market/ && rm -rf node_modules && npm install && npm run build && echo '[ok] dist:' && pwd"
ssh -o BatchMode=yes $SshTarget "$cmd"
