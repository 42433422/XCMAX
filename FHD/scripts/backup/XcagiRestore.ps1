# 停止应用后，用随包后端只读校验备份，再确认恢复；保留 pre-restore 副本。
# 可传 -DataDir 和 -BackupFile；不依赖客户安装 Python 或 sqlite3。
[CmdletBinding()]
param(
  [string]$DataDir = "",
  [string]$BackupFile = ""
)

$ErrorActionPreference = 'Stop'

$AppData = $env:APPDATA
if (-not $AppData) { $AppData = $env:LOCALAPPDATA }
if (-not $AppData) { $AppData = Join-Path $env:USERPROFILE "AppData\Roaming" }

$EffectiveDataDir = if ($DataDir) { $DataDir } else { Join-Path $AppData "XCAGI" }
$BackupsDir = Join-Path $EffectiveDataDir "backups"
$DbFile = Join-Path $EffectiveDataDir "data\xcagi.db"

$BackendDir = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$BackendExe = Join-Path $BackendDir 'xcagi-backend.exe'
if (-not (Test-Path -LiteralPath $BackendExe -PathType Leaf)) {
  throw "packaged backend not found: $BackendExe"
}

function Test-BackupIntegrity([string]$path) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
  try {
    $proc = Start-Process -FilePath $BackendExe -ArgumentList @('--verify-backup', ('"{0}"' -f $path)) `
      -NoNewWindow -Wait -PassThru -ErrorAction Stop
    return $proc.ExitCode -eq 0
  } catch { return $false }
}

$candidates = @(
  Get-ChildItem -LiteralPath $BackupsDir -Filter "xcagi-*.db" -File -ErrorAction SilentlyContinue
  Get-ChildItem -LiteralPath (Join-Path $EffectiveDataDir "data\database_backups") -Filter "*.bak" -File -ErrorAction SilentlyContinue
) |
  Where-Object { Test-BackupIntegrity $_.FullName } |
  Sort-Object LastWriteTime -Descending

if (-not $candidates) {
  Write-Error "no valid backup found in $BackupsDir"
  exit 1
}

$selected = $null
if ($BackupFile) {
  $selected = $candidates | Where-Object { $_.Name -eq $BackupFile } | Select-Object -First 1
  if (-not $selected) {
    Write-Error "specified backup not found or invalid: $BackupFile"
    exit 1
  }
} else {
  Write-Host ""
  Write-Host "Available backups (newest first):"
  Write-Host "-----------------------------------"
  for ($i = 0; $i -lt $candidates.Count; $i++) {
    $c = $candidates[$i]
    $isWeekly = if ($c.Name -match '-weekly-') { " [WEEKLY]" } else { "" }
    Write-Host ("  [{0}] {1}  {2} ({3:N0} bytes){4}" -f $i, $c.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'), $c.Name, $c.Length, $isWeekly)
  }
  Write-Host ""
  $choice = Read-Host "Select backup index to restore [0]"
  if (-not $choice) { $choice = "0" }
  $idx = 0
  if (-not ([int]::TryParse($choice, [ref]$idx)) -or $idx -lt 0 -or $idx -ge $candidates.Count) {
    Write-Error "invalid index: $choice"
    exit 1
  }
  $selected = $candidates[$idx]
}

Write-Host "Selected: $($selected.Name), $($selected.LastWriteTime), $($selected.Length) bytes"

$confirm = Read-Host "Restore this backup to $DbFile? This will overwrite current database. [y/N]"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
  Write-Host "aborted."
  exit 0
}

if (-not (Test-BackupIntegrity $selected.FullName)) {
  throw "selected backup no longer passes integrity_check"
}
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
if (Test-Path $DbFile) {
  $snapshot = "$DbFile.pre-restore-$stamp"
  Copy-Item $DbFile $snapshot -Force
  Write-Host "pre-restore snapshot created: $snapshot"

  $walFile = "$DbFile-wal"
  $shmFile = "$DbFile-shm"
  if (Test-Path $walFile) { Remove-Item $walFile -Force; Write-Host "removed stale WAL: $walFile" }
  if (Test-Path $shmFile) { Remove-Item $shmFile -Force; Write-Host "removed stale SHM: $shmFile" }
}

try {
  Copy-Item $selected.FullName $DbFile -Force
  Write-Host "Restore complete: $($selected.Name) -> $DbFile"
  Write-Host "Please restart XCAGI application."
  Write-Host "If startup fails, the corrupt db was saved as: $DbFile.pre-restore-$stamp"
} catch {
  Write-Error "restore failed: $_"
  Write-Host "Your original database snapshot is at: $DbFile.pre-restore-$stamp"
  exit 1
}
exit 0
