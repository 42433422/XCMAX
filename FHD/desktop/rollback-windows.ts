import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export interface WindowsRollbackAppliedRecord {
  appliedAt: string
  reason: string
  fromVersion: string
  toVersion: string
}

export interface WindowsRollbackDatabaseTarget {
  /** 需要恢复的数据库真实路径 */
  databasePath: string
  /** 迁移前备份 */
  databaseBackupPath: string
}

export interface WindowsRestoreHelperCommand {
  /** 受控恢复程序的绝对路径（必须位于安装目录之外） */
  executable: string
  /** 附加参数（例如 -m app.desktop_runtime.restore_helper） */
  argv?: string[]
  /** 打包时生成的清单，用于核对哈希 */
  manifestPath: string
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
  /** 恢复操作 ID；数据库恢复必须提供 */
  operationId?: string
  /** 数据库恢复目标；存在时必须经受控恢复程序执行 */
  databaseTargets?: WindowsRollbackDatabaseTarget[]
  /** 允许的数据根目录（越界即拒绝） */
  allowedDataRoot?: string
  /** 受控恢复程序（已核验清单） */
  restoreHelper?: WindowsRestoreHelperCommand
  /** 受控恢复程序写出的回执路径 */
  restoreReceiptPath?: string
  /** 恢复操作记录（“进行中/结果未知”），必须先落盘 */
  operationRecordPath?: string
  restartApp?: boolean
  waitTimeoutSeconds?: number
  restoreTimeoutSeconds?: number
}

export interface WindowsRollbackLaunchResult {
  status: 'scheduled' | 'blocked' | 'unknown'
  /** 受控恢复程序退出码（未启动时为 undefined） */
  restoreExitCode?: number
  operationId?: string
  operationRecordPath?: string
  receiptPath?: string
  message?: string
}

export type WindowsRollbackErrorCode =
  | 'DB_GUARD_BAD_REQUEST'
  | 'DB_GUARD_PATH_ESCAPE'
  | 'DB_GUARD_HELPER_MISSING'
  | 'DB_GUARD_HELPER_UNVERIFIED'
  | 'DB_GUARD_RESTORE_FAILED'
  | 'DB_GUARD_UNKNOWN'

/** 回滚门控失败：调用方必须保持 UNKNOWN，不得继续换目录或重启。 */
export class WindowsRollbackGateError extends Error {
  readonly code: WindowsRollbackErrorCode

