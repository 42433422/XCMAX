import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// vi.hoisted 在 import 之前 mock electron
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
vi.mock('./rollback-windows.js', async importOriginal => {
  const actual = await importOriginal<typeof import('./rollback-windows.js')>()
  return {
    ...actual,
    launchWindowsFullRollback: windowsRollbackMocks.launchWindowsFullRollback
  }
})

// 全局 beforeEach 清理 userData 下的 rollback 文件，避免测试间状态泄漏
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
  let savedResourcesPath: string | undefined

  beforeEach(() => {
    electronMocks.app.isPackaged = true
    tmpResources = path.join(os.tmpdir(), `xcagi-rollback-resources-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    fs.mkdirSync(tmpResources, { recursive: true })
    // 模拟打包后的 backend 目录结构
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(backendDir, exeName), 'fake-binary-content')
    fs.mkdirSync(path.join(backendDir, '_internal'), { recursive: true })
    fs.writeFileSync(path.join(backendDir, '_internal', 'config.json'), '{"k":"v"}')
    const appPath = path.join(tmpResources, 'XCAGI.exe')
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
    } else {
      expect(marker!.backupRelPath).toMatch(/^backend-10\.0\.0$/)
    }

    // 备份目录应存在且包含 backend 可执行文件
    const userData = electronMocks.__userDataDir
    const backupRoot =
      process.platform === 'win32'
        ? path.join(userData, 'rollback', marker!.appBackupRelPath!)
        : path.join(userData, 'rollback', marker!.backupRelPath!)
    expect(fs.existsSync(backupRoot)).toBe(true)
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    const backendBackupRoot =
      process.platform === 'win32' ? path.join(backupRoot, 'backend') : backupRoot
    expect(fs.existsSync(path.join(backendBackupRoot, exeName))).toBe(true)
    expect(fs.existsSync(path.join(backendBackupRoot, '_internal', 'config.json'))).toBe(true)
  })

  it('throws when backend executable missing', async () => {
    // 清空 backend 目录
    const backendDir = path.join(tmpResources, 'backend')
    fs.rmSync(backendDir, { recursive: true, force: true })

    const { prepareRollback } = await import('./rollback.js')
    await expect(prepareRollback('10.0.1')).rejects.toThrow(/找不到当前 backend/)
  })
})

describe('rollback — checkPendingRollback', () => {
  it('returns null when no marker exists', async () => {
    const { checkPendingRollback } = await import('./rollback.js')
    expect(checkPendingRollback()).toBeNull()
  })

  it('returns marker when prepared', async () => {
    const { prepareRollback, checkPendingRollback } = await import('./rollback.js')
    // 先 setup packaged 模式
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-check-${Date.now()}`)
    fs.mkdirSync(path.join(tmpResources, 'backend'), { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(tmpResources, 'backend', exeName), 'fake')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      await prepareRollback('10.0.2')
      const marker = checkPendingRollback()
      expect(marker).not.toBeNull()
      expect(marker!.toVersion).toBe('10.0.2')
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
    }
  })
})

describe('rollback — commitRollback', () => {
  it('deletes marker file', async () => {
    const { prepareRollback, commitRollback, checkPendingRollback } = await import('./rollback.js')
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-commit-${Date.now()}`)
    fs.mkdirSync(path.join(tmpResources, 'backend'), { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(tmpResources, 'backend', exeName), 'fake')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      await prepareRollback('10.0.3')
      expect(checkPendingRollback()).not.toBeNull()
      commitRollback()
      expect(checkPendingRollback()).toBeNull()
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
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

  it('restores backend from backup and writes applied marker', async () => {
    const { prepareRollback, triggerRollback, checkPendingRollback, checkRollbackApplied } = await import('./rollback.js')
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-trigger-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    const exeName = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
    fs.writeFileSync(path.join(backendDir, exeName), 'original-content')
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      // 准备回滚（备份当前版本）
      await prepareRollback('10.0.5')
      const marker = checkPendingRollback()
      expect(marker).not.toBeNull()
      if (process.platform === 'win32') {
        marker!.mode = 'backend'
        marker!.backupRelPath = path.join(marker!.appBackupRelPath!, 'backend')
        delete marker!.appPath
        delete marker!.appBackupRelPath
        fs.writeFileSync(
          path.join(electronMocks.__userDataDir, 'rollback-marker.json'),
          JSON.stringify(marker, null, 2),
          'utf8'
        )
      }

      // 模拟更新后 backend 被替换为损坏版本
      fs.writeFileSync(path.join(backendDir, exeName), 'corrupted-content')

      // 触发回滚
      await triggerRollback('backend health timeout')
      expect(checkPendingRollback()).toBeNull()

      const applied = checkRollbackApplied()
      expect(applied).not.toBeNull()
      expect(applied!.reason).toBe('backend health timeout')
      expect(applied!.fromVersion).toBe('10.0.5')
      expect(applied!.toVersion).toBe('10.0.0')

      // 验证 backend 已还原
      const restored = fs.readFileSync(path.join(backendDir, exeName), 'utf8')
      expect(restored).toBe('original-content')
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
    }
  })
})

describe('rollback — checkRollbackApplied', () => {
  it('returns null when no applied marker', async () => {
    const { checkRollbackApplied } = await import('./rollback.js')
    expect(checkRollbackApplied()).toBeNull()
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
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-full-${Date.now()}`)
    const backendDir = path.join(tmpResources, 'backend')
    fs.mkdirSync(backendDir, { recursive: true })
    fs.writeFileSync(path.join(backendDir, 'xcagi-backend.exe'), 'backend')
    const appPath = path.join(tmpResources, 'XCAGI.exe')
    fs.writeFileSync(appPath, 'app')
    electronMocks.__state.exePath = appPath
    const saved = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      const { prepareRollback, triggerRollback, checkPendingRollback } = await import('./rollback.js')
      await prepareRollback('10.0.6')
      const result = await triggerRollback('window failed')
      expect(result).toEqual({ mode: 'windows-full', scheduled: true })
      expect(windowsRollbackMocks.launchWindowsFullRollback).toHaveBeenCalledOnce()
      expect(checkPendingRollback()).not.toBeNull()
    } finally {
      if (saved === undefined) delete (process as { resourcesPath?: string }).resourcesPath
      else (process as { resourcesPath?: string }).resourcesPath = saved
      electronMocks.app.isPackaged = false
      fs.rmSync(tmpResources, { recursive: true, force: true })
    }
  })
})
