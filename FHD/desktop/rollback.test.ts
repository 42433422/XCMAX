import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const electronMocks = vi.hoisted(() => {
  const nodeOs = require('node:os')
  const nodePath = require('node:path')
  const nodeFs = require('node:fs')
  const tmpDir = nodeOs.tmpdir()
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  const userDataDir = nodePath.join(tmpDir, `xcagi-rollback-test-${stamp}`)
  nodeFs.mkdirSync(userDataDir, { recursive: true })
  const state = {
    exePath: nodePath.join(tmpDir, `xcagi-rollback-app-${stamp}`, 'XCAGI.exe')
  }

  return {
    app: {
      isPackaged: false as boolean,
      getPath: (name: string) => {
        if (name === 'userData') return userDataDir
        if (name === 'exe') return state.exePath
        return nodePath.join(tmpDir, `xcagi-rollback-mock-${name}`)
      },
      getVersion: () => '10.0.0'
    },
    __userDataDir: userDataDir,
    __state: state
  }
})

vi.mock('electron', () => electronMocks)
const windowsRollbackMocks = vi.hoisted(() => ({
  launchWindowsFullRollback: vi.fn(async () => 12345)
}))
const macosRollbackMocks = vi.hoisted(() => ({
  launchMacOSFullRollback: vi.fn(async () => 12345)
}))
vi.mock('./rollback-windows.js', async importOriginal => {
  const actual = await importOriginal<typeof import('./rollback-windows.js')>()
  return {
    ...actual,
    launchWindowsFullRollback: windowsRollbackMocks.launchWindowsFullRollback
  }
})
vi.mock('./rollback-macos.js', async importOriginal => {
  const actual = await importOriginal<typeof import('./rollback-macos.js')>()
  return { ...actual, launchMacOSFullRollback: macosRollbackMocks.launchMacOSFullRollback }
})

function cleanRollbackState() {
  const userData = electronMocks.__userDataDir
  const rollbackDir = path.join(userData, 'rollback')
  try { fs.rmSync(rollbackDir, { recursive: true, force: true }) } catch {}
  try { fs.unlinkSync(path.join(userData, 'rollback-marker.json')) } catch {}
  try { fs.unlinkSync(path.join(userData, 'rollback-applied.json')) } catch {}
}

beforeEach(() => {
  cleanRollbackState()
  vi.resetModules()
})

