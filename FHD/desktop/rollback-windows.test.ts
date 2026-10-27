import { afterEach, describe, expect, it } from 'vitest'
import { execFile } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import {
  buildWindowsAppSwapScript,
  launchWindowsFullRollback,
  readWindowsRestoreOperationRecord,
  verifyRestoreHelperBundle,
  verifyWindowsRestoreReceipt,
  WindowsRollbackGateError,
  writeWindowsRestoreOperationRecord,
  type WindowsRollbackLaunchOptions,
} from './rollback-windows.js'

const windowsIt = process.platform === 'win32' ? it : it.skip
const cleanupRoots: string[] = []
const execFileAsync = promisify(execFile)

afterEach(() => {
  for (const root of cleanupRoots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

function baseOptions(root: string): WindowsRollbackLaunchOptions {
  return {
    currentPid: 42,
    installDir: path.join(root, 'XCAGI'),
    backupRoot: path.join(root, 'rollback', 'windows-app-current'),
    appPath: path.join(root, 'XCAGI', 'XCAGI.exe'),
    markerPath: path.join(root, 'rollback-marker.json'),
    appliedPath: path.join(root, 'rollback-applied.json'),
    logPath: path.join(root, 'rollback-helper.log'),
    applied: {
      appliedAt: '2026-07-16T00:00:00.000Z',
      reason: 'test',
      fromVersion: '1.0.0.0-new',
      toVersion: '1.0.0.0-old',
    },
  }
}

function sha256(filePath: string): string {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
}

describe('Windows application swap script', () => {
  it('encodes paths and the applied record without interpolating raw JSON', () => {
    const script = buildWindowsAppSwapScript({
      ...baseOptions('/tmp/xcagi'),
      installDir: "C:\\Users\\O'Brien\\XCAGI",
      appPath: "C:\\Users\\O'Brien\\XCAGI\\XCAGI.exe",
      backupRoot: 'C:\\rollback\\app',
      applied: {
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: "window couldn't start",
        fromVersion: '1.0.0.0',
        toVersion: '1.0.0.0',
      },
    })
    expect(script).toContain("'C:\\Users\\O''Brien\\XCAGI'")
    expect(script).toContain('FromBase64String')
    expect(script).not.toContain("window couldn't start")
    expect(script).toContain('Move-Item -LiteralPath $stagingDir -Destination $installDir')
  })

  it('never writes to the database or deletes WAL sidecars', () => {
    const script = buildWindowsAppSwapScript({
      ...baseOptions('/tmp/xcagi'),
      databaseTargets: [
        {
          databasePath: '/tmp/xcagi/data/xcagi.db',
          databaseBackupPath: '/tmp/xcagi/backups/pre.db',
        },
      ],
    })
    expect(script).not.toMatch(/\$databasePath/)
    expect(script).not.toMatch(/-wal/)
    expect(script).not.toMatch(/-shm/)
    expect(script).not.toMatch(/Copy-Item[^\\n]*xcagi\.db/)
  })
})

describe('Windows rollback gate', () => {
  it('refuses database restore without an operationId', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-gate-'))
    cleanupRoots.push(root)
    const backup = path.join(root, 'pre.db')
    fs.writeFileSync(backup, 'db')
    await expect(
      launchWindowsFullRollback({
        ...baseOptions(root),
        databaseTargets: [{ databasePath: path.join(root, 'xcagi.db'), databaseBackupPath: backup }],
      }),
    ).rejects.toMatchObject({ code: 'DB_GUARD_BAD_REQUEST' })
  })

  it('refuses database restore without a trusted helper', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-gate-'))
    cleanupRoots.push(root)
    const backup = path.join(root, 'pre.db')
    fs.writeFileSync(backup, 'db')
    await expect(
      launchWindowsFullRollback({
        ...baseOptions(root),
        operationId: 'op-1',
        operationRecordPath: path.join(root, 'op.json'),
        restoreReceiptPath: path.join(root, 'receipt.json'),
        databaseTargets: [{ databasePath: path.join(root, 'xcagi.db'), databaseBackupPath: backup }],
      }),
    ).rejects.toMatchObject({ code: 'DB_GUARD_HELPER_MISSING' })
  })

  it('refuses a helper placed inside the directory that will be replaced', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-gate-'))
    cleanupRoots.push(root)
    const installDir = path.join(root, 'XCAGI')
    fs.mkdirSync(installDir, { recursive: true })
    const helper = path.join(installDir, 'restore-helper.exe')
    fs.writeFileSync(helper, 'helper')
    const manifest = path.join(installDir, 'manifest.json')
    fs.writeFileSync(
      manifest,
      JSON.stringify({
        executable: helper,
        files: [{ path: helper, sha256: sha256(helper) }],
      }),
    )
    const backup = path.join(root, 'pre.db')
    fs.writeFileSync(backup, 'db')
    await expect(
      launchWindowsFullRollback({
        ...baseOptions(root),
        installDir,
        operationId: 'op-1',
        operationRecordPath: path.join(root, 'op.json'),
        restoreReceiptPath: path.join(root, 'receipt.json'),
        restoreHelper: { executable: helper, manifestPath: manifest },
        databaseTargets: [{ databasePath: path.join(root, 'xcagi.db'), databaseBackupPath: backup }],
      }),
    ).rejects.toMatchObject({ code: 'DB_GUARD_PATH_ESCAPE' })
  })

  it('refuses an unverified helper bundle', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-bundle-'))
    cleanupRoots.push(root)
    const helper = path.join(root, 'restore-helper')
    fs.writeFileSync(helper, 'helper')
    const manifest = path.join(root, 'manifest.json')
    fs.writeFileSync(manifest, JSON.stringify({ executable: helper, files: [] }))
    expect(() =>
      verifyRestoreHelperBundle({ executable: helper, manifestPath: manifest }),
    ).toThrow(WindowsRollbackGateError)
  })

  it('refuses a helper whose dependency hash does not match', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-bundle-'))
    cleanupRoots.push(root)
    const helper = path.join(root, 'restore-helper')
    fs.writeFileSync(helper, 'helper')
    const manifest = path.join(root, 'manifest.json')
    fs.writeFileSync(
      manifest,
      JSON.stringify({ executable: helper, files: [{ path: helper, sha256: 'deadbeef' }] }),
    )
    expect(() => verifyRestoreHelperBundle({ executable: helper, manifestPath: manifest })).toThrow(
      /哈希不匹配/,
    )
  })
})

