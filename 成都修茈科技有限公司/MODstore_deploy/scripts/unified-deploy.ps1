<#
.SYNOPSIS
  MODstore 统一部署入口（本机 Windows PowerShell）：封装既有脚本，避免记多条命令路径。

.DESCRIPTION
  - FullSync   调用 sync-modstore-to-server.ps1：将本机 MODstore_deploy（含未提交修改）打成 tar → scp → 远端解压 → pip / npm build / mvn → systemctl 重启 modstore + modstore-payment，并做健康检查。
  - RemoteGit  调用 remote-sre.ps1 -Action deploy：远端 git fetch/reset、备份、docker compose --profile app、冒烟（见 docs/runbooks/remote-server-operations.md）。
  - 其余动作   直接透传 remote-sre.ps1（preflight / smoke / backup / rollback 等）。

  可在 MODstore_deploy 根目录放置 deploy-target.local.ps1（已 gitignore）预置 $env:DEPLOY_SSH、DEPLOY_REMOTE_REPO 等，与本仓库 remote-sre.ps1 行为一致。

.PARAMETER Mode
  FullSync | RemoteGit | Preflight | Smoke | Backup | Rollback | Loadtest | ChaosDryRun | Help

.PARAMETER SshTarget
  例：root@119.27.178.147。未传时读环境变量 DEPLOY_SSH（用户/进程/ deploy-target.local.ps1）。

.PARAMETER RemoteBase
  仅 FullSync：远端仓库根（MODstore_deploy 的父目录），默认 /root/modstore-git；也可设 DEPLOY_REMOTE_BASE。

.PARAMETER AlignSystemd
  仅 FullSync：同步完成后上传并执行 align_modstore_systemd_to_deploy.sh，对齐 systemd 工作目录。

.PARAMETER RemoteRepo
  非 FullSync：远端 git 顶层路径，默认 /root/modstore-git。

.PARAMETER Branch
  RemoteGit：分支名，默认 main。

.PARAMETER RollbackRef
  Rollback：传给 remote-sre 的 Git ref（如 HEAD~1）。

.EXAMPLE
  cd MODstore_deploy
  .\scripts\unified-deploy.ps1 -Mode FullSync -SshTarget root@119.27.178.147

.EXAMPLE
  .\scripts\unified-deploy.ps1 -Mode RemoteGit -SshTarget root@119.27.178.147 -RemoteRepo /root/modstore-git -Branch main

.EXAMPLE
  .\scripts\unified-deploy.ps1 -Mode Preflight -SshTarget root@119.27.178.147

.EXAMPLE
  .\scripts\unified-deploy.ps1 -Mode Help