describe('rollback — prepareRollback', () => {
  let tmpResources: string
  let tmpAppBundle: string
  let savedResourcesPath: string | undefined

  beforeEach(() => {
    electronMocks.app.isPackaged = true
    tmpAppBundle = path.join(os.tmpdir(), `xcagi-rollback-${Date.now()}-${Math.random().toString(36).slice(2)}.app`)
    tmpResources = process.platform === 'darwin' ? path.join(tmpAppBundle, 'Contents', 'Resources') : path.join(tmpAppBundle, 'Resources')
    fs.mkdirSync(tmpResources, { recursive: true })
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(backendDir, exeName), 'fake-binary-content')
    fs.mkdirSync(path.join(backendDir, '_internal'), { recursive: true })
    fs.writeFileSync(path.join(backendDir, '_internal', 'config.json'), '{"k":"v"}')
    const appPath = process.platform === 'darwin'
      ? path.join(tmpAppBundle, 'Contents', 'MacOS', 'XCAGI')
      : path.join(tmpResources, 'XCAGI.exe')
    fs.mkdirSync(path.dirname(appPath), { recursive: true })
    fs.writeFileSync(appPath, 'fake-app')
    electronMocks.__state.exePath = appPath

    savedResourcesPath = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
  })

  afterEach(() => {
    electronMocks.app.isPackaged = false
    if (savedResourcesPath === undefined) {
      delete (process as { resourcesPath?: string }).resourcesPath
    } else {
      (process as { resourcesPath?: string }).resourcesPath = savedResourcesPath
    }
  })

  it('skips prepareRollback in dev mode (not packaged)', async () => {
    electronMocks.app.isPackaged = false
    const { prepareRollback } = await import('./rollback.js')
    await expect(prepareRollback('10.0.1')).resolves.toBeUndefined()
  })

  it('backs up backend dir and writes marker when packaged', async () => {
    const { prepareRollback, checkPendingRollback } = await import('./rollback.js')
    await prepareRollback('10.0.1')
    const marker = checkPendingRollback()
    expect(marker).not.toBeNull()
    expect(marker!.fromVersion).toBe('10.0.0')
    expect(marker!.toVersion).toBe('10.0.1')
    if (process.platform === 'win32') {
      expect(marker!.mode).toBe('windows-full')
      expect(marker!.appBackupRelPath).toBe('windows-app-current')
    } else if (process.platform === 'darwin') {
      expect(marker!.mode).toBe('macos-full')
      expect(marker!.appBackupRelPath).toBe('macos-app-current.app')
    } else {
      expect(marker!.backupRelPath).toMatch(/^backend-10\.0\.0$/)
    }

    const userData = electronMocks.__userDataDir
    const backupRoot =
      process.platform === 'win32'
        ? path.join(userData, 'rollback', marker!.appBackupRelPath!)
        : process.platform === 'darwin'
          ? path.join(userData, 'rollback', marker!.appBackupRelPath!)
        : path.join(userData, 'rollback', marker!.backupRelPath!)
    expect(fs.existsSync(backupRoot)).toBe(true)
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    const backendBackupRoot =
      process.platform === 'win32'
        ? path.join(backupRoot, 'backend')
        : process.platform === 'darwin'
          ? path.join(backupRoot, 'Contents', 'Resources', 'backend')
          : backupRoot
    expect(fs.existsSync(path.join(backendBackupRoot, exeName))).toBe(true)
    expect(fs.existsSync(path.join(backendBackupRoot, '_internal', 'config.json'))).toBe(true)
  })

  it('throws when backend executable missing', async () => {
    const backendDir = path.join(tmpResources, 'backend')
    fs.rmSync(backendDir, { recursive: true, force: true })

    const { prepareRollback } = await import('./rollback.js')
    await expect(prepareRollback('10.0.1')).rejects.toThrow(/找不到当前 backend/)
  })
})

describe('rollback — commitRollback', () => {
  it('deletes marker file', async () => {
    const { prepareRollback, commitRollback, checkPendingRollback } = await import('./rollback.js')
    const cleanup = setupPackagedBackend()
    try {
      await prepareRollback('10.0.3')
      expect(checkPendingRollback()).not.toBeNull()
      commitRollback()
      expect(checkPendingRollback()).toBeNull()
    } finally {
      cleanup()
    }
  })
})

describe('rollback — triggerRollback', () => {
  it('returns silently when no marker (not update first-run)', async () => {
    const { triggerRollback } = await import('./rollback.js')
    await expect(triggerRollback('test reason')).resolves.toEqual({
      mode: 'none',
      scheduled: false
    })
  })

})

describe('rollback — consumeRollbackApplied', () => {
  it('returns the applied record only once', async () => {
    const appliedPath = path.join(electronMocks.__userDataDir, 'rollback-applied.json')
    fs.writeFileSync(
      appliedPath,
      JSON.stringify({
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: 'test',
        fromVersion: 'new',
        toVersion: 'old'
      })
    )
    const { consumeRollbackApplied } = await import('./rollback.js')
    expect(consumeRollbackApplied()?.reason).toBe('test')
    expect(consumeRollbackApplied()).toBeNull()
  })
})

const windowsIt = process.platform === 'win32' ? it : it.skip
describe('rollback — Windows full app restore scheduling', () => {
  windowsIt('launches the external helper and leaves marker consumption to it', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, triggerRollback, checkPendingRollback } = await import('./rollback.js')
      await prepareRollback('10.0.6')
      const result = await triggerRollback('window failed')
      expect(result).toEqual({ mode: 'windows-full', scheduled: true })
      expect(windowsRollbackMocks.launchWindowsFullRollback).toHaveBeenCalledOnce()
      expect(checkPendingRollback()).not.toBeNull()
    } finally {
      cleanup()
    }
  })
})