  constructor(code: WindowsRollbackErrorCode, message: string) {
    super(message)
    this.name = 'WindowsRollbackGateError'
    this.code = code
  }
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

function isPathInside(root: string, candidate: string): boolean {
  const resolvedRoot = path.resolve(root)
  const resolvedCandidate = path.resolve(candidate)
  const normalize = (value: string) =>
    process.platform === 'win32' ? value.toLowerCase() : value
  const rootKey = normalize(resolvedRoot)
  const candidateKey = normalize(resolvedCandidate)
  return candidateKey === rootKey || candidateKey.startsWith(`${rootKey}${path.sep}`)
}

function sha256File(filePath: string): string {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
}

function writeJsonAtomic(filePath: string, payload: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const temp = `${filePath}.tmp-${process.pid}-${Date.now()}`
  fs.writeFileSync(temp, JSON.stringify(payload, null, 2), 'utf8')
  fs.renameSync(temp, filePath)
}

export interface WindowsRestoreOperationRecord {
  operationId: string
  status: 'in_progress' | 'succeeded' | 'result_unknown'
  startedAt: string
  updatedAt: string
  reason: string
  targets: WindowsRollbackDatabaseTarget[]
  receiptPath: string
  message?: string
  restoreExitCode?: number
}

/** 启动恢复前必须落盘的“进行中”记录（需求第 19 条）。 */
export function writeWindowsRestoreOperationRecord(
  recordPath: string,
  record: WindowsRestoreOperationRecord,
): void {
  writeJsonAtomic(recordPath, record)
}

export function readWindowsRestoreOperationRecord(
  recordPath: string,
): WindowsRestoreOperationRecord | null {
  try {
    return JSON.parse(fs.readFileSync(recordPath, 'utf8')) as WindowsRestoreOperationRecord
  } catch {
    return null
  }
}

/**
 * 核验受控恢复程序写出的回执。
 *
 * 退出码 0 与“进程消失”都不等于恢复成功：必须同时满足
 * 回执存在、operationId 一致、状态为 succeeded、每个目标哈希与磁盘一致
 * 且目标仍在登记范围内。
 */
export function verifyWindowsRestoreReceipt(
  receiptPath: string,
  operationId: string,
  targets: WindowsRollbackDatabaseTarget[],
): void {
  let receipt: {
    operationId?: string
    status?: string
    targets?: Array<{ path?: string; sha256?: string }>
  }
  try {
    receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'))
  } catch {
    throw new WindowsRollbackGateError(
      'DB_GUARD_UNKNOWN',
      `恢复回执缺失或不可解析：${receiptPath}`,
    )
  }
  if (receipt.operationId !== operationId) {
    throw new WindowsRollbackGateError('DB_GUARD_UNKNOWN', '恢复回执 operationId 不匹配')
  }
  if (receipt.status !== 'succeeded') {
    throw new WindowsRollbackGateError(
      'DB_GUARD_UNKNOWN',
      `恢复回执状态不是 succeeded：${receipt.status ?? 'missing'}`,
    )
  }
  const recorded = new Map<string, string>()
  for (const item of receipt.targets ?? []) {
    if (item?.path) recorded.set(path.resolve(item.path), String(item.sha256 ?? ''))
  }
  for (const target of targets) {
    const resolved = path.resolve(target.databasePath)
    const expected = recorded.get(resolved)
    if (!expected) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_UNKNOWN',
        `恢复回执未登记目标：${resolved}`,
      )
    }
    if (!fs.existsSync(resolved)) {
      throw new WindowsRollbackGateError('DB_GUARD_UNKNOWN', `恢复后目标不存在：${resolved}`)
    }
    if (sha256File(resolved) !== expected) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_UNKNOWN',
        `恢复后目标哈希与回执不一致：${resolved}`,
      )
    }
  }
}

/** 校验受控恢复程序清单与磁盘哈希；失败即拒绝执行（需求第 16—17 条）。 */
export function verifyRestoreHelperBundle(helper: WindowsRestoreHelperCommand): void {
  const manifestPath = path.resolve(helper.manifestPath)
  let manifest: {
    executable?: string
    files?: Array<{ path?: string; sha256?: string }>
  }
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  } catch {
    throw new WindowsRollbackGateError(
      'DB_GUARD_HELPER_UNVERIFIED',
      `恢复程序清单缺失：${manifestPath}`,
    )
  }
  const files = Array.isArray(manifest.files) ? manifest.files : []
  if (files.length === 0) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_HELPER_UNVERIFIED',
      '恢复程序清单为空，无法核验依赖完整性',
    )
  }
  for (const entry of files) {
    if (!entry?.path || !entry.sha256) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_HELPER_UNVERIFIED',
        '恢复程序清单条目缺少 path 或 sha256',
      )
    }
    const absolute = path.resolve(path.dirname(manifestPath), entry.path)
    if (!fs.existsSync(absolute)) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_HELPER_UNVERIFIED',
        `恢复程序依赖缺失：${absolute}`,
      )
    }
    if (sha256File(absolute) !== entry.sha256) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_HELPER_UNVERIFIED',
        `恢复程序依赖哈希不匹配：${absolute}`,
      )
    }
  }
  if (!fs.existsSync(path.resolve(helper.executable))) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_HELPER_MISSING',
      `恢复程序不存在：${helper.executable}`,
    )
  }
  if (manifest.executable && path.resolve(manifest.executable) !== path.resolve(helper.executable)) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_HELPER_UNVERIFIED',
      '恢复程序与清单登记的 executable 不一致',
    )
  }
}

