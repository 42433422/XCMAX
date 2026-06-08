<#
.SYNOPSIS
  从本机触发远程 MODstore 单机 SRE 运维动作。
  统一部署入口见 **unified-deploy.ps1**（-Mode RemoteGit / Preflight / Smoke 等，底层调用本脚本）。

.EXAMPLE
  .\scripts\remote-sre.ps1 -Action preflight -SshTarget root@your-server -RemoteRepo /root/modstore-git
  .\scripts\remote-sre.ps1 -Action deploy -SshTarget root@your-server -RemoteRepo /root/modstore-git -Branch main
  .\scripts\remote-sre.ps1 -Action rollback -RollbackRef HEAD~1
#>
param(
  [ValidateSet("preflight", "smoke", "backup", "deploy", "loadtest", "chaos-dry-run", "rollback")]
  [string] $Action = "preflight",
  [string] $SshTarget = $env:DEPLOY_SSH,
  [string] $RemoteRepo = $env:DEPLOY_REMOTE_REPO,
  [string] $Branch = $env:DEPLOY_GIT_BRANCH,
  [string] $RollbackRef = $env:MODSTORE_ROLLBACK_REF,
  [string] $ApiUrl = $env:MODSTORE_API_URL,
  [string] $MarketUrl = $env:MODSTORE_MARKET_URL,
  [string] $PaymentUrl = $env:MODSTORE_PAYMENT_URL,
  [string] $PrometheusUrl = $env:MODSTORE_PROMETHEUS_URL,
  [string] $ChaosScenario = $env:MODSTORE_CHAOS_SCENARIO,
  [string] $K6Stage = $env:K6_STAGE
)

$ErrorActionPreference = "Stop"

# 可选：在 MODstore_deploy 根目录放 deploy-target.local.ps1，仅本机使用（已 gitignore），用于设置 $env:DEPLOY_* 
$_scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$_deployRoot = Split-Path -Parent $_scriptDir
$_localTarget = Join-Path $_deployRoot "deploy-target.local.ps1"
if (Test-Path $_localTarget) {
  . $_localTarget
  if (-not $SshTarget -and $env:DEPLOY_SSH) { $SshTarget = $env:DEPLOY_SSH }
  if (-not $RemoteRepo -and $env:DEPLOY_REMOTE_REPO) { $RemoteRepo = $env:DEPLOY_REMOTE_REPO }
  if (-not $Branch -and $env:DEPLOY_GIT_BRANCH) { $Branch = $env:DEPLOY_GIT_BRANCH }
}

# 进程级未设置时，读取 Windows「用户/系统」环境变量（图形界面里配置的 DEPLOY_SSH 在此）
if (-not $SshTarget) {
  $SshTarget = [Environment]::GetEnvironmentVariable('DEPLOY_SSH', 'User')
}
if (-not $SshTarget) {
  $SshTarget = [Environment]::GetEnvironmentVariable('DEPLOY_SSH', 'Machine')
}
if (-not $RemoteRepo) {
  $RemoteRepo = [Environment]::GetEnvironmentVariable('DEPLOY_REMOTE_REPO', 'User')
}
if (-not $RemoteRepo) {
  $RemoteRepo = [Environment]::GetEnvironmentVariable('DEPLOY_REMOTE_REPO', 'Machine')
}
if (-not $Branch) {
  $Branch = [Environment]::GetEnvironmentVariable('DEPLOY_GIT_BRANCH', 'User')
}
if (-not $Branch) {
  $Branch = [Environment]::GetEnvironmentVariable('DEPLOY_GIT_BRANCH', 'Machine')
}

if (-not $SshTarget) { throw "SshTarget is required. Set user env DEPLOY_SSH or pass -SshTarget root@your-server" }
if (-not $RemoteRepo) { $RemoteRepo = "/root/modstore-git" }
if (-not $Branch) { $Branch = "main" }
if (-not $ApiUrl) { $ApiUrl = "http://127.0.0.1:8765" }
if (-not $MarketUrl) { $MarketUrl = "http://127.0.0.1:4173" }
if (-not $PaymentUrl) { $PaymentUrl = "http://127.0.0.1:8080" }
if (-not $PrometheusUrl) { $PrometheusUrl = "http://127.0.0.1:9090" }
if (-not $ChaosScenario) { $ChaosScenario = "payment-restart" }
if (-not $K6Stage) { $K6Stage = "smoke" }

$DeployRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ScriptPath = Join-Path $DeployRoot "scripts/remote_sre_ops.sh"
if (-not (Test-Path $ScriptPath)) { throw "Missing $ScriptPath" }

$tmp = Join-Path $env:TEMP "remote_sre_ops_$(Get-Date -Format 'yyyyMMddHHmmss').sh"
$enc = [System.Text.UTF8Encoding]::new($false)
$content = (Get-Content -Raw -Path $ScriptPath) -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmp, $content, $enc)

try {
  Write-Host "[remote-sre] upload helper to $SshTarget"
  & scp -o BatchMode=yes -q $tmp ($SshTarget + ":/tmp/remote_sre_ops.sh")
  if ($LASTEXITCODE -ne 0) { throw "scp failed exit=$LASTEXITCODE" }
} finally {
  Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}

function Escape-SingleQuoted([string] $Value) {
  return $Value.Replace("'", "'\''")
}

$envParts = @(
  "MODSTORE_REMOTE_REPO='$(Escape-SingleQuoted $RemoteRepo)'",
  "MODSTORE_REMOTE_BRANCH='$(Escape-SingleQuoted $Branch)'",
  "MODSTORE_API_URL='$(Escape-SingleQuoted $ApiUrl)'",
  "MODSTORE_MARKET_URL='$(Escape-SingleQuoted $MarketUrl)'",
  "MODSTORE_PAYMENT_URL='$(Escape-SingleQuoted $PaymentUrl)'",
  "MODSTORE_PROMETHEUS_URL='$(Escape-SingleQuoted $PrometheusUrl)'",
  "MODSTORE_CHAOS_SCENARIO='$(Escape-SingleQuoted $ChaosScenario)'",
  "K6_STAGE='$(Escape-SingleQuoted $K6Stage)'"
)

if ($Action -eq "rollback") {
  if (-not $RollbackRef) { throw "RollbackRef is required for rollback." }
  $envParts += "MODSTORE_ROLLBACK_REF='$(Escape-SingleQuoted $RollbackRef)'"
}

$remoteCmd = "chmod +x /tmp/remote_sre_ops.sh; " + ($envParts -join " ") + " bash /tmp/remote_sre_ops.sh '$Action'; ec=`$?; rm -f /tmp/remote_sre_ops.sh; exit `$ec"
Write-Host "[remote-sre] action=$Action repo=$RemoteRepo branch=$Branch"
& ssh -o BatchMode=yes $SshTarget $remoteCmd
exit $LASTEXITCODE
