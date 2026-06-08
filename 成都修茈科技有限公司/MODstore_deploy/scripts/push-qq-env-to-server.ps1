<#
.SYNOPSIS
  将本机 MODstore_deploy/.env.local 中 QQ 一等公民相关 4 个键合并到服务器 .env，并重启 modstore。
  不覆盖服务器 .env 其余内容；先备份 .env，再剔除旧同名键后追加新值。

.PARAMETER SshTarget
.PARAMETER RemoteBase
.PARAMETER EnvLocalPath
  默认：MODstore_deploy/.env.local
#>
param(
  [string] $SshTarget = $env:DEPLOY_SSH,
  [string] $RemoteBase = $env:DEPLOY_REMOTE_BASE,
  [string] $EnvLocalPath = ""
)

$ErrorActionPreference = "Stop"
if (-not $SshTarget) { $SshTarget = "root@119.27.178.147" }
if (-not $RemoteBase) {
  $RemoteBase = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String("L3Jvb3QvbW9kc3RvcmUtZ2l0"))
}

$ModstoreDeploy = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $EnvLocalPath) { $EnvLocalPath = Join-Path $ModstoreDeploy ".env.local" }
if (-not (Test-Path $EnvLocalPath)) {
  throw "找不到 $EnvLocalPath ，请指定 -EnvLocalPath"
}

$keys = @(
  "TASK_ROUTER_QQ_APP_SECRET",
  "TASK_ROUTER_QQ_BOT_TOKEN",
  "EMPLOYEE_INTERVIEW_QQ_APP_SECRET",
  "EMPLOYEE_INTERVIEW_QQ_BOT_TOKEN"
)
$pat = "^(" + ($keys -join "|") + ")="
$lines = Get-Content -LiteralPath $EnvLocalPath -Encoding UTF8 |
  Where-Object { $_ -match $pat }
if ($lines.Count -lt 1) {
  throw "在 $EnvLocalPath 中未找到任何 QQ 一等公民变量行（$pat）"
}

$patch = Join-Path $env:TEMP "modstore_qq_env.patch"
$patchBody = "# merged keys (no comments from .env.local)`n" + (($lines | ForEach-Object { $_ -replace "`r$", '' }) -join "`n") + "`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($patch, $patchBody.Replace("`r`n", "`n"), $utf8NoBom)

Write-Host "[push-qq-env] scp fragment -> ${SshTarget}:/tmp/modstore_qq_env.patch"
scp -q $patch "${SshTarget}:/tmp/modstore_qq_env.patch"

$mergeSh = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "remote-merge-qq-env.sh"
if (-not (Test-Path $mergeSh)) { throw "找不到 $mergeSh" }
$mergeTmp = Join-Path $env:TEMP "remote-merge-qq-env.sh"
$mt = ([System.IO.File]::ReadAllText($mergeSh)) -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($mergeTmp, $mt.TrimEnd() + "`n", $utf8NoBom)

Write-Host "[push-qq-env] scp merge script -> ${SshTarget}:/tmp/remote-merge-qq-env.sh"
scp -q $mergeTmp "${SshTarget}:/tmp/remote-merge-qq-env.sh"

Write-Host "[push-qq-env] merge on server + systemctl restart modstore"
ssh -q $SshTarget "bash /tmp/remote-merge-qq-env.sh '$RemoteBase'"

Remove-Item -Force $patch, $mergeTmp -ErrorAction SilentlyContinue
Write-Host "[push-qq-env] done."
