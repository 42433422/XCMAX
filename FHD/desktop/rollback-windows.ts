import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { createHash, randomUUID } from 'node:crypto'

export interface WindowsRollbackAppliedRecord {
  appliedAt: string
  reason: string
  fromVersion: string
  toVersion: string
}

export interface WindowsRollbackLaunchOptions {
  currentPid: number
  installDir: string
  backupRoot: string
  appPath: string
  markerPath: string
  appliedPath: string
  logPath: string
  applied: WindowsRollbackAppliedRecord
  databasePath?: string
  databaseBackupPath?: string
  databaseOriginallyAbsent?: boolean
  restartApp?: boolean
  waitTimeoutSeconds?: number
  expectedAppFiles?: Record<string, string>
  expectedDatabaseSha256?: string
  /** Optional inventory for customer-owned Mods and supported SQLite files. */
  ownedUserDataRoot?: string
  ownedBackupRoot?: string
  expectedOwnedFiles?: Record<string, string>
  expectedOwnedDirectories?: string[]
  /** Internal launch handshake. Omitted by the C# installer template generator. */
  helperStatusPath?: string
  helperStatusToken?: string
  helperAuthorizationPath?: string
}

interface WindowsRollbackHelperStatus {
  status?: unknown
  token?: unknown
  candidateScriptSha256?: unknown
  message?: unknown
  processId?: unknown
}

function powershellLiteral(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}

function resolveTargetPath(value: string): string {
  if (/^(?:[A-Za-z]:[\\/]|\\\\)/.test(value)) {
    return path.win32.resolve(value)
  }
  return path.resolve(value)
}

function targetBasename(value: string): string {
  if (/^(?:[A-Za-z]:[\\/]|\\\\)/.test(value)) {
    return path.win32.basename(value)
  }
  return path.basename(value)
}

/**
 * Restore the previous app and pre-migration DB after the failed process exits.
 * On failure, preserve SQLite sidecars and compensate both swaps before exiting.
 */
