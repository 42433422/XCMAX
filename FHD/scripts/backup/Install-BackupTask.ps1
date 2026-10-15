# Registers XcagiDailyBackup at 12:30 and XcagiWeeklyBackup on Sunday at 13:30.
# Task Scheduler COM works from the 32-bit PowerShell that a 32-bit NSIS stub launches.
[CmdletBinding()]
param(
  [string]$ExternalDir = "",
  [string]$DataDir = ""
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path $MyInvocation.MyCommand.Path -Parent
$BackupScript = Join-Path $ScriptDir "XcagiBackup.ps1"
if (-not (Test-Path -LiteralPath $BackupScript)) {
  Write-Error "XcagiBackup.ps1 not found at: $BackupScript"
  exit 1
}

$powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$baseArgs = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$BackupScript`""
if ($DataDir) { $baseArgs += " -DataDir `"$DataDir`"" }
if ($ExternalDir) { $baseArgs += " -ExternalDir `"$ExternalDir`"" }

function Register-BackupTask {
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][ValidateSet("Daily", "Weekly")][string]$Cadence,
    [Parameter(Mandatory = $true)][datetime]$At
  )

  $service = New-Object -ComObject Schedule.Service
  $service.Connect()
  $folder = $service.GetFolder("\")
  try { $folder.DeleteTask($TaskName, 0) } catch { Write-Host "no previous task: $TaskName" }

  $task = $service.NewTask(0)
  $task.RegistrationInfo.Description = "XCAGI $Cadence backup"
  $task.Settings.Enabled = $true
  $task.Settings.AllowDemandStart = $true
  $task.Settings.StartWhenAvailable = $true
  $task.Settings.DisallowStartIfOnBatteries = $false
  $task.Settings.StopIfGoingOnBatteries = $false
  $task.Settings.ExecutionTimeLimit = "PT30M"
  $task.Settings.RestartCount = 2
  $task.Settings.RestartInterval = "PT5M"
  $action = $task.Actions.Create(0)
  $action.Path = $powershell
  $action.Arguments = $(if ($Cadence -eq "Weekly") { "$baseArgs -Weekly" } else { $baseArgs })
  $trigger = $task.Triggers.Create($(if ($Cadence -eq "Daily") { 2 } else { 3 }))
  $trigger.StartBoundary = $At.ToString("yyyy-MM-ddTHH:mm:ss")
  $trigger.Enabled = $true
  if ($Cadence -eq "Daily") {
    $trigger.DaysInterval = 1
  } else {
    $trigger.DaysOfWeek = 1
    $trigger.WeeksInterval = 1
  }
  $task.Principal.LogonType = 3
  $task.Principal.RunLevel = 0
  try {
    $folder.RegisterTaskDefinition($TaskName, $task, 6, $null, $null, 3) | Out-Null
  } catch {
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    Write-Host "retry register as ${user}: $($_.Exception.Message)"
    $folder.RegisterTaskDefinition($TaskName, $task, 6, $user, $null, 3) | Out-Null
  }
  Write-Host "registered task: $TaskName cadence=$Cadence at=$($At.ToString('HH:mm'))"
}

$at = Get-Date -Hour 12 -Minute 30 -Second 0 -Millisecond 0
Register-BackupTask -TaskName "XcagiDailyBackup" -Cadence Daily -At $at
Register-BackupTask -TaskName "XcagiWeeklyBackup" -Cadence Weekly -At $at.AddHours(1)
Write-Host "=== XCMAX backup tasks installed ==="
if ($ExternalDir) { Write-Host "External backup dir: $ExternalDir" }
exit 0
