# 卸载 XCMAX 桌面端定时备份计划任务
# =============================================================================
# 作用：XCAGI 卸载时调用，删除 Install-BackupTask.ps1 注册的两个计划任务。
#       幂等：任务不存在时静默跳过。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File Uninstall-BackupTask.ps1
# =============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = 'SilentlyContinue'

$tasks = @("XcagiDailyBackup", "XcagiWeeklyBackup")
foreach ($name in $tasks) {
  $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($existing) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "removed task: $name"
  } else {
    Write-Host "task not found (skip): $name"
  }
}
exit 0