#>
param(
  [ValidateSet('FullSync', 'RemoteGit', 'Preflight', 'Smoke', 'Backup', 'Rollback', 'Loadtest', 'ChaosDryRun', 'Help')]
  [string] $Mode = 'Help',

  [string] $SshTarget = $env:DEPLOY_SSH,
  [string] $RemoteBase = $env:DEPLOY_REMOTE_BASE,
  [switch] $AlignSystemd,

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

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DeployRoot = Split-Path -Parent $ScriptDir
$LocalTarget = Join-Path $DeployRoot 'deploy-target.local.ps1'
if (Test-Path $LocalTarget) {
  . $LocalTarget
  if (-not $SshTarget -and $env:DEPLOY_SSH) { $SshTarget = $env:DEPLOY_SSH }
  if (-not $RemoteRepo -and $env:DEPLOY_REMOTE_REPO) { $RemoteRepo = $env:DEPLOY_REMOTE_REPO }
  if (-not $Branch -and $env:DEPLOY_GIT_BRANCH) { $Branch = $env:DEPLOY_GIT_BRANCH }
  if (-not $RemoteBase -and $env:DEPLOY_REMOTE_BASE) { $RemoteBase = $env:DEPLOY_REMOTE_BASE }
}

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
if (-not $RemoteBase) {
  $RemoteBase = [Environment]::GetEnvironmentVariable('DEPLOY_REMOTE_BASE', 'User')
}
if (-not $RemoteBase) {
  $RemoteBase = [Environment]::GetEnvironmentVariable('DEPLOY_REMOTE_BASE', 'Machine')
}

function Show-UnifiedDeployHelp {
  $lines = @(
    'MODstore unified-deploy.ps1 (single entry for MODstore releases)'
    ''
    'Usage:'
    '  .\scripts\unified-deploy.ps1 -Mode <Mode> [parameters]'
    ''
    'Modes:'
    '  FullSync    Tar sync from this PC -> remote extract -> pip / npm build / mvn -> systemctl (same as sync-modstore-to-server.ps1)'
    '  RemoteGit   Remote git reset + docker compose + smoke (same as remote-sre.ps1 -Action deploy)'
    '  Preflight   Remote preflight checks'
    '  Smoke       Remote smoke tests (includes scheduler checks)'
    '  Backup      Remote backup'
    '  Rollback    Remote rollback (requires -RollbackRef)'
    '  Loadtest    Remote k6 loadtest profile'
    '  ChaosDryRun Print chaos drill commands'
    ''
    'Examples:'
    '  .\scripts\unified-deploy.ps1 -Mode FullSync -SshTarget root@YOUR_HOST'
    '  .\scripts\unified-deploy.ps1 -Mode FullSync -SshTarget root@YOUR_HOST -AlignSystemd'
    '  .\scripts\unified-deploy.ps1 -Mode RemoteGit -SshTarget root@YOUR_HOST -RemoteRepo /root/modstore-git -Branch main'
    ''
    'Environment variables (optional):'
    '  DEPLOY_SSH              e.g. root@119.27.178.147'
    '  DEPLOY_REMOTE_BASE      FullSync parent dir on server (default /root/modstore-git)'
    '  DEPLOY_REMOTE_REPO      Git root for RemoteGit etc. (default /root/modstore-git)'
    '  DEPLOY_GIT_BRANCH       default main'
    '  MODSTORE_ROLLBACK_REF   required for Rollback mode'
    ''
    'Manual: docs/runbooks/remote-server-operations.md'
  )
  Write-Host ($lines -join [Environment]::NewLine)
}

if ($Mode -eq 'Help') {
  Show-UnifiedDeployHelp
  exit 0
}

if (-not $SshTarget) {
  throw 'SshTarget is required: pass -SshTarget root@host, set env DEPLOY_SSH, or use deploy-target.local.ps1.'
}

$SyncScript = Join-Path $ScriptDir 'sync-modstore-to-server.ps1'
$SreScript = Join-Path $ScriptDir 'remote-sre.ps1'

if (-not (Test-Path $SyncScript)) { throw "Missing: $SyncScript" }
if (-not (Test-Path $SreScript)) { throw "Missing: $SreScript" }

switch ($Mode) {
  'FullSync' {
    Write-Host "[unified-deploy] Mode=FullSync -> sync-modstore-to-server.ps1"
    $argsSync = @{ SshTarget = $SshTarget }
    if ($RemoteBase) { $argsSync['RemoteBase'] = $RemoteBase }
    if ($AlignSystemd) { $argsSync['AlignSystemd'] = $true }
    & $SyncScript @argsSync
    exit $LASTEXITCODE
  }

  'RemoteGit' {
    Write-Host "[unified-deploy] Mode=RemoteGit -> remote-sre.ps1 -Action deploy"
    if (-not $RemoteRepo) { $RemoteRepo = '/root/modstore-git' }
    if (-not $Branch) { $Branch = 'main' }
    & $SreScript -Action deploy -SshTarget $SshTarget -RemoteRepo $RemoteRepo -Branch $Branch `
      -ApiUrl $ApiUrl -MarketUrl $MarketUrl -PaymentUrl $PaymentUrl -PrometheusUrl $PrometheusUrl `
      -ChaosScenario $ChaosScenario -K6Stage $K6Stage
    exit $LASTEXITCODE
  }

  'Rollback' {
    if (-not $RollbackRef) {
      throw 'Rollback requires -RollbackRef or env MODSTORE_ROLLBACK_REF.'
    }
    Write-Host "[unified-deploy] Mode=Rollback -> remote-sre.ps1 -Action rollback"
    if (-not $RemoteRepo) { $RemoteRepo = '/root/modstore-git' }
    & $SreScript -Action rollback -SshTarget $SshTarget -RemoteRepo $RemoteRepo -Branch $Branch `
      -RollbackRef $RollbackRef -ApiUrl $ApiUrl -MarketUrl $MarketUrl -PaymentUrl $PaymentUrl -PrometheusUrl $PrometheusUrl `
      -ChaosScenario $ChaosScenario -K6Stage $K6Stage
    exit $LASTEXITCODE
  }

  default {
    $sreAction = switch ($Mode) {
      'Preflight' { 'preflight' }
      'Smoke' { 'smoke' }
      'Backup' { 'backup' }
      'Loadtest' { 'loadtest' }
      'ChaosDryRun' { 'chaos-dry-run' }
    }
    Write-Host "[unified-deploy] Mode=$Mode -> remote-sre.ps1 -Action $sreAction"
    if (-not $RemoteRepo) { $RemoteRepo = '/root/modstore-git' }
    if (-not $Branch) { $Branch = 'main' }
    & $SreScript -Action $sreAction -SshTarget $SshTarget -RemoteRepo $RemoteRepo -Branch $Branch `
      -ApiUrl $ApiUrl -MarketUrl $MarketUrl -PaymentUrl $PaymentUrl -PrometheusUrl $PrometheusUrl `
      -ChaosScenario $ChaosScenario -K6Stage $K6Stage
    exit $LASTEXITCODE
  }
}
