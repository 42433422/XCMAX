<#
.SYNOPSIS
  通过 SSH：在 Linux 服务器上安装 Docker（若尚未可用）→ 再执行与 remote-sre.ps1 deploy 相同的部署流程。

.DESCRIPTION
  1) 将 install_docker_engine.sh 上传到 /tmp 并在远端以 root 执行（需 root 或 sudo 免密）。
  2) 调用 remote-sre.ps1 -Action deploy（远端 git pull、备份、docker compose --profile app up -d --build、冒烟）。

  要求：服务器为常见 Linux，可访问 https://get.docker.com（内网/离线需自行预装 Docker 后只用 remote-sre deploy）。

.PARAMETER SshTarget
  例如 root@119.27.178.147；也可用环境变量 DEPLOY_SSH。

.PARAMETER RemoteRepo
  服务器上**仓库根目录**（内含 MODstore_deploy 或已进入 MODstore_deploy 的父路径，与 remote_sre_ops.sh 逻辑一致）。
  默认 $env:DEPLOY_REMOTE_REPO，未设置时为 /root/modstore-git。

.PARAMETER Branch
  默认 $env:DEPLOY_GIT_BRANCH，未设置时为 main。

.PARAMETER UseSudo
  登录用户非 root 时指定，远端执行 `sudo bash install_docker_engine.sh`（需免密 sudo）。

.EXAMPLE
  .\scripts\ssh-install-docker-and-deploy.ps1 -SshTarget root@1.2.3.4 -RemoteRepo /root/成都修茈科技有限公司
  .\scripts\ssh-install-docker-and-deploy.ps1 -SshTarget ubuntu@1.2.3.4 -RemoteRepo /home/ubuntu/XCai -UseSudo
#>
param(
  [string] $SshTarget = $env:DEPLOY_SSH,
  [string] $RemoteRepo = $env:DEPLOY_REMOTE_REPO,
  [string] $Branch = $env:DEPLOY_GIT_BRANCH,
  [switch] $UseSudo
)

$ErrorActionPreference = "Stop"

if (-not $SshTarget) {
  throw "需要 -SshTarget 或环境变量 DEPLOY_SSH（例如 root@你的公网IP）"
}
if (-not $RemoteRepo) {
  $RemoteRepo = "/root/modstore-git"
}
if (-not $Branch) {
  $Branch = "main"
}

$DeployRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$InstallSh = Join-Path $DeployRoot "scripts/install_docker_engine.sh"
if (-not (Test-Path $InstallSh)) {
  throw "Missing $InstallSh"
}

Write-Host "[ssh-docker-deploy] 1/2 install Docker on $SshTarget (skip if already ok)…"
$enc = [System.Text.UTF8Encoding]::new($false)
$tmp = Join-Path $env:TEMP "install_docker_engine_$(Get-Date -Format 'yyyyMMddHHmmss').sh"
$content = (Get-Content -Raw -Path $InstallSh) -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmp, $content, $enc)
try {
  & scp -o BatchMode=yes -q $tmp ($SshTarget + ":/tmp/install_docker_engine.sh")
  if ($LASTEXITCODE -ne 0) { throw "scp install_docker_engine.sh failed exit=$LASTEXITCODE" }
} finally {
  Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}

$sudo = if ($UseSudo) { "sudo " } else { "" }
$remoteInstall = "chmod +x /tmp/install_docker_engine.sh && ${sudo}bash /tmp/install_docker_engine.sh; ec=`$?; rm -f /tmp/install_docker_engine.sh; exit `$ec"
& ssh -o BatchMode=yes $SshTarget $remoteInstall
if ($LASTEXITCODE -ne 0) {
  throw "Remote Docker install failed exit=$LASTEXITCODE"
}

Write-Host "[ssh-docker-deploy] 2/2 remote-sre deploy (repo=$RemoteRepo branch=$Branch)…"
& (Join-Path $DeployRoot "scripts/remote-sre.ps1") -Action deploy -SshTarget $SshTarget -RemoteRepo $RemoteRepo -Branch $Branch
exit $LASTEXITCODE
