import { afterEach, describe, expect, it } from 'vitest'
import { execFile } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import {
  buildWindowsRollbackScript,
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

  windowsIt('restores the complete app directory and pre-migration database', async () => {
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
    fs.writeFileSync(markerPath, '{}')
    fs.writeFileSync(databasePath, 'new-database')
    fs.writeFileSync(`${databasePath}-wal`, 'new-wal')
    fs.writeFileSync(databaseBackupPath, 'old-database')

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
        // Hosted Windows runners occasionally spend more than 20 seconds in
        // Defender while moving the executable-shaped fixture. The helper's
        // own process wait remains capped at five seconds; leave enough room
        // for filesystem scanning without turning a genuine hang into a pass.
        { cwd: dataDir, timeout: 45_000 },
      )
    } catch (error) {
      executionError = error instanceof Error ? error.message : String(error)
    }
    const helperLog = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : ''

    expect(fs.readFileSync(appPath, 'utf8'), `${executionError}\n${helperLog}`).toBe('old-app')
    expect(fs.readFileSync(path.join(installDir, 'build.txt'), 'utf8')).toBe('old-build')
    expect(fs.readFileSync(databasePath, 'utf8')).toBe('old-database')
    expect(fs.existsSync(`${databasePath}-wal`)).toBe(false)
    expect(fs.existsSync(markerPath)).toBe(false)
    expect(JSON.parse(fs.readFileSync(appliedPath, 'utf8')).reason).toBe('integration test')
  }, 60_000)
})