function assertDatabaseGate(options: WindowsRollbackLaunchOptions): void {
  const targets = options.databaseTargets ?? []
  if (targets.length === 0) {
    return
  }
  if (!options.operationId) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_BAD_REQUEST',
      '数据库恢复缺少 operationId，拒绝进入旧回滚链',
    )
  }
  if (!options.operationRecordPath || !options.restoreReceiptPath) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_BAD_REQUEST',
      '数据库恢复缺少操作记录或回执路径，拒绝执行',
    )
  }
  if (!options.restoreHelper) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_HELPER_MISSING',
      '未提供受控恢复程序，拒绝用 PowerShell 直接覆盖数据库',
    )
  }
  if (isPathInside(options.installDir, options.restoreHelper.executable)) {
    throw new WindowsRollbackGateError(
      'DB_GUARD_PATH_ESCAPE',
      '受控恢复程序不能位于待替换的安装目录内',
    )
  }
  for (const target of targets) {
    const database = resolveTargetPath(target.databasePath)
    const backup = resolveTargetPath(target.databaseBackupPath)
    if (options.allowedDataRoot) {
      const root = resolveTargetPath(options.allowedDataRoot)
      if (!isPathInside(root, database) || !isPathInside(root, backup)) {
        throw new WindowsRollbackGateError(
          'DB_GUARD_PATH_ESCAPE',
          `数据库目标或备份越界：${database} / ${backup}`,
        )
      }
    }
    if (path.resolve(database) === path.resolve(backup)) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_BAD_REQUEST',
        `备份与目标是同一文件：${database}`,
      )
    }
    if (!fs.existsSync(backup)) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_BAD_REQUEST',
        `数据库回滚备份不存在：${backup}`,
      )
    }
  }
}

function runProcess(
  executable: string,
  argv: string[],
  options: { cwd: string; timeoutMs: number },
): Promise<{ code: number | null; timedOut: boolean; stderr: string }> {
  return new Promise(resolve => {
    const child = spawn(executable, argv, {
      cwd: options.cwd,
      windowsHide: true,
      stdio: ['ignore', 'ignore', 'pipe'],
    })
    let stderr = ''
    let timedOut = false
    child.stderr?.on('data', chunk => {
      stderr += String(chunk)
    })
    const timer = setTimeout(() => {
      timedOut = true
      child.kill()
    }, options.timeoutMs)
    child.once('error', error => {
      clearTimeout(timer)
      resolve({ code: null, timedOut, stderr: `${stderr}${error.message}` })
    })
    child.once('exit', code => {
      clearTimeout(timer)
      resolve({ code, timedOut, stderr })
    })
  })
}

/**
 * 受控数据库恢复：先落盘“进行中”，再交给受控恢复程序，最后核验回执。
 * 任何一步失败都保留“结果未知”，不允许继续替换应用或重启。
 */