describe('Windows restore receipt verification', () => {
  it('accepts a receipt whose hashes match the restored database', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-receipt-'))
    cleanupRoots.push(root)
    const database = path.join(root, 'xcagi.db')
    fs.writeFileSync(database, 'restored-bytes')
    const receipt = path.join(root, 'receipt.json')
    fs.writeFileSync(
      receipt,
      JSON.stringify({
        operationId: 'op-1',
        status: 'succeeded',
        targets: [{ path: database, sha256: sha256(database) }],
      }),
    )
    expect(() =>
      verifyWindowsRestoreReceipt(receipt, 'op-1', [
        { databasePath: database, databaseBackupPath: path.join(root, 'pre.db') },
      ]),
    ).not.toThrow()
  })

  it('rejects a mismatched operationId', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-receipt-'))
    cleanupRoots.push(root)
    const database = path.join(root, 'xcagi.db')
    fs.writeFileSync(database, 'restored-bytes')
    const receipt = path.join(root, 'receipt.json')
    fs.writeFileSync(
      receipt,
      JSON.stringify({ operationId: 'other', status: 'succeeded', targets: [] }),
    )
    expect(() =>
      verifyWindowsRestoreReceipt(receipt, 'op-1', [
        { databasePath: database, databaseBackupPath: path.join(root, 'pre.db') },
      ]),
    ).toThrow(/operationId 不匹配/)
  })

  it('rejects a receipt whose hash no longer matches disk', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-receipt-'))
    cleanupRoots.push(root)
    const database = path.join(root, 'xcagi.db')
    fs.writeFileSync(database, 'restored-bytes')
    const receipt = path.join(root, 'receipt.json')
    fs.writeFileSync(
      receipt,
      JSON.stringify({
        operationId: 'op-1',
        status: 'succeeded',
        targets: [{ path: database, sha256: '0'.repeat(64) }],
      }),
    )
    expect(() =>
      verifyWindowsRestoreReceipt(receipt, 'op-1', [
        { databasePath: database, databaseBackupPath: path.join(root, 'pre.db') },
      ]),
    ).toThrow(/哈希与回执不一致/)
  })

  it('rejects a missing receipt even when the helper exited 0', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-receipt-'))
    cleanupRoots.push(root)
    expect(() =>
      verifyWindowsRestoreReceipt(path.join(root, 'missing.json'), 'op-1', []),
    ).toThrow(/回执缺失/)
  })
})

