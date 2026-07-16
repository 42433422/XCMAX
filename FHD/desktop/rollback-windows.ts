import { spawn } from 'node:child_process'
import path from 'node:path'

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
  restartApp?: boolean
  waitTimeoutSeconds?: number
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
 * PowerShell runs outside the installed XCAGI directory. It waits for the
 * failed new process to exit, stages the complete previous app directory,
 * swaps it into place, restores the pre-migration database when present, and
 * only then records a successful rollback and restarts the old executable.
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
  const appFileName = targetBasename(appPath)
  const waitTimeoutSeconds = Math.max(5, Math.trunc(options.waitTimeoutSeconds ?? 120))
  const appliedBase64 = Buffer.from(JSON.stringify(options.applied, null, 2), 'utf8').toString(
    'base64',
  )
  const databasePath =
    options.databasePath && options.databaseBackupPath
      ? resolveTargetPath(options.databasePath)
      : ''
  const databaseBackupPath =
    options.databasePath && options.databaseBackupPath
      ? resolveTargetPath(options.databaseBackupPath)
      : ''
  const restartApp = options.restartApp !== false

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
    `$databasePath = ${powershellLiteral(databasePath)}`,
    `$databaseBackupPath = ${powershellLiteral(databaseBackupPath)}`,
    `$stagingDir = "$installDir.xcagi-rollback-staging"`,
    `$failedDir = "$installDir.xcagi-failed"`,
    `$databaseStaging = if ($databasePath) { "$databasePath.xcagi-rollback-staging" } else { "" }`,
    `$databaseFailed = if ($databasePath) { "$databasePath.xcagi-failed" } else { "" }`,
    'function Write-RollbackLog([string]$message) {',
    '  try {',
    '    $parent = Split-Path -Parent $logPath',
    '    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }',
    '    Add-Content -LiteralPath $logPath -Value ("{0:o} {1}" -f (Get-Date), $message) -Encoding UTF8',
    '  } catch {}',
    '}',
    'try {',
    '  Write-RollbackLog "waiting for failed XCAGI process pid=$waitPid"',
    `  $deadline = (Get-Date).AddSeconds(${waitTimeoutSeconds})`,
    '  while (Get-Process -Id $waitPid -ErrorAction SilentlyContinue) {',
    '    if ((Get-Date) -ge $deadline) { throw "timed out waiting for pid=$waitPid" }',
    '    Start-Sleep -Milliseconds 250',
    '  }',
    '  if (-not (Test-Path -LiteralPath $backupRoot)) { throw "rollback backup missing: $backupRoot" }',
    '  if (-not (Test-Path -LiteralPath (Join-Path $backupRoot $appFileName))) {',
    '    throw "rollback executable missing from backup: $appFileName"',
    '  }',
    '  if ($databasePath -and $databaseBackupPath -and (-not (Test-Path -LiteralPath $databaseBackupPath))) {',
    '    throw "database rollback backup missing: $databaseBackupPath"',
    '  }',
    '  Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  Remove-Item -LiteralPath $failedDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  if ($databaseStaging) { Remove-Item -LiteralPath $databaseStaging -Force -ErrorAction SilentlyContinue }',
    '  if ($databaseFailed) { Remove-Item -LiteralPath $databaseFailed -Force -ErrorAction SilentlyContinue }',
    '  New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null',
    '  Get-ChildItem -LiteralPath $backupRoot -Force | Copy-Item -Destination $stagingDir -Recurse -Force',
    '  if (-not (Test-Path -LiteralPath (Join-Path $stagingDir $appFileName))) {',
    '    throw "staged rollback executable missing: $appFileName"',
    '  }',
    '  if ($databasePath -and $databaseBackupPath) {',
    '    $databaseParent = Split-Path -Parent $databasePath',
    '    New-Item -ItemType Directory -Path $databaseParent -Force | Out-Null',
    '    Copy-Item -LiteralPath $databaseBackupPath -Destination $databaseStaging -Force',
    '  }',
    '  if (Test-Path -LiteralPath $installDir) { Move-Item -LiteralPath $installDir -Destination $failedDir -Force }',
    '  try {',
    '    Move-Item -LiteralPath $stagingDir -Destination $installDir -Force',
    '  } catch {',
    '    if ((-not (Test-Path -LiteralPath $installDir)) -and (Test-Path -LiteralPath $failedDir)) {',
    '      Move-Item -LiteralPath $failedDir -Destination $installDir -Force',
    '    }',
    '    throw',
    '  }',
    '  if ($databasePath -and $databaseBackupPath) {',
    '    if (Test-Path -LiteralPath $databasePath) {',
    '      Move-Item -LiteralPath $databasePath -Destination $databaseFailed -Force',
    '    }',
    '    try {',
    '      Move-Item -LiteralPath $databaseStaging -Destination $databasePath -Force',
    '    } catch {',
    '      if ((-not (Test-Path -LiteralPath $databasePath)) -and (Test-Path -LiteralPath $databaseFailed)) {',
    '        Move-Item -LiteralPath $databaseFailed -Destination $databasePath -Force',
    '      }',
    '      throw',
    '    }',
    '    Remove-Item -LiteralPath "$databasePath-wal" -Force -ErrorAction SilentlyContinue',
    '    Remove-Item -LiteralPath "$databasePath-shm" -Force -ErrorAction SilentlyContinue',
    '  }',
    `  $appliedJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${appliedBase64}'))`,
    '  $appliedParent = Split-Path -Parent $appliedPath',
    '  if ($appliedParent) { New-Item -ItemType Directory -Path $appliedParent -Force | Out-Null }',
    '  [IO.File]::WriteAllText($appliedPath, $appliedJson, (New-Object Text.UTF8Encoding($false)))',
    '  Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue',
    '  Remove-Item -LiteralPath $failedDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  if ($databaseFailed) { Remove-Item -LiteralPath $databaseFailed -Force -ErrorAction SilentlyContinue }',
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
    '  Write-RollbackLog ("rollback failed: " + $_.Exception.Message)',
    '  Write-Error ("rollback failed: " + $_.Exception.Message)',
    '  if (Test-Path -LiteralPath $failedDir) {',
    '    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue',
    '    Move-Item -LiteralPath $failedDir -Destination $installDir -Force -ErrorAction SilentlyContinue',
    '  }',
    '  if ($databaseFailed -and (Test-Path -LiteralPath $databaseFailed)) {',
    '    Remove-Item -LiteralPath $databasePath -Force -ErrorAction SilentlyContinue',
    '    Move-Item -LiteralPath $databaseFailed -Destination $databasePath -Force -ErrorAction SilentlyContinue',
    '  }',
    '  Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  if ($databaseStaging) { Remove-Item -LiteralPath $databaseStaging -Force -ErrorAction SilentlyContinue }',
    '  exit 1',
    '}',
  ].join('\r\n')
}

export function launchWindowsFullRollback(
  options: WindowsRollbackLaunchOptions,
): Promise<number | undefined> {
  const encoded = Buffer.from(buildWindowsRollbackScript(options), 'utf16le').toString('base64')
  return new Promise((resolve, reject) => {
    const child = spawn(
      'powershell.exe',
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
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
    child.once('error', reject)
    child.once('spawn', () => {
      child.unref()
      resolve(child.pid)
    })
  })
}
