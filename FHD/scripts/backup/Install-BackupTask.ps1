# 注册 XCMAX 桌面端定时备份 Windows 计划任务
# =============================================================================
# 作用：安装时调用，注册两个计划任务：
#   1. XcagiDailyBackup  —— 每日 12:30 触发 XcagiBackup.ps1（业务低峰）
#   2. XcagiWeeklyBackup —— 每周日 12:30 触发 XcagiBackup.ps1（额外 weekly 副本）
#
# 幂等：重复执行不会重复注册（同名任务先删除再创建）。
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

# 构造 PowerShell 启动命令行
$pwshArgs = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$BackupScript`"")
if ($DataDir) { $pwshArgs += @("-DataDir", "`"$DataDir`"") }
if ($ExternalDir) { $pwshArgs += @("-ExternalDir", "`"$ExternalDir`"") }
$CmdLine = "powershell.exe " + ($pwshArgs -join " ")

# 检查 ScheduledTasks 模块
if (-not (Get-Module -ListAvailable -Name ScheduledTasks)) {
  Write-Error "ScheduledTasks module not available (requires Windows 8+ / Server 2012+)"
  exit 1
}

function Register-BackupTask([string]$TaskName, [datetime]$Trigger) {
  # 幂等：同名任务先删除
  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "removed existing task: $TaskName"
  }

  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $CmdLine
  $trigger = New-ScheduledTaskTrigger -Once -At $Trigger
  # 每日/每周重复
  if ($TaskName -eq $TaskNameDaily) {
    $trigger.Repetition = (New-ScheduledTaskTrigger -Daily -At $Trigger).Repetition
  } else {
    $trigger.Repetition = (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $Trigger).Repetition
  }

  # 以当前用户运行，不需要登录时也运行（InteractiveToken）
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

  Write-Host "registered task: $TaskName (trigger: $($trigger.StartBoundary))"
}

# 业务低峰 12:30
$triggerTime = Get-Date -Hour 12 -Minute 30 -Second 0 -Millisecond 0

Register-BackupTask -TaskName $TaskNameDaily -Trigger $triggerTime
Register-BackupTask -TaskName $TaskNameWeekly -Trigger $triggerTime

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
