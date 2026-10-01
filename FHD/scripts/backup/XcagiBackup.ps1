# Windows 计划任务入口：调用打包后端的 SQLite 在线备份及 integrity_check。
# -DataDir 指定数据目录；-ExternalDir 同时写入外部位置。
# 日志：%APPDATA%/XCAGI/logs/backup.log；保留策略由后端统一执行。
[CmdletBinding()]
param(
  [string]$DataDir = "",
  [string]$ExternalDir = ""
)

$ErrorActionPreference = 'Stop'

# --- 路径与日志 ---
$AppData = $env:APPDATA
if (-not $AppData) { $AppData = $env:LOCALAPPDATA }
if (-not $AppData) { $AppData = Join-Path $env:USERPROFILE "AppData\Roaming" }

$LogDir = Join-Path $AppData "XCAGI\logs"
$LogFile = Join-Path $LogDir "backup.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$msg) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $line = "[$ts] $msg"
  Add-Content -Path $LogFile -Value $line -Encoding UTF8
  Write-Host $line
}

# --- 定位 xcagi-backend.exe ---
function Find-BackendExe {
  # Resolve the executable shipped beside this script, including custom NSIS /D paths.
  $packagedBackendDir = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
  $packagedBackendExe = Join-Path $packagedBackendDir 'xcagi-backend.exe'
  if (Test-Path $packagedBackendExe) { return $packagedBackendExe }
  # Missing packaged backend is an error; never run a different installed instance.
  return $null
}

# --- 清理老旧备份（与 backup_scheduler.py 策略一致）---
function Cleanup-OldBackups([string]$BackupsDir) {
  if (-not (Test-Path $BackupsDir)) { return }
  $now = Get-Date
  $dailyCutoff = $now.AddDays(-7)
  $weeklyCutoff = $now.AddDays(-28)

  Get-ChildItem -Path $BackupsDir -Filter "xcagi-*.db" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $isWeekly = $_.Name -match '-weekly-'
    $cutoff = if ($isWeekly) { $weeklyCutoff } else { $dailyCutoff }
    if ($_.LastWriteTime -lt $cutoff) {
      try {
        Remove-Item $_.FullName -Force
        Write-Log "cleaned up $(if ($isWeekly) {'weekly'} else {'daily'}) backup: $($_.Name)"
      } catch {
        Write-Log "WARN: failed to clean up $($_.Name): $_"
      }
    }
  }
}

# --- 同步到外部目录（USB 盘）---
function Sync-ToExternal([string]$BackupFile) {
  if (-not $ExternalDir) { return }
  if (-not (Test-Path $BackupFile)) { return }
  try {
    if (-not (Test-Path $ExternalDir)) {
      New-Item -ItemType Directory -Force -Path $ExternalDir | Out-Null
    }
    $dest = Join-Path $ExternalDir (Split-Path $BackupFile -Leaf)
    Copy-Item $BackupFile $dest -Force
    Write-Log "backup synced to external: $dest"
  } catch {
    # USB 未插入 / 权限不足 / 磁盘满 —— 仅警告，本地备份已成功
    Write-Log "WARN: external sync failed (non-fatal): $_"
  }
}

# --- 主流程 ---
Write-Log "=== XcagiBackup start ==="

$BackendExe = Find-BackendExe
if (-not $BackendExe) {
  Write-Log "ERROR: xcagi-backend.exe not found, cannot backup"
  exit 1
}

# 构造 CLI 参数
$cliArgs = @("--desktop", "--migrate-only", "--backup")
if ($DataDir) {
  $cliArgs += @("--data-dir", $DataDir)
}

Write-Log "invoking: $BackendExe $($cliArgs -join ' ')"
try {
  $proc = Start-Process -FilePath $BackendExe -ArgumentList $cliArgs `
    -NoNewWindow -Wait -PassThru -ErrorAction Stop
  if ($proc.ExitCode -ne 0) {
    Write-Log "ERROR: backend backup exited with code $($proc.ExitCode)"
    exit $proc.ExitCode
  }
} catch {
  Write-Log "ERROR: failed to invoke backend: $_"
  exit 1
}

# 定位数据目录（用于清理和外部同步）
$EffectiveDataDir = if ($DataDir) { $DataDir } else { Join-Path $AppData "XCAGI" }
$BackupsDir = Join-Path $EffectiveDataDir "backups"

# 找到本次产生的最新备份文件
$latest = Get-ChildItem -Path $BackupsDir -Filter "xcagi-*.db" -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
  Write-Log "latest backup: $($latest.Name) ($($latest.Length) bytes)"
  Sync-ToExternal $latest.FullName

  # 周日额外创建 weekly 副本（与应用内 backup_scheduler 策略一致）
  if ((Get-Date).DayOfWeek -eq 'Sunday' -and $latest.Name -match '^(xcagi-.+?)-(\d{14})\.db$') {
    $weeklyName = "$($Matches[1])-weekly-$($Matches[2]).db"
    $weeklyPath = Join-Path $BackupsDir $weeklyName
    try {
      Copy-Item $latest.FullName $weeklyPath -Force
      Write-Log "weekly backup created: $weeklyName"
      Sync-ToExternal $weeklyPath
    } catch {
      Write-Log "WARN: failed to create weekly copy: $_"
    }
  }
}

# 清理老旧备份
Cleanup-OldBackups $BackupsDir

Write-Log "=== XcagiBackup done ==="
exit 0