export function buildWindowsRollbackScript(options: WindowsRollbackLaunchOptions): string {
  const currentPid = Math.trunc(options.currentPid)
  if (!Number.isSafeInteger(currentPid) || currentPid <= 0) {
    throw new Error(`Invalid rollback wait pid: ${options.currentPid}`)
  }

  const installDir = resolveTargetPath(options.installDir)
  const backupRoot = resolveTargetPath(options.backupRoot)
  const appPath = resolveTargetPath(options.appPath)
  const markerPath = resolveTargetPath(options.markerPath)
  const appliedPath = resolveTargetPath(options.appliedPath)
  const logPath = resolveTargetPath(options.logPath)
  const helperStatusPath = options.helperStatusPath ? resolveTargetPath(options.helperStatusPath) : ''
  const helperStatusToken = options.helperStatusToken || ''
  const helperAuthorizationPath = options.helperAuthorizationPath ? resolveTargetPath(options.helperAuthorizationPath) : ''
  const appFileName = targetBasename(appPath)
  const waitTimeoutSeconds = Math.max(5, Math.trunc(options.waitTimeoutSeconds ?? 120))
  const appliedBase64 = Buffer.from(JSON.stringify(options.applied, null, 2), 'utf8').toString(
    'base64',
  )
  const databasePath =
    options.databasePath && (options.databaseBackupPath || options.databaseOriginallyAbsent)
      ? resolveTargetPath(options.databasePath)
      : ''
  const databaseBackupPath =
    options.databasePath && options.databaseBackupPath
      ? resolveTargetPath(options.databaseBackupPath)
      : ''
  const restartApp = options.restartApp !== false
  const expectedAppFiles = Buffer.from(JSON.stringify(options.expectedAppFiles || {})).toString('base64')
  const ownedUserDataRoot = options.ownedUserDataRoot ? resolveTargetPath(options.ownedUserDataRoot) : ''
  const ownedBackupRoot = options.ownedBackupRoot ? resolveTargetPath(options.ownedBackupRoot) : ''
  const expectedOwnedFiles = Buffer.from(JSON.stringify(options.expectedOwnedFiles || {})).toString('base64')
  const expectedOwnedDirectories = Buffer.from(JSON.stringify(options.expectedOwnedDirectories || [])).toString('base64')

  return [
    "$ErrorActionPreference = 'Stop'",
    `$waitPid = ${currentPid}`,
    `$installDir = ${powershellLiteral(installDir)}`,
    `$backupRoot = ${powershellLiteral(backupRoot)}`,
    `$appPath = ${powershellLiteral(appPath)}`,
    `$appFileName = ${powershellLiteral(appFileName)}`,
    `$markerPath = ${powershellLiteral(markerPath)}`,
    `$appliedPath = ${powershellLiteral(appliedPath)}`,
    `$logPath = ${powershellLiteral(logPath)}`,
    `$helperStatusPath = ${powershellLiteral(helperStatusPath)}`,
    `$helperStatusToken = ${powershellLiteral(helperStatusToken)}`,
    `$helperAuthorizationPath = ${powershellLiteral(helperAuthorizationPath)}`,
    '$helperStatusScriptSha256 = [string]$env:XCAGI_ROLLBACK_VERIFIED_SCRIPT_SHA256',
    `$databasePath = ${powershellLiteral(databasePath)}`,
    `$databaseOriginallyAbsent = $${options.databaseOriginallyAbsent ? 'true' : 'false'}`,
    `$databaseBackupPath = ${powershellLiteral(databaseBackupPath)}`,
    `$expectedAppFiles = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${expectedAppFiles}')) | ConvertFrom-Json`,
    `$expectedDatabaseSha256 = ${powershellLiteral(options.expectedDatabaseSha256 || '')}`,
    `$ownedUserDataRoot = ${powershellLiteral(ownedUserDataRoot)}`,
    `$ownedBackupRoot = ${powershellLiteral(ownedBackupRoot)}`,
    `$expectedOwnedFiles = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${expectedOwnedFiles}')) | ConvertFrom-Json`,
    `$expectedOwnedDirectories = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${expectedOwnedDirectories}')) | ConvertFrom-Json`,
    `$ownedStaging = if ($ownedBackupRoot) { Join-Path (Split-Path -Parent $ownedBackupRoot) 'os' } else { "" }`,
    `$ownedFailed = if ($ownedBackupRoot) { Join-Path (Split-Path -Parent $ownedBackupRoot) 'of' } else { "" }`,
    `$stagingDir = "$installDir.xcagi-rollback-staging"`,
    `$failedDir = "$installDir.xcagi-failed"`,
    `$databaseStaging = if ($databasePath) { "$databasePath.xcagi-rollback-staging" } else { "" }`,
    `$databaseFailed = if ($databasePath) { "$databasePath.xcagi-failed" } else { "" }`,
    '$appliedWritten = $appQuarantined = $databaseQuarantined = $false',
    '$appliedHadPrevious = $false; $appliedBackupPath = $appliedTempPath = $null; $rollbackCommitted = $false',
    '$stagingCreated = $databaseStagingCreated = $ownedStagingCreated = $false',
    '$ownedQuarantined = $false',
    '$ownedQuarantinedFiles = @()',
    '$ownedPromotedFiles = @()',
    '$ownedOriginalDirectories = @()',
    '$helperReady = $false',
    'function File-Sha256([string]$file) {',
    '  $stream = [IO.File]::OpenRead($file); $hash = [Security.Cryptography.SHA256]::Create()',
    '  try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace("-", "") } finally { $stream.Dispose(); $hash.Dispose() }',
    '}',
    'function Assert-AppSnapshot([string]$root) {',
    '  $expected = @($expectedAppFiles.PSObject.Properties)',
    '  if (-not $expected.Count) { return }',
    '  $root = [IO.Path]::GetFullPath($root).TrimEnd("\\")',
    '  if ((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "snapshot link rejected" }',
    '  $entries = @(Get-ChildItem -LiteralPath $root -Recurse -Force)',
    '  if (@($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "snapshot link rejected" }',
    '  if (@($entries | Where-Object { -not $_.PSIsContainer }).Count -ne $expected.Count) { throw "snapshot file set mismatch" }',
    '  foreach ($entry in $expected) {',
    '    $file = [IO.Path]::GetFullPath((Join-Path $root $entry.Name))',
    '    if (-not $file.StartsWith($root + "\\", [StringComparison]::OrdinalIgnoreCase)) { throw "snapshot path escaped" }',
    '    if ((File-Sha256 $file) -ne $entry.Value) { throw "snapshot file checksum mismatch" }',
    '  }',
    '}',
    'function Move-DatabaseFiles([string]$from, [string]$to) {',
    '  foreach ($suffix in @("", "-wal", "-shm", "-journal")) {',
    '    if (Test-Path -LiteralPath "$from$suffix") { Move-Item -LiteralPath "$from$suffix" -Destination "$to$suffix" -Force }',
    '  }',
    '}',
    'function Get-OwnedFiles([string]$root) {',
    '  $result = @(); if (-not $root -or -not (Test-Path -LiteralPath $root)) { return $result }',
    '  $root = [IO.Path]::GetFullPath($root).TrimEnd("\\")',
    '  $modRoot = Join-Path $root "mods"; if (Test-Path -LiteralPath $modRoot) { $result += @(Get-ChildItem -LiteralPath $modRoot -Recurse -File -Force) }',
    '  $rootDb = Get-ChildItem -LiteralPath $root -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "(?i)^(products|inventory|voice_learning|error_collection)(__[a-z0-9_-]+)?\\.db(?:-(?:wal|shm|journal))?$" }; $result += @($rootDb)',
    '  $dataRoot = Join-Path $root "data"; if (Test-Path -LiteralPath $dataRoot) {',
    '    $result += @(Get-ChildItem -LiteralPath $dataRoot -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "(?i)^.+\\.db(?:-(?:wal|shm|journal))?$" -and $_.Name -notmatch "(?i)^xcagi\\.db(?:-(?:wal|shm|journal))?$" })',
    '    $modDbRoot = Join-Path $dataRoot "mod_dbs"; if (Test-Path -LiteralPath $modDbRoot) { $result += @(Get-ChildItem -LiteralPath $modDbRoot -Recurse -File -Force | Where-Object { $_.Name -match "(?i)^.+\\.db(?:-(?:wal|shm|journal))?$" }) }',
    '  }',
    '  return @($result | Sort-Object -Property FullName -Unique)',
    '}',
    'function Get-OwnedDirectories([string]$root) {',
    '  $result = @(); if (-not $root -or -not (Test-Path -LiteralPath $root)) { return $result }; $root = [IO.Path]::GetFullPath($root).TrimEnd("\\")',
    '  foreach ($top in @("mods", "data")) { $base = Join-Path $root $top; if (-not (Test-Path -LiteralPath $base)) { continue }; $result += $top; if ($top -eq "mods") { $scan = $base } else { $scan = Join-Path $base "mod_dbs"; if (Test-Path -LiteralPath $scan) { $result += "data\\mod_dbs" } }; if (Test-Path -LiteralPath $scan) { $result += @(Get-ChildItem -LiteralPath $scan -Recurse -Directory -Force | ForEach-Object { $_.FullName.Substring($root.Length).TrimStart("\\") }) } }',
    '  return @($result | Sort-Object -Unique)',
    '}',
    'function Assert-OwnedInventory([string]$root, $expected) {',
    '  $root = [IO.Path]::GetFullPath($root).TrimEnd("\\"); $actual = @(Get-OwnedFiles $root)',
    '  if ($actual.Count -ne @($expected.PSObject.Properties).Count) { throw "owned state file set mismatch (actual=$($actual.Count), expected=$(@($expected.PSObject.Properties).Count))" }',
    '  foreach ($entry in @($expected.PSObject.Properties)) { $file = [IO.Path]::GetFullPath((Join-Path $root $entry.Name)); if (-not $file.StartsWith($root + "\\", [StringComparison]::OrdinalIgnoreCase)) { throw "owned state path escaped" }; if (-not (Test-Path -LiteralPath $file) -or (File-Sha256 $file) -ne $entry.Value) { throw "owned state checksum mismatch: $($entry.Name)" } }',
    '  if (@(Get-ChildItem -LiteralPath $root -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "owned state link rejected" }',
    '}',
    'function Restore-OwnedState([ref]$stagingRef, [ref]$quarantineRef, [ref]$quarantinedFilesRef, [ref]$promotedFilesRef, [ref]$originalDirectoriesRef) {',
    '  if (-not $ownedUserDataRoot -or -not $ownedBackupRoot) { return }',
    '  if ((Test-Path -LiteralPath $ownedStaging) -or (Test-Path -LiteralPath $ownedFailed)) { throw "retained owned-state rollback files must be recovered first" }',
    '  if (-not (Test-Path -LiteralPath $ownedBackupRoot)) { throw "owned-state snapshot missing" }',
    '  Assert-OwnedInventory $ownedBackupRoot $expectedOwnedFiles',
    '  $backupDirectories = @(Get-OwnedDirectories $ownedBackupRoot); if ($backupDirectories.Count -ne @($expectedOwnedDirectories).Count -or @($expectedOwnedDirectories | Where-Object { $_ -notin $backupDirectories }).Count) { throw "owned state directory snapshot mismatch" }',
    '  if (@(Get-ChildItem -LiteralPath $ownedUserDataRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "owned state link rejected" }',
    '  $originalDirectoriesRef.Value = @(Get-OwnedDirectories $ownedUserDataRoot)',
    '  New-Item -ItemType Directory -Path $ownedStaging | Out-Null; $stagingRef.Value = $true',
    '  foreach ($entry in @($expectedOwnedFiles.PSObject.Properties)) { $src = Join-Path $ownedBackupRoot $entry.Name; $dst = Join-Path $ownedStaging $entry.Name; New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null; Copy-Item -LiteralPath $src -Destination $dst; if ((File-Sha256 $dst) -ne $entry.Value) { throw "owned-state staged checksum mismatch" } }',
    '  $current = @(Get-OwnedFiles $ownedUserDataRoot); New-Item -ItemType Directory -Path $ownedFailed | Out-Null; $quarantineRef.Value = $true',
    '  foreach ($file in $current) { $rel = $file.FullName.Substring(([IO.Path]::GetFullPath($ownedUserDataRoot).TrimEnd("\\")).Length).TrimStart("\\"); $dest = Join-Path $ownedFailed $rel; New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null; Move-Item -LiteralPath $file.FullName -Destination $dest; $quarantinedFilesRef.Value += $rel }',
    '  foreach ($entry in @($expectedOwnedFiles.PSObject.Properties)) { $src = Join-Path $ownedStaging $entry.Name; $dst = Join-Path $ownedUserDataRoot $entry.Name; New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null; Move-Item -LiteralPath $src -Destination $dst; $promotedFilesRef.Value += $entry.Name }',
    '  Assert-OwnedInventory $ownedUserDataRoot $expectedOwnedFiles',
    '  foreach ($relative in $expectedOwnedDirectories) { $directory = [IO.Path]::GetFullPath((Join-Path $ownedUserDataRoot $relative)); if (-not $directory.StartsWith(([IO.Path]::GetFullPath($ownedUserDataRoot).TrimEnd("\\") + "\\"), [StringComparison]::OrdinalIgnoreCase)) { throw "owned directory path escaped" }; New-Item -ItemType Directory -Path $directory -Force | Out-Null }',
    '  foreach ($relative in @($ownedOriginalDirectories | Sort-Object { $_.Length } -Descending)) { if ($relative -notin $expectedOwnedDirectories) { $directory = Join-Path $ownedUserDataRoot $relative; if (Test-Path -LiteralPath $directory) { $items = @(Get-ChildItem -LiteralPath $directory -Force); if ($items.Count -eq 0) { Remove-Item -LiteralPath $directory -Force -ErrorAction Stop } } } }',
    '}',
    'function Write-RollbackLog([string]$message) {',
    '  try {',
    '    $parent = Split-Path -Parent $logPath',
    '    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }',
    '    Add-Content -LiteralPath $logPath -Value ("{0:o} {1}" -f (Get-Date), $message) -Encoding UTF8',
    '  } catch {}',
    '}',
    'function Write-HelperStatus([string]$status, [string]$message) {',
    '  if (-not $helperStatusPath -or -not $helperStatusToken) { return }',
    '  $parent = Split-Path -Parent $helperStatusPath',
    '  if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }',
    '  $record = @{ status = $status; token = $helperStatusToken; candidateScriptSha256 = $helperStatusScriptSha256; message = $message; processId = $PID } | ConvertTo-Json -Compress',
    '  $temporaryPath = "$helperStatusPath.$PID.tmp"',
    '  [IO.File]::WriteAllText($temporaryPath, $record, (New-Object Text.UTF8Encoding($false)))',
    '  [IO.File]::Move($temporaryPath, $helperStatusPath)',
    '}',
    'try {',
    '  Write-RollbackLog "verified rollback helper started"',
    '  foreach ($candidate in (@($stagingDir, $failedDir, $databaseStaging, $databaseFailed, $ownedStaging, $ownedFailed) + @(if ($databaseFailed) { "$databaseFailed-wal"; "$databaseFailed-shm"; "$databaseFailed-journal" }))) {',
    '    if ($candidate -and (Test-Path -LiteralPath $candidate)) { throw "retained rollback files must be recovered first: $candidate" }',
    '  }',
    '  Write-HelperStatus "ready" ""',
    '  $helperReady = $true',
    '  Write-RollbackLog "waiting for failed XCAGI process pid=$waitPid"',
    `  $deadline = (Get-Date).AddSeconds(${waitTimeoutSeconds})`,
    '  while (Get-Process -Id $waitPid -ErrorAction SilentlyContinue) {',
    '    if ((Get-Date) -ge $deadline) { throw "timed out waiting for pid=$waitPid" }',
    '    Start-Sleep -Milliseconds 250',
    '  }',
    '  if ($helperAuthorizationPath) {',
    '    if (-not (Test-Path -LiteralPath $helperAuthorizationPath)) { throw "rollback launch authorization missing; helper will not modify files" }',
    '    $authorization = Get-Content -LiteralPath $helperAuthorizationPath -Raw | ConvertFrom-Json',
    '    if ($authorization.state -ne "authorized" -or $authorization.token -ne $helperStatusToken -or $authorization.candidateScriptSha256 -ne $helperStatusScriptSha256 -or [int]$authorization.processId -ne $PID) { throw "rollback launch authorization did not match this helper" }',
    '  }',
    '  if (-not (Test-Path -LiteralPath $backupRoot)) { throw "rollback backup missing: $backupRoot" }',
    '  if (-not (Test-Path -LiteralPath (Join-Path $backupRoot $appFileName))) {',
    '    throw "rollback executable missing from backup: $appFileName"',
    '  }',
    '  if ($databasePath -and $databaseBackupPath -and (-not (Test-Path -LiteralPath $databaseBackupPath))) {',
    '    throw "database rollback backup missing: $databaseBackupPath"',
    '  }',
    '  Restore-OwnedState ([ref]$ownedStagingCreated) ([ref]$ownedQuarantined) ([ref]$ownedQuarantinedFiles) ([ref]$ownedPromotedFiles) ([ref]$ownedOriginalDirectories)',
    '  New-Item -ItemType Directory -Path $stagingDir | Out-Null',
    '  $stagingCreated = $true',
    '  Assert-AppSnapshot $backupRoot',
    '  Get-ChildItem -LiteralPath $backupRoot -Force | Copy-Item -Destination $stagingDir -Recurse -Force',
    '  Assert-AppSnapshot $stagingDir',
    '  if (-not (Test-Path -LiteralPath (Join-Path $stagingDir $appFileName))) {',
    '    throw "staged rollback executable missing: $appFileName"',
    '  }',
    '  if ($databasePath -and $databaseBackupPath) {',
    '    $databaseParent = Split-Path -Parent $databasePath',
    '    New-Item -ItemType Directory -Path $databaseParent -Force | Out-Null',
    '    if (Test-Path -LiteralPath $databaseStaging) { throw "database staging path already exists: $databaseStaging" }',
    '    Copy-Item -LiteralPath $databaseBackupPath -Destination $databaseStaging',
    '    $databaseStagingCreated = $true',
    '    if ($expectedDatabaseSha256 -and (File-Sha256 $databaseStaging) -ne $expectedDatabaseSha256) { throw "database snapshot checksum mismatch" }',
    '  }',
    '  if (Test-Path -LiteralPath $installDir) { Move-Item -LiteralPath $installDir -Destination $failedDir -Force; $appQuarantined = $true }',
    '  Move-Item -LiteralPath $stagingDir -Destination $installDir -Force',
    '  $stagingCreated = $false',
    '  if ($databasePath -and ($databaseBackupPath -or $databaseOriginallyAbsent)) {',
    '    $databaseQuarantined = $true',
    '    Move-DatabaseFiles $databasePath $databaseFailed',
    '    if (-not $databaseOriginallyAbsent) { Move-Item -LiteralPath $databaseStaging -Destination $databasePath -Force; $databaseStagingCreated = $false }',
    '  }',
    `  $appliedJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${appliedBase64}'))`,
    '  $appliedParent = Split-Path -Parent $appliedPath',
    '  if ($appliedParent) { New-Item -ItemType Directory -Path $appliedParent -Force | Out-Null }',
    '  $receiptId = [Guid]::NewGuid().ToString("N")',
    '  $appliedTempPath = $appliedPath + "." + $receiptId + ".tmp"',
    '  $appliedBackupPath = $appliedPath + "." + $receiptId + ".previous"',
    '  $appliedHadPrevious = Test-Path -LiteralPath $appliedPath',
    '  $receiptBytes = (New-Object Text.UTF8Encoding($false)).GetBytes($appliedJson)',
    '  $receiptStream = [IO.File]::Open($appliedTempPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)',
    '  try { $receiptStream.Write($receiptBytes, 0, $receiptBytes.Length); $receiptStream.Flush($true) } finally { $receiptStream.Dispose() }',
    '  if ($appliedHadPrevious) { [IO.File]::Replace($appliedTempPath, $appliedPath, $appliedBackupPath) } else { [IO.File]::Move($appliedTempPath, $appliedPath) }',
    '  $appliedWritten = $true',
    '  Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop',
    '  $rollbackCommitted = $true; $appliedWritten = $false',
    '  Remove-Item -LiteralPath $failedDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  if ($appliedBackupPath -and (Test-Path -LiteralPath $appliedBackupPath)) { Remove-Item -LiteralPath $appliedBackupPath -Force -ErrorAction SilentlyContinue }',
    '  if ($ownedFailed) { Remove-Item -LiteralPath $ownedFailed -Recurse -Force -ErrorAction SilentlyContinue }',
    '  if ($ownedStaging) { Remove-Item -LiteralPath $ownedStaging -Recurse -Force -ErrorAction SilentlyContinue }',
    '  if ($databaseFailed) { foreach ($suffix in @("", "-wal", "-shm", "-journal")) { Remove-Item -LiteralPath "$databaseFailed$suffix" -Force -ErrorAction SilentlyContinue } }',
    '  Write-RollbackLog "full application rollback completed"',
    ...(restartApp
      ? [
          '  try {',
          '    Start-Process -FilePath $appPath',
          '  } catch {',
          '    Write-RollbackLog ("rollback succeeded but restart failed: " + $_.Exception.Message)',
          '  }',
        ]
      : []),
    '} catch {',
    '  if ($rollbackCommitted) { try { Write-RollbackLog ("rollback committed; later bookkeeping failed: " + $_.Exception.Message) } catch {}; exit 0 }',
    '  Write-RollbackLog ("rollback failed: " + $_.Exception.Message)',
    '  if (-not $helperReady) { try { Write-HelperStatus "failed" $_.Exception.Message } catch {} }',
    '  Write-Error ("rollback failed: " + $_.Exception.Message) -ErrorAction Continue',
    '  if ($appliedWritten) {',
    '    try {',
    '      if ($appliedHadPrevious -and (Test-Path -LiteralPath $appliedBackupPath)) { [IO.File]::Replace($appliedBackupPath, $appliedPath, ($appliedTempPath + ".failed")) }',
    '      elseif (-not $appliedHadPrevious) { [IO.File]::Delete($appliedPath) }',
    '      $appliedWritten = $false',
    '    } catch { Write-RollbackLog ("could not restore previous applied receipt; backup retained at " + $appliedBackupPath + ": " + $_.Exception.Message) }',
    '  }',
    '  if ($appQuarantined -and (Test-Path -LiteralPath $failedDir)) {',
    '    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue',
    '    Move-Item -LiteralPath $failedDir -Destination $installDir -Force -ErrorAction SilentlyContinue',
    '  }',
    '  if ($databaseQuarantined) {',
    '    Move-DatabaseFiles $databaseFailed $databasePath',
    '  }',
    '  if ($ownedQuarantined -and (Test-Path -LiteralPath $ownedFailed)) {',
    '    $ownedCompensationFailed = $false',
    '    foreach ($rel in $ownedPromotedFiles) { $promoted = Join-Path $ownedUserDataRoot $rel; if (Test-Path -LiteralPath $promoted) { try { Remove-Item -LiteralPath $promoted -Force -ErrorAction Stop } catch { $ownedCompensationFailed = $true; Write-RollbackLog ("owned-state compensation could not remove promoted snapshot file " + $promoted + ": " + $_.Exception.Message) } } }',
    '    foreach ($rel in $ownedQuarantinedFiles) { $file = Join-Path $ownedFailed $rel; if (Test-Path -LiteralPath $file) { $dest = Join-Path $ownedUserDataRoot $rel; try { New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null; $hash = File-Sha256 $file; Move-Item -LiteralPath $file -Destination $dest -Force -ErrorAction Stop; if ((File-Sha256 $dest) -ne $hash) { throw "restored candidate checksum mismatch" } } catch { $ownedCompensationFailed = $true; Write-RollbackLog ("owned-state compensation could not restore quarantined file " + $dest + ": " + $_.Exception.Message) } } }',
    '    foreach ($relative in $ownedOriginalDirectories) { try { New-Item -ItemType Directory -Path (Join-Path $ownedUserDataRoot $relative) -Force | Out-Null } catch { $ownedCompensationFailed = $true; Write-RollbackLog ("owned-state compensation could not recreate candidate directory " + $relative + ": " + $_.Exception.Message) } }',
    '    foreach ($relative in @($expectedOwnedDirectories | Sort-Object { $_.Length } -Descending)) { if ($relative -notin $ownedOriginalDirectories) { $directory = Join-Path $ownedUserDataRoot $relative; if (Test-Path -LiteralPath $directory) { try { $items = @(Get-ChildItem -LiteralPath $directory -Force); if ($items.Count -eq 0) { Remove-Item -LiteralPath $directory -Force -ErrorAction Stop } } catch { $ownedCompensationFailed = $true; Write-RollbackLog ("owned-state compensation could not remove created directory " + $relative + ": " + $_.Exception.Message) } } } }',
    '    if (-not $ownedCompensationFailed) { Remove-Item -LiteralPath $ownedFailed -Recurse -Force -ErrorAction SilentlyContinue }',
    '  }',
    '  if ($appliedTempPath -and (Test-Path -LiteralPath $appliedTempPath)) { Remove-Item -LiteralPath $appliedTempPath -Force -ErrorAction SilentlyContinue }',
    '  if ($stagingCreated) { Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue }',
    '  if ($databaseStagingCreated -and $databaseStaging) { Remove-Item -LiteralPath $databaseStaging -Force -ErrorAction SilentlyContinue }',
    '  if ($ownedStagingCreated -and $ownedStaging) { Remove-Item -LiteralPath $ownedStaging -Recurse -Force -ErrorAction SilentlyContinue }',
    '  exit 1',
    '}',
  ].join('\r\n')
}

