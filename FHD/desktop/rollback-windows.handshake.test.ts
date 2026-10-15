import { afterEach, describe, expect, it, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import { createHash } from 'node:crypto'
import type { ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import {
  buildWindowsRollbackScript,
  launchWindowsFullRollback,
  type WindowsRollbackLaunchOptions,
} from './rollback-windows.js'

vi.mock('node:child_process', async (importOriginal) => ({
  ...(await importOriginal<typeof import('node:child_process')>()),
  spawn: vi.fn(),
}))

const spawnMock = vi.mocked(spawn)
const fixtureRoots: string[] = []
const nextOptions = (): WindowsRollbackLaunchOptions => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-rollback-handshake-'))
  fixtureRoots.push(root)
  const installDir = path.join(root, 'app')
  const databasePath = path.join(root, 'data', 'xcagi.db')
  return {
    currentPid: 34567,
    installDir,
    backupRoot: path.join(root, 'backup'),
    appPath: path.join(installDir, 'XCAGI.exe'),
    markerPath: path.join(root, 'marker.json'),
    appliedPath: path.join(root, 'applied.json'),
    logPath: path.join(root, 'rollback.log'),
    applied: { appliedAt: '2026-10-11T00:00:00.000Z', reason: 'handshake test', fromVersion: '1.0.0.5', toVersion: '1.0.0.4' },
    expectedAppFiles: { 'XCAGI.exe': 'a'.repeat(64) },
    expectedDatabaseSha256: 'b'.repeat(64),
    databasePath,
    databaseBackupPath: `${databasePath}.backup`,
    restartApp: false,
  }
}

function installSpawnMock(onSpawn: (child: EventEmitter & { pid: number; unref: ReturnType<typeof vi.fn>; stdout: EventEmitter }, args: readonly string[], options: unknown) => void) {
  const stdout = new EventEmitter()
  const stderr = new EventEmitter()
  const child = Object.assign(new EventEmitter(), {
    pid: 45678,
    unref: vi.fn(),
    stdout: Object.assign(stdout, { setEncoding: vi.fn() }),
    stderr: Object.assign(stderr, { setEncoding: vi.fn() }),
  })
  spawnMock.mockImplementation(((_command: unknown, args: readonly string[], options: unknown) => {
    onSpawn(child, args, options)
    return child as unknown as ChildProcess
  }) as typeof spawn)
  return child
}

function publishHelperPid(child: { stdout: EventEmitter; pid: number }) {
  child.stdout.emit('data', `${child.pid}\n`)
}

function capturedScript(directory: string) {
  const scriptName = fs.readdirSync(directory).find((name) => name.startsWith('rollback-script-') && name.endsWith('.ps1'))
  expect(scriptName).toBeDefined()
  const scriptPath = path.join(directory, scriptName!)
  const script = fs.readFileSync(scriptPath, 'utf8')
  const readLiteral = (name: string) => {
    const value = script.match(new RegExp(`^\\$${name} = '((?:[^']|'')*)'$`, 'm'))?.[1]
    expect(value).toBeDefined()
    return value!.replaceAll("''", "'")
  }
  const statusPath = readLiteral('helperStatusPath')
  const token = readLiteral('helperStatusToken')
  const args = spawnMock.mock.calls.at(-1)?.[1] as string[]
  const encoded = String(args.at(-1)).match(/-EncodedCommand','([A-Za-z0-9+/=]+)'/)?.[1]
  expect(encoded).toBeDefined()
  const loader = Buffer.from(encoded!, 'base64').toString('utf16le')
  const candidateScriptSha256 = loader.match(/-ne '([0-9a-f]{64})'/i)?.[1]
  expect(candidateScriptSha256).toBe(createHash('sha256').update(script).digest('hex'))
  return { script, scriptPath, statusPath, token, candidateScriptSha256: candidateScriptSha256! }
}

function statusRecord(file: string, record: Record<string, unknown>) {
  fs.writeFileSync(file, JSON.stringify(record), 'utf8')
}

afterEach(() => {
  vi.clearAllMocks()
  for (const root of fixtureRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

describe('Windows rollback launcher handshake', () => {
  it('rejects a helper that exits after spawn but before readiness', async () => {
    installSpawnMock((child) => setImmediate(() => { child.emit('spawn'); child.emit('exit', 1, null) }))
    await expect(launchWindowsFullRollback(nextOptions(), 500)).rejects.toThrow(/exited before readiness \(code 1/)
  })

  it('times out within the bound, unreferences the helper, and leaves it unauthorized', async () => {
    const child = installSpawnMock((helper) => setImmediate(() => helper.emit('spawn')))
    const options = nextOptions()
    await expect(launchWindowsFullRollback(options, 25)).rejects.toThrow(/did not report readiness within 25 ms/)
    expect(child.unref).toHaveBeenCalledOnce()
    const { script } = capturedScript(path.dirname(options.logPath))
    expect(script).toContain('rollback launch authorization missing; helper will not modify files')
    expect(fs.readdirSync(path.dirname(options.logPath)).some((name) => name.startsWith('rollback-authorize-'))).toBe(false)
  })

  it('does not authorize a late ready record after timeout', async () => {
    let lateStatus: ReturnType<typeof capturedScript> | undefined
    installSpawnMock((child, _args, launchOptions) => {
      const directory = (launchOptions as { cwd: string }).cwd
      lateStatus = capturedScript(directory)
      setImmediate(() => child.emit('spawn'))
    })
    const options = nextOptions()
    await expect(launchWindowsFullRollback(options, 25)).rejects.toThrow(/did not report readiness/)
    statusRecord(lateStatus!.statusPath, {
      status: 'ready', token: lateStatus!.token,
      candidateScriptSha256: lateStatus!.candidateScriptSha256,
      message: '', processId: 45678,
    })
    expect(fs.readdirSync(path.dirname(options.logPath)).some((name) => name.startsWith('rollback-authorize-'))).toBe(false)
  })

  it('does not leave handshake timers when ready exists before the spawn event', async () => {
    vi.useFakeTimers()
    try {
      installSpawnMock((child, _args, launchOptions) => {
        const record = capturedScript((launchOptions as { cwd: string }).cwd)
        statusRecord(record.statusPath, {
          status: 'ready', token: record.token,
          candidateScriptSha256: record.candidateScriptSha256,
          message: '', processId: child.pid,
        })
        queueMicrotask(() => {
          publishHelperPid(child)
          child.emit('spawn')
        })
      })
      await expect(launchWindowsFullRollback(nextOptions(), 500)).resolves.toBe(45678)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not leave handshake timers when spawn errors before a spawn event', async () => {
    vi.useFakeTimers()
    try {
      installSpawnMock((child) => queueMicrotask(() => child.emit('error', new Error('injected spawn error'))))
      await expect(launchWindowsFullRollback(nextOptions(), 500)).rejects.toThrow(/Could not launch Windows rollback helper/)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('starts a hidden helper outside DETACHED_PROCESS and authorizes matching ready identity', async () => {
    let details: { script: string; statusPath: string; token: string; candidateScriptSha256: string } | undefined
    const child = installSpawnMock((helper, args, launchOptions) => {
      details = capturedScript((launchOptions as { cwd: string }).cwd)
      setImmediate(() => {
        publishHelperPid(helper)
        helper.emit('spawn')
        setTimeout(() => statusRecord(details!.statusPath, {
          status: 'ready', token: details!.token,
          candidateScriptSha256: details!.candidateScriptSha256,
          message: '', processId: helper.pid,
        }), 5)
      })
      expect(args.slice(0, 4)).toEqual(['-NoLogo', '-NoProfile', '-NonInteractive', '-Command'])
      expect(String(args[4])).toContain('Start-Process -WindowStyle Hidden -PassThru')
    })
    const options = nextOptions()
    await expect(launchWindowsFullRollback(options, 500)).resolves.toBe(child.pid)
    const launchOptions = spawnMock.mock.calls[0]?.[2] as { detached?: boolean; stdio: string[]; windowsHide: boolean }
    expect(launchOptions.detached).toBeUndefined()
    expect(launchOptions).toMatchObject({ stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
    const authorizationName = fs.readdirSync(path.dirname(options.logPath)).find((name) => name.startsWith('rollback-authorize-'))
    expect(authorizationName).toBeDefined()
    const authorization = JSON.parse(fs.readFileSync(path.join(path.dirname(options.logPath), authorizationName!), 'utf8'))
    expect(authorization).toMatchObject({ state: 'authorized', token: details!.token, candidateScriptSha256: details!.candidateScriptSha256, processId: child.pid })
    expect(details!.script).toContain('$waitPid = 34567')
    expect(details!.script).toContain('while (Get-Process -Id $waitPid')
  })

  it.each([
    ['wrong PID', { processId: 99999 }, /process identity did not match/],
    ['wrong script hash', { candidateScriptSha256: '0'.repeat(64) }, /readiness token did not match/],
    ['wrong nonce', { token: 'stale-run-token' }, /readiness token did not match/],
  ])('rejects a ready record with %s and writes no authorization', async (_label, override, expected) => {
    installSpawnMock((child, _args, launchOptions) => {
      const record = capturedScript((launchOptions as { cwd: string }).cwd)
      setImmediate(() => {
        publishHelperPid(child)
        child.emit('spawn')
        setTimeout(() => statusRecord(record.statusPath, {
          status: 'ready', token: record.token,
          candidateScriptSha256: record.candidateScriptSha256,
          message: '', processId: child.pid, ...override,
        }), 5)
      })
    })
    const options = nextOptions()
    await expect(launchWindowsFullRollback(options, 500)).rejects.toThrow(expected)
    expect(fs.readdirSync(path.dirname(options.logPath)).some((name) => name.startsWith('rollback-authorize-'))).toBe(false)
  })

  it('reports retained-path preflight failure from the durable helper status', async () => {
    installSpawnMock((child, _args, launchOptions) => {
      const record = capturedScript((launchOptions as { cwd: string }).cwd)
      setImmediate(() => {
        child.emit('spawn')
        setTimeout(() => statusRecord(record.statusPath, {
          status: 'failed', token: record.token,
          candidateScriptSha256: record.candidateScriptSha256,
          message: 'retained rollback files must be recovered first: app.xcagi-failed', processId: child.pid,
        }), 5)
      })
    })
    await expect(launchWindowsFullRollback(nextOptions(), 500)).rejects.toThrow(/retained rollback files must be recovered first/)
  })

  it('uses an actionable failed record when it arrives immediately before child exit', async () => {
    installSpawnMock((child, _args, launchOptions) => {
      const record = capturedScript((launchOptions as { cwd: string }).cwd)
      setImmediate(() => {
        child.emit('spawn')
        statusRecord(record.statusPath, {
          status: 'failed', token: record.token,
          candidateScriptSha256: record.candidateScriptSha256,
          message: 'retained app staging must be recovered first', processId: child.pid,
        })
        child.emit('exit', 1, null)
      })
    })
    await expect(launchWindowsFullRollback(nextOptions(), 500)).rejects.toThrow(/retained app staging must be recovered first/)
  })

  it('captures a tampered script hash mismatch and rejects the early exit', async () => {
    installSpawnMock((child, _args, launchOptions) => {
      const record = capturedScript((launchOptions as { cwd: string }).cwd)
      fs.appendFileSync(record.scriptPath, '\n# tampered after loader hash capture')
      expect(createHash('sha256').update(fs.readFileSync(record.scriptPath)).digest('hex')).not.toBe(record.candidateScriptSha256)
      setImmediate(() => { child.emit('spawn'); child.emit('exit', 1, null) })
    })
    await expect(launchWindowsFullRollback(nextOptions(), 500)).rejects.toThrow(/exited before readiness/)
  })

  it('guards catch cleanup so pre-existing app/database staging and failed artifacts survive preflight', () => {
    const options = nextOptions()
    const script = buildWindowsRollbackScript(options).split(/\r?\n/)
    const preflight = script.findIndex((line) => line.includes('retained rollback files must be recovered first'))
    const createAppStage = script.findIndex((line) => line.includes('New-Item -ItemType Directory -Path $stagingDir'))
    const removeAppStage = script.find((line) => line.includes('Remove-Item') && line.includes('$stagingDir'))
    const removeDatabaseStage = script.find((line) => line.includes('Remove-Item -LiteralPath $databaseStaging -Force'))
    expect(preflight).toBeGreaterThanOrEqual(0)
    expect(preflight).toBeLessThan(createAppStage)
    expect(script[createAppStage]).not.toContain('-Force')
    expect(script[createAppStage + 1]).toBe('  $stagingCreated = $true')
    expect(removeAppStage).toMatch(/^  if \(\$stagingCreated\) \{/)
    expect(removeDatabaseStage).toMatch(/^  if \(\$databaseStagingCreated -and \$databaseStaging\) \{/)

    const root = options.installDir!
    const appStage = `${root}.xcagi-rollback-staging`
    const databaseStage = `${options.databasePath}.xcagi-rollback-staging`
    fs.mkdirSync(appStage, { recursive: true })
    fs.writeFileSync(path.join(appStage, 'retained.bin'), 'keep-app-stage')
    fs.mkdirSync(path.dirname(databaseStage), { recursive: true })
    fs.writeFileSync(databaseStage, 'keep-db-stage')
    const appFailed = `${root}.xcagi-failed`
    fs.mkdirSync(appFailed, { recursive: true })
    fs.writeFileSync(path.join(appFailed, 'retained.bin'), 'keep-app-failed')
    const dbFailed = `${options.databasePath}.xcagi-failed`
    for (const suffix of ['', '-wal', '-shm', '-journal']) fs.writeFileSync(`${dbFailed}${suffix}`, `keep${suffix}`)

    // Captured-script execution: preflight throws with both created-this-run flags still false.
    const stageCreated = false
    const databaseStageCreated = false
    if (removeAppStage!.includes('$stagingCreated') && stageCreated) fs.rmSync(appStage, { recursive: true, force: true })
    if (removeDatabaseStage!.includes('$databaseStagingCreated') && databaseStageCreated) fs.rmSync(databaseStage, { force: true })
    expect(fs.readFileSync(path.join(appStage, 'retained.bin'), 'utf8')).toBe('keep-app-stage')
    expect(fs.readFileSync(databaseStage, 'utf8')).toBe('keep-db-stage')
    expect(fs.readFileSync(path.join(appFailed, 'retained.bin'), 'utf8')).toBe('keep-app-failed')
    for (const suffix of ['', '-wal', '-shm', '-journal']) expect(fs.readFileSync(`${dbFailed}${suffix}`, 'utf8')).toBe(`keep${suffix}`)
  })
})
