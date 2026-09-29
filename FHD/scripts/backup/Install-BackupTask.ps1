# 注册 XCMAX 桌面端定时备份 Windows 计划任务
# =============================================================================
# 作用：安装时调用，注册两个计划任务：
#   1. XcagiDailyBackup  —— 每日 12:30 触发 XcagiBackup.ps1（业务低峰）
#   2. XcagiWeeklyBackup —— 每周日 12:30 触发 XcagiBackup.ps1（额外 weekly 副本）
#
# 幂等：重复执行不会重复注册（同名任务先删除再创建）。
# 运行身份：当前交互用户，Limited。触发：每天 12:30，以及每周日 12:30。
#
# 用法（NSIS 安装时 / 运维手动执行）：
#   powershell -ExecutionPolicy Bypass -File Install-BackupTask.ps1
#   powershell -ExecutionPolicy Bypass -File Install-BackupTask.ps1 -ExternalDir "E:\XCAGI-Backup"
# =============================================================================
[CmdletBinding()]
param(
  [string]$ExternalDir = "",
  [string]$DataDir = ""
)

$ErrorActionPreference = 'Stop'

$TaskNameDaily = "XcagiDailyBackup"
$TaskNameWeekly = "XcagiWeeklyBackup"
$ScriptDir = Split-Path $MyInvocation.MyCommand.Path -Parent
$BackupScript = Join-Path $ScriptDir "XcagiBackup.ps1"

if (-not (Test-Path $BackupScript)) {
  Write-Error "XcagiBackup.ps1 not found at: $BackupScript"
  exit 1
}

if (-not (Get-Module -ListAvailable -Name ScheduledTasks)) {
  Write-Error "ScheduledTasks module not available (requires Windows 8+ / Server 2012+)"
  exit 1
}

$pwshArgs = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$BackupScript`"")
if ($DataDir) { $pwshArgs += @("-DataDir", "`"$DataDir`"") }
if ($ExternalDir) { $pwshArgs += @("-ExternalDir", "`"$ExternalDir`"") }
# Execute is already powershell.exe. Argument must not start with another powershell.exe.
$ArgumentLine = $pwshArgs -join " "

function Register-BackupTask {
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][ValidateSet("Daily", "Weekly")][string]$Cadence,
    [Parameter(Mandatory = $true)][datetime]$At
  )

  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "removed existing task: $TaskName"
  }

  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ArgumentLine
  if ($Cadence -eq "Daily") {
    $taskTrigger = New-ScheduledTaskTrigger -Daily -At $At
  } else {
    $taskTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $At
  }

  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $taskTrigger `
    -Principal $principal -Settings $settings -Force | Out-Null

  Write-Host "registered task: $TaskName cadence=$Cadence at=$($At.ToString('HH:mm'))"
}

$at = Get-Date -Hour 12 -Minute 30 -Second 0 -Millisecond 0
Register-BackupTask -TaskName $TaskNameDaily -Cadence Daily -At $at
Register-BackupTask -TaskName $TaskNameWeekly -Cadence Weekly -At $at

Write-Host ""
Write-Host "=== XCMAX backup tasks installed ==="
Write-Host "  Daily  : $TaskNameDaily  @ 12:30 every day"
Write-Host "  Weekly : $TaskNameWeekly @ 12:30 every Sunday"
if ($ExternalDir) {
  Write-Host "  External backup dir: $ExternalDir"
}
Write-Host "  Log: %APPDATA%\XCAGI\logs\backup.log"
Write-Host ""
Write-Host "Manual trigger test:"
Write-Host "  Start-ScheduledTask -TaskName $TaskNameDaily"