describe('Windows restore operation record', () => {
  it('persists in_progress before execution and result_unknown afterwards', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-op-'))
    cleanupRoots.push(root)
    const recordPath = path.join(root, 'restore-operation.json')
    const now = new Date().toISOString()
    writeWindowsRestoreOperationRecord(recordPath, {
      operationId: 'op-1',
      status: 'in_progress',
      startedAt: now,
      updatedAt: now,
      reason: 'test',
      targets: [],
      receiptPath: path.join(root, 'receipt.json'),
    })
    expect(readWindowsRestoreOperationRecord(recordPath)?.status).toBe('in_progress')

    writeWindowsRestoreOperationRecord(recordPath, {
      operationId: 'op-1',
      status: 'result_unknown',
      startedAt: now,
      updatedAt: now,
      reason: 'test',
      targets: [],
      receiptPath: path.join(root, 'receipt.json'),
      message: 'helper crashed',
    })
    expect(readWindowsRestoreOperationRecord(recordPath)?.status).toBe('result_unknown')
  })
})

const windowsItIntegration = windowsIt
windowsItIntegration('restores the complete app directory without touching the database', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-windows-rollback-'))
  cleanupRoots.push(root)
  const installDir = path.join(root, 'XCAGI')
  const backupRoot = path.join(root, 'rollback', 'windows-app-current')
  const appPath = path.join(installDir, 'XCAGI.exe')
  const markerPath = path.join(root, 'rollback-marker.json')
  const appliedPath = path.join(root, 'rollback-applied.json')
  const logPath = path.join(root, 'rollback-helper.log')
  const databasePath = path.join(root, 'data', 'xcagi.db')

  fs.mkdirSync(installDir, { recursive: true })
  fs.mkdirSync(backupRoot, { recursive: true })
  fs.mkdirSync(path.dirname(databasePath), { recursive: true })
  fs.writeFileSync(appPath, 'new-app')
  fs.writeFileSync(path.join(installDir, 'build.txt'), 'new-build')
  fs.writeFileSync(path.join(backupRoot, 'XCAGI.exe'), 'old-app')
  fs.writeFileSync(path.join(backupRoot, 'build.txt'), 'old-build')
  fs.writeFileSync(markerPath, '{}')
  fs.writeFileSync(databasePath, 'new-database')
  fs.writeFileSync(`${databasePath}-wal`, 'new-wal')

  const script = buildWindowsAppSwapScript({
    currentPid: 2_000_000_000,
    installDir,
    backupRoot,
    appPath,
    markerPath,
    appliedPath,
    logPath,
    restartApp: false,
    waitTimeoutSeconds: 5,
    applied: {
      appliedAt: '2026-07-16T00:00:00.000Z',
      reason: 'integration test',
      fromVersion: '1.0.0.0-new',
      toVersion: '1.0.0.0-old',
    },
  })
  const encoded = Buffer.from(script, 'utf16le').toString('base64')
  let executionError = ''
  try {
    await execFileAsync(
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
      { cwd: root, timeout: 45_000 },
    )
  } catch (error) {
    executionError = error instanceof Error ? error.message : String(error)
  }
  const helperLog = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : ''

  expect(fs.readFileSync(appPath, 'utf8'), `${executionError}\n${helperLog}`).toBe('old-app')
  expect(fs.readFileSync(path.join(installDir, 'build.txt'), 'utf8')).toBe('old-build')
  // 数据库与 WAL 不归应用替换脚本处理
  expect(fs.readFileSync(databasePath, 'utf8')).toBe('new-database')
  expect(fs.existsSync(`${databasePath}-wal`)).toBe(true)
  expect(fs.existsSync(markerPath)).toBe(false)
  expect(JSON.parse(fs.readFileSync(appliedPath, 'utf8')).reason).toBe('integration test')
}, 60_000)