function setupPackagedBackend(): () => void {
  electronMocks.app.isPackaged = true
  const tmpAppBundle = path.join(
    os.tmpdir(),
    `xcagi-rollback-ext-${Date.now()}-${Math.random().toString(36).slice(2)}.app`,
  )
  const tmpResources = process.platform === 'darwin'
    ? path.join(tmpAppBundle, 'Contents', 'Resources')
    : tmpAppBundle
  const backendDir = path.join(tmpResources, 'backend')
  fs.mkdirSync(backendDir, { recursive: true })
  const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
  fs.writeFileSync(path.join(backendDir, exeName), 'fake-backend')
  const appPath = process.platform === 'darwin'
    ? path.join(tmpAppBundle, 'Contents', 'MacOS', 'XCAGI')
    : path.join(tmpResources, 'XCAGI.exe')
  fs.mkdirSync(path.dirname(appPath), { recursive: true })
  fs.writeFileSync(appPath, 'fake-app')
  electronMocks.__state.exePath = appPath
  const saved = (process as { resourcesPath?: string }).resourcesPath
  ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
  return () => {
    if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
    else (process as { resourcesPath?: string }).resourcesPath = saved
    electronMocks.app.isPackaged = false
    fs.rmSync(tmpAppBundle, { recursive: true, force: true })
  }
}

describe('rollback — attachDatabaseBackupToRollback', () => {
  it('throws when no marker exists', async () => {
    const { attachDatabaseBackupToRollback } = await import('./rollback.js')
    expect(() => attachDatabaseBackupToRollback('/tmp/any.db.bak')).toThrow(/缺少 rollback marker/)
  })

  it('attaches a valid backup inside userData to the marker', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, attachDatabaseBackupToRollback, checkPendingRollback } = await import(
        './rollback.js'
      )
      await prepareRollback('10.1.0')
      const backupPath = path.join(electronMocks.__userDataDir, 'backups', 'pre-migrate.db')
      fs.mkdirSync(path.dirname(backupPath), { recursive: true })
      fs.writeFileSync(backupPath, 'db-snapshot')

      attachDatabaseBackupToRollback(backupPath)
      const marker = checkPendingRollback()
      expect(marker?.databaseBackupPath).toBe(backupPath)
      expect(marker?.databasePath).toBe(path.join(electronMocks.__userDataDir, 'data', 'xcagi.db'))
    } finally {
      cleanup()
    }
  })

  it('rejects outside and missing backups', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, attachDatabaseBackupToRollback } = await import('./rollback.js')
      await prepareRollback('10.1.2')
      expect(() => attachDatabaseBackupToRollback('/tmp/outside.db')).toThrow(/不在 XCAGI 数据目录内/)
      const missing = path.join(electronMocks.__userDataDir, 'backups', 'missing.db')
      expect(() => attachDatabaseBackupToRollback(missing)).toThrow(/数据库备份不存在/)
    } finally {
      cleanup()
    }
  })
})

describe('rollback — cancelPreparedRollback', () => {
  it('removes a prepared marker and is idempotent without one', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const { prepareRollback, cancelPreparedRollback, checkPendingRollback } = await import(
        './rollback.js'
      )
      await prepareRollback('10.2.0')
      expect(checkPendingRollback()).not.toBeNull()
      cancelPreparedRollback()
      expect(checkPendingRollback()).toBeNull()
      expect(() => cancelPreparedRollback()).not.toThrow()
    } finally {
      cleanup()
    }
  })
})