export function buildWindowsRollbackFileLoader(scriptPath: string, sha256: string): string {
  if (!/^[0-9a-f]{64}$/i.test(sha256)) throw new Error('Invalid rollback script checksum')
  return [
    "$ErrorActionPreference = 'Stop'",
    `$stream = [IO.File]::Open(${powershellLiteral(scriptPath)}, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)`,
    '$hash = [Security.Cryptography.SHA256]::Create()',
    'try {',
    `  if ([BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '') -ne '${sha256}') { throw 'rollback script checksum mismatch' }`,
    '  $stream.Position = 0',
    `  $env:XCAGI_ROLLBACK_VERIFIED_SCRIPT_SHA256 = '${sha256}'`,
    '  $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8, $true)',
    '  & ([ScriptBlock]::Create($reader.ReadToEnd()))',
    '} finally { $stream.Dispose(); $hash.Dispose() }',
  ].join('\r\n')
}

export function launchWindowsFullRollback(
  options: WindowsRollbackLaunchOptions,
  readinessTimeoutMs = 15_000,
): Promise<number | undefined> {
  const directory = path.dirname(resolveTargetPath(options.logPath))
  fs.mkdirSync(directory, { recursive: true })
  const handshakeId = randomUUID()
  const helperStatusPath = path.join(directory, `rollback-status-${handshakeId}.json`)
  const helperAuthorizationPath = path.join(directory, `rollback-authorize-${handshakeId}.json`)
  const helperStatusToken = randomUUID()
  const finalScript = buildWindowsRollbackScript({ ...options, helperStatusPath, helperStatusToken, helperAuthorizationPath })
  const finalScriptSha256 = createHash('sha256').update(finalScript).digest('hex')
  const scriptPath = path.join(directory, `rollback-script-${handshakeId}.ps1`)
  fs.writeFileSync(scriptPath, finalScript, { encoding: 'utf8', mode: 0o600, flag: 'wx' })
  const encoded = Buffer.from(buildWindowsRollbackFileLoader(scriptPath, finalScriptSha256), 'utf16le').toString('base64')
  return new Promise((resolve, reject) => {
    const child = spawn(
      'powershell.exe',
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-EncodedCommand',
        encoded,
      ],
      {
        cwd: path.dirname(resolveTargetPath(options.logPath)),
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
      },
    )
    let settled = false
    let spawned = false
    let pollTimer: NodeJS.Timeout | undefined
    let timeoutTimer: NodeJS.Timeout | undefined
    const cleanUp = () => {
      if (pollTimer) clearInterval(pollTimer)
      if (timeoutTimer) clearTimeout(timeoutTimer)
      child.removeListener('error', onError)
      child.removeListener('exit', onExit)
      child.removeListener('close', onClose)
      child.removeListener('spawn', onSpawn)
    }
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      cleanUp()
      // A readiness failure must not keep Electron alive; detach only after readiness or failure.
      try { child.unref() } catch {}
      if (error) reject(error)
      else resolve(child.pid)
    }
    const checkStatus = (acceptReady = true) => {
      if (!spawned || settled) return
      let status: WindowsRollbackHelperStatus
      try {
        status = JSON.parse(fs.readFileSync(helperStatusPath, 'utf8')) as WindowsRollbackHelperStatus
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') return
        finish(new Error(`Windows rollback helper wrote an unreadable readiness record: ${(error as Error).message}`))
        return
      }
      if (status.token !== helperStatusToken || status.candidateScriptSha256 !== finalScriptSha256) {
        finish(new Error('Windows rollback helper readiness token did not match'))
      } else if (typeof child.pid !== 'number' || status.processId !== child.pid) {
        finish(new Error('Windows rollback helper process identity did not match'))
      } else if (status.status === 'ready') {
        if (!acceptReady) return
        try {
          const authorizationPath = `${helperAuthorizationPath}.${process.pid}.tmp`
          fs.writeFileSync(
            authorizationPath,
            JSON.stringify({ state: 'authorized', token: helperStatusToken, candidateScriptSha256: finalScriptSha256, processId: child.pid }),
            { encoding: 'utf8', mode: 0o600, flag: 'wx' },
          )
          fs.renameSync(authorizationPath, helperAuthorizationPath)
          finish()
        } catch (error) {
          finish(new Error(`Could not authorize Windows rollback helper after readiness: ${(error as Error).message}`))
        }
      } else if (status.status === 'failed') {
        finish(new Error(`Windows rollback helper failed before readiness: ${String(status.message || 'unknown preflight failure')}`))
      } else {
        finish(new Error(`Windows rollback helper reported an unknown readiness state: ${String(status.status)}`))
      }
    }
    const onError = (error: Error) => finish(new Error(`Could not launch Windows rollback helper: ${error.message}`))
    const onExit = (code: number | null, signal: NodeJS.Signals | null) => {
      checkStatus(false)
      if (!settled) finish(new Error(`Windows rollback helper exited before readiness (code ${String(code)}, signal ${String(signal)})`))
    }
    const onClose = (code: number | null, signal: NodeJS.Signals | null) => {
      checkStatus(false)
      if (!settled) finish(new Error(`Windows rollback helper closed before readiness (code ${String(code)}, signal ${String(signal)})`))
    }
    const onSpawn = () => {
      spawned = true
      checkStatus()
      if (settled) return
      pollTimer = setInterval(checkStatus, 25)
      timeoutTimer = setTimeout(() => {
        finish(new Error(`Windows rollback helper did not report readiness within ${readinessTimeoutMs} ms`))
      }, readinessTimeoutMs)
    }
    child.once('error', onError)
    child.once('exit', onExit)
    child.once('close', onClose)
    child.once('spawn', onSpawn)
  })
}
