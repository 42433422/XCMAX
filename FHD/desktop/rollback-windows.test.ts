import { afterEach, describe, expect, it } from 'vitest'
import { execFile } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import { createHash } from 'node:crypto'
import {
  buildWindowsRollbackScript,
  buildWindowsRollbackFileLoader,
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

describe('Windows full application rollback helper', () => {
  windowsIt.each([false, true])('checks the private script checksum before execution (tampered=%s)', async (tampered) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "xcagi-loader-'")); cleanupRoots.push(root)
    const scriptPath = path.join(root, 'restore.ps1'), receipt = path.join(root, 'executed.txt')
    const script = `[IO.File]::WriteAllText('${receipt.replaceAll("'", "''")}', 'executed')`
    const digest = createHash('sha256').update(script).digest('hex')
    fs.writeFileSync(scriptPath, tampered ? script + '\n# changed' : script)
    const encoded = Buffer.from(buildWindowsRollbackFileLoader(scriptPath, digest), 'utf16le').toString('base64')
    expect(encoded.length).toBeLessThan(32767)
    let rejected = false
    try { await execFileAsync('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { timeout: 10000 }) } catch { rejected = true }
    expect(rejected).toBe(tampered); expect(fs.existsSync(receipt)).toBe(!tampered)
  })
  it('encodes paths and the applied record without interpolating raw JSON', () => {
    const options: WindowsRollbackLaunchOptions = {
      currentPid: 42,
      installDir: "C:\\Users\\O'Brien\\XCAGI",
      backupRoot: 'C:\\rollback\\app',
      appPath: "C:\\Users\\O'Brien\\XCAGI\\XCAGI.exe",
      markerPath: 'C:\\data\\rollback-marker.json',
      appliedPath: 'C:\\data\\rollback-applied.json',
      logPath: 'C:\\data\\rollback.log',
      applied: {
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: "window couldn't start",
        fromVersion: '1.0.0.0',
        toVersion: '1.0.0.0',
      },
    }
    const script = buildWindowsRollbackScript(options)
    expect(script).toContain("'C:\\Users\\O''Brien\\XCAGI'")
    expect(script).toContain('FromBase64String')
    expect(script).not.toContain("window couldn't start")
    expect(script).toContain('Move-Item -LiteralPath $stagingDir -Destination $installDir')
  })

  windowsIt.each(['success', 'receipt-failure', 'marker-failure', 'retained-failure', 'retained-wal', 'retained-journal'])('keeps app and database consistent after %s', async (scenario) => {
    const failed = scenario !== 'success'
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-windows-rollback-'))
    cleanupRoots.push(root)
    const installDir = path.join(root, 'XCAGI')
    const backupRoot = path.join(root, 'rollback', 'windows-app-current')
    const dataDir = path.join(root, 'data')
    const appPath = path.join(installDir, 'XCAGI.exe')
    const markerPath = path.join(dataDir, 'rollback-marker.json')
    const appliedPath = path.join(dataDir, 'rollback-applied.json')
    const logPath = path.join(dataDir, 'rollback-helper.log')
    const databasePath = path.join(dataDir, 'data', 'xcagi.db')
    const databaseBackupPath = path.join(dataDir, 'backups', 'pre-migration.db')

    fs.mkdirSync(installDir, { recursive: true })
    fs.mkdirSync(backupRoot, { recursive: true })
    fs.mkdirSync(path.dirname(databasePath), { recursive: true })
    fs.mkdirSync(path.dirname(databaseBackupPath), { recursive: true })
    fs.writeFileSync(appPath, 'new-app')
    fs.writeFileSync(path.join(installDir, 'build.txt'), 'new-build')
    fs.writeFileSync(path.join(backupRoot, 'XCAGI.exe'), 'old-app')
    fs.writeFileSync(path.join(backupRoot, 'build.txt'), 'old-build')
    if (scenario === 'marker-failure') fs.mkdirSync(markerPath)
    fs.writeFileSync(scenario === 'marker-failure' ? path.join(markerPath, 'retained') : markerPath, '{}')
    fs.writeFileSync(databasePath, 'new-database')
    fs.writeFileSync(`${databasePath}-wal`, 'new-wal')
    fs.writeFileSync(`${databasePath}-shm`, 'new-shm')
    fs.writeFileSync(databaseBackupPath, 'old-database')
    if (scenario === 'receipt-failure') fs.mkdirSync(appliedPath)
    const retained = path.join(`${installDir}.xcagi-failed`, 'XCAGI.exe')
    if (scenario === 'retained-failure') { fs.mkdirSync(path.dirname(retained)); fs.writeFileSync(retained, 'prior-failure') }
    if (scenario === 'retained-wal') fs.writeFileSync(`${databasePath}.xcagi-failed-wal`, 'prior-wal')
    if (scenario === 'retained-journal') fs.writeFileSync(`${databasePath}.xcagi-failed-journal`, 'prior-journal')

    const options: WindowsRollbackLaunchOptions = {
      currentPid: 2_000_000_000,
      installDir,
      backupRoot,
      appPath,
      markerPath,
      appliedPath,
      logPath,
      databasePath,
      databaseBackupPath,
      restartApp: false,
      waitTimeoutSeconds: 5,
      applied: {
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: 'integration test',
        fromVersion: '1.0.0.0-new',
        toVersion: '1.0.0.0-old',
      },
    }
    const script = buildWindowsRollbackScript(options)
    const scriptPath = path.join(dataDir, 'rollback-helper-test.ps1')
    fs.writeFileSync(scriptPath, script, 'utf8')
    const scriptSha256 = createHash('sha256').update(script).digest('hex')
    const loader = buildWindowsRollbackFileLoader(scriptPath, scriptSha256)
    const encoded = Buffer.from(loader, 'utf16le').toString('base64')
    expect(encoded.length).toBeLessThan(32767)
    let executionError = ''
    try {
      await execFileAsync(
        'powershell.exe',
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-EncodedCommand',
          encoded,
        ],
        // Allow executable fixture scanning; the helper process wait stays capped at five seconds.
        { cwd: dataDir, timeout: 45_000 },
      )
    } catch (error) {
      executionError = error instanceof Error ? error.message : String(error)
    }
    const helperLog = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : ''

    expect(fs.readFileSync(appPath, 'utf8'), `${executionError}\n${helperLog}`).toBe(failed ? 'new-app' : 'old-app')
    expect(fs.readFileSync(path.join(installDir, 'build.txt'), 'utf8')).toBe(failed ? 'new-build' : 'old-build')
    expect(fs.readFileSync(databasePath, 'utf8')).toBe(failed ? 'new-database' : 'old-database')
    expect(fs.existsSync(markerPath)).toBe(failed)
    for (const [suffix, value] of [['wal', 'new-wal'], ['shm', 'new-shm']]) {
      expect(fs.existsSync(`${databasePath}-${suffix}`)).toBe(failed)
      if (failed) expect(fs.readFileSync(`${databasePath}-${suffix}`, 'utf8')).toBe(value)
    }
    if (failed) expect(executionError).not.toBe('')
    else expect(JSON.parse(fs.readFileSync(appliedPath, 'utf8')).reason).toBe('integration test')
    if (scenario === 'marker-failure') expect(fs.existsSync(appliedPath)).toBe(false)
    if (scenario === 'retained-failure') expect(fs.readFileSync(retained, 'utf8')).toBe('prior-failure')
    if (scenario === 'retained-wal') expect(fs.readFileSync(`${databasePath}.xcagi-failed-wal`, 'utf8')).toBe('prior-wal')
    if (scenario === 'retained-journal') expect(fs.readFileSync(`${databasePath}.xcagi-failed-journal`, 'utf8')).toBe('prior-journal')
  }, 60_000)
})