describe('rollback — prepareRollback hygiene and nesting guards', () => {
  it('clears a stale applied marker when preparing a new rollback', async () => {
    const cleanup = setupPackagedBackend()
    try {
      fs.writeFileSync(
        path.join(electronMocks.__userDataDir, 'rollback-applied.json'),
        JSON.stringify({ appliedAt: 'x', reason: 'old', fromVersion: 'a', toVersion: 'b' }),
      )
      const { prepareRollback, checkRollbackApplied } = await import('./rollback.js')
      await prepareRollback('10.3.0')
      expect(checkRollbackApplied()).toBeNull()
    } finally {
      cleanup()
    }
  })

  windowsIt('rejects install directory nested inside the backup root', async () => {
    electronMocks.app.isPackaged = true
    const backupRoot = path.join(electronMocks.__userDataDir, 'rollback', 'windows-app-current')
    const installDir = path.join(backupRoot, 'app')
    fs.mkdirSync(path.join(installDir, 'backend'), { recursive: true })
    fs.writeFileSync(path.join(installDir, 'backend', 'xcagi-backend.exe'), 'fake')
    fs.writeFileSync(path.join(installDir, 'XCAGI.exe'), 'fake-app')
    electronMocks.__state.exePath = path.join(installDir, 'XCAGI.exe')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = installDir
    try {
      const { prepareRollback } = await import('./rollback.js')
      await expect(prepareRollback('10.3.1')).rejects.toThrow(/互相嵌套/)
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
    }
  })

  windowsIt('rejects when the packaged app executable is missing', async () => {
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-noapp-${Date.now()}`)
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    fs.writeFileSync(path.join(backendDir, 'xcagi-backend.exe'), 'fake')
    electronMocks.__state.exePath = path.join(tmpResources, 'missing', 'XCAGI.exe')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      const { prepareRollback } = await import('./rollback.js')
      await expect(prepareRollback('10.3.2')).rejects.toThrow(/找不到当前 XCAGI 可执行文件/)
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
      fs.rmSync(tmpResources, { recursive: true, force: true })
    }
  })
})

describe('rollback — triggerRollback defensive paths', () => {
  function writeMarker(marker: Record<string, unknown>): void {
    fs.writeFileSync(
      path.join(electronMocks.__userDataDir, 'rollback-marker.json'),
      JSON.stringify(marker, null, 2),
      'utf8',
    )
  }

  it('rejects invalid rollback markers', async () => {
    const { triggerRollback } = await import('./rollback.js')
    const cases: Array<[Record<string, unknown>, string, RegExp]> = [
      [{ mode: 'backend', backendPath: '/tmp/xcagi-escape/backend/app', backupRelPath: '../../escape' }, 'escape', /路径越界/],
      [{ mode: 'backend', backendPath: '/tmp/xcagi-missing/backend/app' }, 'missing path', /缺少 backend 备份路径/],
      [{ mode: 'backend', backendPath: '/tmp/xcagi-gone/backend/app', backupRelPath: 'backend-gone' }, 'missing backup', /备份目录不存在/],
      [{ mode: 'windows-full', backendPath: '/tmp/xcagi-win/backend/app.exe', appPath: '/tmp/xcagi-win/app.exe', appBackupRelPath: 'windows-app-current' }, 'windows backup', process.platform === 'win32' ? /完整应用备份目录不存在/ : /缺少 backend 备份路径/],
    ]
    for (const [fields, reason, expected] of cases) {
      writeMarker({ fromVersion: '1.0.0', toVersion: '2.0.0', preparedAt: new Date().toISOString(), ...fields })
      await expect(triggerRollback(reason)).rejects.toThrow(expected)
    }
  })

  it('restores the backend directory including nested files', async () => {
    const cleanup = setupPackagedBackend()
    try {
      const resourcesPath = (process as { resourcesPath?: string }).resourcesPath as string
      const backendDir = path.join(resourcesPath, 'backend')
      const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
      fs.mkdirSync(path.join(backendDir, '_internal'), { recursive: true })
      fs.writeFileSync(path.join(backendDir, '_internal', 'data.txt'), 'original')

      const { prepareRollback, triggerRollback, checkRollbackApplied } = await import('./rollback.js')
      await prepareRollback('10.4.0')
      fs.writeFileSync(path.join(backendDir, exeName), 'broken')
      fs.rmSync(path.join(backendDir, '_internal'), { recursive: true, force: true })

      const result = await triggerRollback('health timeout')
      if (process.platform === 'win32') {
        expect(result).toEqual({ mode: 'windows-full', scheduled: true })
      } else if (process.platform === 'darwin') {
        expect(result).toEqual({ mode: 'macos-full', scheduled: true })
        expect(macosRollbackMocks.launchMacOSFullRollback).toHaveBeenCalled()
      } else {
        expect(result).toEqual({ mode: 'backend', scheduled: false })
        expect(fs.readFileSync(path.join(backendDir, exeName), 'utf8')).toBe('fake-backend')
        expect(fs.readFileSync(path.join(backendDir, '_internal', 'data.txt'), 'utf8')).toBe('original')
        const applied = checkRollbackApplied()
        expect(applied?.fromVersion).toBe('10.4.0')
        expect(applied?.toVersion).toBe('10.0.0')
      }
    } finally {
      cleanup()
    }
  })
})
