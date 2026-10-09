# Removes XcagiDailyBackup and XcagiWeeklyBackup. Missing tasks are skipped.
# Uses Task Scheduler COM so uninstall works from 32-bit installer PowerShell.
[CmdletBinding()]
param()

$ErrorActionPreference = 'SilentlyContinue'
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$folder = $service.GetFolder("\")
foreach ($name in @("XcagiDailyBackup", "XcagiWeeklyBackup")) {
  try {
    $folder.DeleteTask($name, 0)
    Write-Host "removed task: $name"
  } catch {
    Write-Host "task not found (skip): $name"
  }
}
exit 0
