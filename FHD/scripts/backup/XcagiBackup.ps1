# XCMAX 桌面端定时备份脚本（Windows 计划任务调用入口）
# =============================================================================
# 作用：在 XCAGI 应用未运行时（如午休），由 Windows 计划任务触发一次 SQLite
#       在线热备份。复用 xcagi-backend.exe --desktop --migrate-only --backup
#       子命令，内部调用 sqlite3.backup() API + integrity_check 校验。
#
# 与应用内 backup_scheduler.py 的关系：
#   - 应用运行时：lifespan 启动 backup_scheduler 线程，每 24h 备份
#   - 应用未运行：本脚本由计划任务触发，作为补充（双保险）
#   - 两者文件名格式一致，清理策略一致（daily 7日 + weekly 28日）
#
# 用法：
#   .\XcagiBackup.ps1                              # 仅本地备份
#   .\XcagiBackup.ps1 -ExternalDir "E:\XCAGI-Backup"  # 同时备份到 USB 盘
#   .\XcagiBackup.ps1 -DataDir "D:\XCAGI-Data"     # 指定数据目录
#
# 日志：%APPDATA%\XCAGI\logs\backup.log
# =============================================================================
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
  # 1. 注册表（NSIS 安装）
  $regPaths = @(
    "HKCU:\Software\XCAGI",
    "HKLM:\Software\XCAGI",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\XCAGI"
  )
  foreach ($rp in $regPaths) {
    try {
      if (Test-Path $rp) {
        $v = Get-ItemProperty -Path $rp -ErrorAction SilentlyContinue
        if ($v.InstallPath) {
          $candidate = Join-Path $v.InstallPath "resources\backend\xcagi-backend.exe"
          if (Test-Path $candidate) { return $candidate }
        }
        if ($v.UninstallString) {
          $dir = Split-Path $v.UninstallString -Parent
          $candidate = Join-Path $dir "resources\backend\xcagi-backend.exe"
          if (Test-Path $candidate) { return $candidate }
        }
      }
    } catch { }
  }
  # 2. 常见安装路径
  $commonPaths = @(
    (Join-Path $env:LOCALAPPDATA "Programs\XCAGI\resources\backend\xcagi-backend.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\xcagi\resources\backend\xcagi-backend.exe"),
    "C:\Program Files\XCAGI\resources\backend\xcagi-backend.exe",
    "C:\Program Files (x86)\XCAGI\resources\backend\xcagi-backend.exe"
  )
  foreach ($p in $commonPaths) {
    if ($p -and (Test-Path $p)) { return $p }
  }
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
  $backendDir = Split-Path $BackendExe -Parent
  $proc = Start-Process -FilePath $BackendExe -ArgumentList $cliArgs `
    -WorkingDirectory $backendDir -NoNewWindow -Wait -PassThru -ErrorAction Stop
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
