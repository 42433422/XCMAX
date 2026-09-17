# XCMAX 桌面端手动恢复脚本
# =============================================================================
# 作用：当数据库损坏或需要回滚到某个时间点时，从 backups/ 目录选择一个备份
#       恢复到 xcagi.db。恢复前自动创建 pre-restore snapshot，便于撤销。
#
# 流程：
#   1. 列出 backups/ 中所有通过 integrity_check 的备份（按时间倒序）
#   2. 交互式选择一个（或通过 -BackupFile 指定）
#   3. 当前 xcagi.db 复制为 xcagi.db.pre-restore-{stamp}（snapshot）
#   4. 复制选中的备份到 xcagi.db
#   5. 复制同名 -wal/-shm 文件清理（WAL 模式残留）
#   6. 提示重启 XCAGI 应用
#
# 用法：
#   .\XcagiRestore.ps1                          # 交互式
#   .\XcagiRestore.ps1 -BackupFile "xcagi-10.0.0-20260705123000.db"
#   .\XcagiRestore.ps1 -DataDir "D:\XCAGI-Data" -BackupFile "..."
# =============================================================================
[CmdletBinding()]
param(
  [string]$DataDir = "",
  [string]$BackupFile = ""
)

$ErrorActionPreference = 'Stop'

# --- 路径 ---
$AppData = $env:APPDATA
if (-not $AppData) { $AppData = $env:LOCALAPPDATA }
if (-not $AppData) { $AppData = Join-Path $env:USERPROFILE "AppData\Roaming" }

$EffectiveDataDir = if ($DataDir) { $DataDir } else { Join-Path $AppData "XCAGI" }
$BackupsDir = Join-Path $EffectiveDataDir "backups"
$DbFile = Join-Path $EffectiveDataDir "data\xcagi.db"

if (-not (Test-Path $BackupsDir)) {
  Write-Error "backups directory not found: $BackupsDir"
  exit 1
}

# --- 校验备份完整性（用 xcagi-backend.exe 的 Python sqlite3 不可用，改用文件大小检查）---
function Test-BackupIntegrity([string]$path) {
  # 简单校验：文件存在且大于 1KB（空库也有几十 KB）
  if (-not (Test-Path $path)) { return $false }
  $size = (Get-Item $path).Length
  return $size -gt 1024
}

# --- 列出候选备份 ---
$candidates = Get-ChildItem -Path $BackupsDir -Filter "xcagi-*.db" -File -ErrorAction SilentlyContinue |
  Where-Object { Test-BackupIntegrity $_.FullName } |
  Sort-Object LastWriteTime -Descending

if (-not $candidates) {
  # 也扫 legacy database_backups/*.bak
  $legacyDir = Join-Path $EffectiveDataDir "data\database_backups"
  if (Test-Path $legacyDir) {
    $candidates = Get-ChildItem -Path $legacyDir -Filter "*.bak" -File -ErrorAction SilentlyContinue |
      Where-Object { Test-BackupIntegrity $_.FullName } |
      Sort-Object LastWriteTime -Descending
  }
}

if (-not $candidates) {
  Write-Error "no valid backup found in $BackupsDir"
  exit 1
}

# --- 选择备份 ---
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

Write-Host ""
Write-Host "Selected: $($selected.Name)"
Write-Host "  Time: $($selected.LastWriteTime)"
Write-Host "  Size: $($selected.Length) bytes"
Write-Host ""

# --- 确认 ---
$confirm = Read-Host "Restore this backup to $DbFile? This will overwrite current database. [y/N]"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
  Write-Host "aborted."
  exit 0
}

# --- 创建 pre-restore snapshot ---
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
if (Test-Path $DbFile) {
  $snapshot = "$DbFile.pre-restore-$stamp"
  Copy-Item $DbFile $snapshot -Force
  Write-Host "pre-restore snapshot created: $snapshot"

  # 清理 WAL/SHM 残留（恢复后应该重新生成）
  $walFile = "$DbFile-wal"
  $shmFile = "$DbFile-shm"
  if (Test-Path $walFile) { Remove-Item $walFile -Force; Write-Host "removed stale WAL: $walFile" }
  if (Test-Path $shmFile) { Remove-Item $shmFile -Force; Write-Host "removed stale SHM: $shmFile" }
}

# --- 恢复 ---
try {
  Copy-Item $selected.FullName $DbFile -Force
  Write-Host ""
  Write-Host "=== Restore complete ==="
  Write-Host "  Restored from: $($selected.Name)"
  Write-Host "  To: $DbFile"
  Write-Host ""
  Write-Host "Please restart XCAGI application."
  Write-Host "If startup fails, the corrupt db was saved as: $DbFile.pre-restore-$stamp"
} catch {
  Write-Error "restore failed: $_"
  Write-Host "Your original database snapshot is at: $DbFile.pre-restore-$stamp"
  exit 1
}
exit 0