async function runGuardedDatabaseRestore(
  options: WindowsRollbackLaunchOptions,
): Promise<void> {
  const targets = options.databaseTargets ?? []
  const operationId = options.operationId as string
  const recordPath = options.operationRecordPath as string
  const receiptPath = options.restoreReceiptPath as string
  const helper = options.restoreHelper as WindowsRestoreHelperCommand

  verifyRestoreHelperBundle(helper)

  const now = new Date().toISOString()
  writeWindowsRestoreOperationRecord(recordPath, {
    operationId,
    status: 'in_progress',
    startedAt: now,
    updatedAt: now,
    reason: options.applied.reason,
    targets,
    receiptPath,
  })

  const argv = [
    ...(helper.argv ?? []),
    '--mode',
    'restore',
    '--operation-id',
    operationId,
    '--receipt',
    receiptPath,
  ]
  if (options.allowedDataRoot) {
    argv.push('--allowed-root', resolveTargetPath(options.allowedDataRoot))
  }
  for (const target of targets) {
    argv.push('--target', resolveTargetPath(target.databasePath))
    argv.push('--backup', resolveTargetPath(target.databaseBackupPath))
  }

  const result = await runProcess(helper.executable, argv, {
    cwd: path.dirname(recordPath),
    timeoutMs: Math.max(30_000, (options.restoreTimeoutSeconds ?? 600) * 1000),
  })

  const record = readWindowsRestoreOperationRecord(recordPath)
  const base = record ?? {
    operationId,
    status: 'in_progress' as const,
    startedAt: now,
    updatedAt: now,
    reason: options.applied.reason,
    targets,
    receiptPath,
  }

  if (result.timedOut) {
    writeWindowsRestoreOperationRecord(recordPath, {
      ...base,
      status: 'result_unknown',
      updatedAt: new Date().toISOString(),
      message: '受控恢复程序超时被终止，结果未知',
    })
    throw new WindowsRollbackGateError(
      'DB_GUARD_UNKNOWN',
      '受控恢复程序超时被终止，结果未知；禁止继续替换应用或重启',
    )
  }

  try {
    if (result.code !== 0) {
      throw new WindowsRollbackGateError(
        'DB_GUARD_RESTORE_FAILED',
        `受控恢复程序退出码 ${String(result.code)}：${result.stderr.slice(-500)}`,
      )
    }
    verifyWindowsRestoreReceipt(receiptPath, operationId, targets)
  } catch (error) {
    writeWindowsRestoreOperationRecord(recordPath, {
      ...base,
      status: 'result_unknown',
      updatedAt: new Date().toISOString(),
      restoreExitCode: result.code ?? undefined,
      message: error instanceof Error ? error.message : String(error),
    })
    throw error instanceof WindowsRollbackGateError
      ? error
      : new WindowsRollbackGateError('DB_GUARD_UNKNOWN', String(error))
  }

  writeWindowsRestoreOperationRecord(recordPath, {
    ...base,
    status: 'succeeded',
    updatedAt: new Date().toISOString(),
    restoreExitCode: 0,
  })
}

/**
 * 只做应用目录替换的 PowerShell 脚本：不写数据库、不删 WAL、不重启。
 *
 * 数据库恢复已在受控进程内完成并核验；这里仅替换安装目录。
 */
export function buildWindowsAppSwapScript(options: WindowsRollbackLaunchOptions): string {
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
    `$stagingDir = "$installDir.xcagi-rollback-staging"`,
    `$failedDir = "$installDir.xcagi-failed"`,
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
    '  Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  Remove-Item -LiteralPath $failedDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null',
    '  Get-ChildItem -LiteralPath $backupRoot -Force | Copy-Item -Destination $stagingDir -Recurse -Force',
    '  if (-not (Test-Path -LiteralPath (Join-Path $stagingDir $appFileName))) {',
    '    throw "staged rollback executable missing: $appFileName"',
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
    `  $appliedJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${appliedBase64}'))`,
    '  $appliedParent = Split-Path -Parent $appliedPath',
    '  if ($appliedParent) { New-Item -ItemType Directory -Path $appliedParent -Force | Out-Null }',
    '  [IO.File]::WriteAllText($appliedPath, $appliedJson, (New-Object Text.UTF8Encoding($false)))',
    '  Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue',
    '  Remove-Item -LiteralPath $failedDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  Write-RollbackLog "application directory swap completed"',
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
    '  Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue',
    '  exit 1',
    '}',
  ].join('\r\n')
}

function spawnAppSwap(options: WindowsRollbackLaunchOptions): Promise<number | undefined> {
  const encoded = Buffer.from(buildWindowsAppSwapScript(options), 'utf16le').toString('base64')
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

/**
 * Windows 回滚入口（唯一允许的入口）。
 *
 * 顺序：门控校验 → 受控数据库恢复并核验回执 → 锁释放后替换应用目录
 * →（可选）重启。数据库恢复未核验成功时不得进入后续步骤。
 */
export async function launchWindowsFullRollback(
  options: WindowsRollbackLaunchOptions,
): Promise<WindowsRollbackLaunchResult> {
  assertDatabaseGate(options)

  if ((options.databaseTargets ?? []).length > 0) {
    await runGuardedDatabaseRestore(options)
  }

  await spawnAppSwap(options)
  return {
    status: 'scheduled',
    operationId: options.operationId,
    operationRecordPath: options.operationRecordPath,
    receiptPath: options.restoreReceiptPath,
  }
}
