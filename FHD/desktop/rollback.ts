import { app } from 'electron'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import {
  launchWindowsFullRollback,
  type WindowsRollbackAppliedRecord,
} from './rollback-windows.js'
import { launchMacOSFullRollback } from './rollback-macos.js'

/** Snapshot the prior app and database, then commit only after startup stabilizes. */

const ROLLBACK_DIR = 'rollback'
const ROLLBACK_MARKER = 'rollback-marker.json'
const ROLLBACK_APPLIED = 'rollback-applied.json'

export interface RollbackMarker {
  mode?: 'backend' | 'windows-full' | 'macos-full'
  fromVersion: string
  toVersion: string
  preparedAt: string
  backendPath: string
  backupRelPath?: string
  appPath?: string
  appBackupRelPath?: string
  appBundlePath?: string
  databaseBackupPath?: string
  databasePath?: string
}

export interface RollbackApplied {
  appliedAt: string
  reason: string
  fromVersion: string
  toVersion: string
}

function rollbackDir(): string {
  return path.join(app.getPath('userData'), ROLLBACK_DIR)
}

function markerPath(): string {
  return path.join(app.getPath('userData'), ROLLBACK_MARKER)
}

function appliedPath(): string {
  return path.join(app.getPath('userData'), ROLLBACK_APPLIED)
}

function helperLogPath(): string {
  return path.join(rollbackDir(), 'rollback-helper.log')
}

function resolveInside(root: string, relativePath: string): string {
  const resolvedRoot = path.resolve(root)
  const resolved = path.resolve(resolvedRoot, relativePath)
  if (resolved !== resolvedRoot && !resolved.startsWith(`${resolvedRoot}${path.sep}`)) {
    throw new Error(`回滚路径越界：${relativePath}`)
  }
  return resolved
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

function replaceDirectoryFromStaging(source: string, destination: string, appBundle = false): void {
  const staging = `${destination}.tmp-${process.pid}-${Date.now()}`
  const failed = `${destination}.failed-${process.pid}-${Date.now()}`
  try {
    fs.rmSync(staging, { recursive: true, force: true })
    fs.rmSync(failed, { recursive: true, force: true })
    if (appBundle) execFileSync('/usr/bin/ditto', [source, staging], { stdio: 'ignore' })
    else fs.cpSync(source, staging, { recursive: true, force: true })
    if (fs.existsSync(destination)) {
      fs.renameSync(destination, failed)
    }
    try {
      fs.renameSync(staging, destination)
    } catch (error) {
      if (!fs.existsSync(destination) && fs.existsSync(failed)) {
        fs.renameSync(failed, destination)
      }
      throw error
    }
    fs.rmSync(failed, { recursive: true, force: true })
  } catch (error) {
    fs.rmSync(staging, { recursive: true, force: true })
    if (!fs.existsSync(destination) && fs.existsSync(failed)) {
      try { fs.renameSync(failed, destination) } catch {}
    }
    throw error
  }
}

export function resolvePackagedBackendPath(): string {
  if (!app.isPackaged) return ''
  const backendDir = path.join(process.resourcesPath, 'backend')
  const exe = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'
  const candidates = [
    path.join(backendDir, exe),
    path.join(backendDir, 'xcagi-backend', exe),
    path.join(backendDir, '_internal', exe)
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  return candidates[0]
}

export function resolvePackagedAppPath(): string {
  if (!app.isPackaged) return ''
  return app.getPath('exe')
}

function resolveMacOSAppBundlePath(appPath: string): string {
  let current = path.resolve(appPath)
  while (current !== path.dirname(current)) {
    if (current.endsWith('.app')) return current
    current = path.dirname(current)
  }
  throw new Error(`回滚备份失败：可执行文件不在 .app 包内 ${appPath}`)
}

function currentVersionIdentity(): string {
  const version = app.getVersion() || 'unknown'
  if (!app.isPackaged) return version
  for (const candidate of [
    path.join(process.resourcesPath, 'build-info.json'),
    path.join(process.resourcesPath, 'backend', 'build-info.json'),
  ]) {
    try {
      if (!fs.existsSync(candidate)) continue
      const parsed = JSON.parse(fs.readFileSync(candidate, 'utf8')) as {
        gitSha?: string
        buildSha?: string
      }
      const sha = String(parsed.gitSha || parsed.buildSha || '').trim()
      if (sha) return `${version}+${sha.slice(0, 12)}`
    } catch {
      /* try next build identity source */
    }
  }
  return version
}

/** Back up the current packaged app before electron-updater replaces it. */
export async function prepareRollback(toVersion: string): Promise<void> {
  if (!app.isPackaged) {
    return
  }
  const backendPath = resolvePackagedBackendPath()
  if (!backendPath || !fs.existsSync(backendPath)) {
    throw new Error(`回滚备份失败：找不到当前 backend 可执行文件 ${backendPath}`)
  }

  const fromVersion = currentVersionIdentity()
  const dir = rollbackDir()
  fs.mkdirSync(dir, { recursive: true })

  let marker: RollbackMarker
  if (process.platform === 'win32') {
    const appPath = resolvePackagedAppPath()
    if (!appPath || !fs.existsSync(appPath)) {
      throw new Error(`回滚备份失败：找不到当前 XCAGI 可执行文件 ${appPath}`)
    }
    const installDir = path.dirname(appPath)
    const appBackupRoot = path.join(dir, 'windows-app-current')
    if (
      isPathInside(installDir, appBackupRoot) ||
      isPathInside(appBackupRoot, installDir)
    ) {
      throw new Error(
        `回滚备份失败：安装目录与备份目录不能互相嵌套（install=${installDir}, backup=${appBackupRoot}）`,
      )
    }
    replaceDirectoryFromStaging(installDir, appBackupRoot)
    marker = {
      mode: 'windows-full',
      fromVersion,
      toVersion,
      preparedAt: new Date().toISOString(),
      backendPath,
      appPath,
      appBackupRelPath: path.relative(dir, appBackupRoot),
    }
  } else if (process.platform === 'darwin') {
    const appPath = resolvePackagedAppPath()
    if (!appPath || !fs.existsSync(appPath)) {
      throw new Error(`回滚备份失败：找不到当前 XCAGI 可执行文件 ${appPath}`)
    }
    const appBundlePath = resolveMacOSAppBundlePath(appPath)
    const appBackupRoot = path.join(dir, 'macos-app-current.app')
    if (isPathInside(appBundlePath, appBackupRoot) || isPathInside(appBackupRoot, appBundlePath)) {
      throw new Error(`回滚备份失败：应用包与备份目录不能互相嵌套（app=${appBundlePath}, backup=${appBackupRoot}）`)
    }
    replaceDirectoryFromStaging(appBundlePath, appBackupRoot, true)
    marker = {
      mode: 'macos-full',
      fromVersion,
      toVersion,
      preparedAt: new Date().toISOString(),
      backendPath,
      appPath,
      appBundlePath,
      appBackupRelPath: path.relative(dir, appBackupRoot),
    }
  } else {
    const backendDir = path.dirname(backendPath)
    const backupRoot = path.join(dir, `backend-${fromVersion}`)
    replaceDirectoryFromStaging(backendDir, backupRoot)
    marker = {
      mode: 'backend',
      fromVersion,
      toVersion,
      preparedAt: new Date().toISOString(),
      backendPath,
      backupRelPath: path.relative(dir, backupRoot),
    }
  }
  fs.writeFileSync(markerPath(), JSON.stringify(marker, null, 2), 'utf8')

  try { fs.unlinkSync(appliedPath()) } catch {}
}

export function attachDatabaseBackupToRollback(databaseBackupPath: string): void {
  if (!databaseBackupPath) return
  const marker = checkPendingRollback()
  if (!marker) {
    throw new Error('无法关联数据库备份：缺少 rollback marker')
  }
  const userData = path.resolve(app.getPath('userData'))
  const resolvedBackup = path.resolve(databaseBackupPath)
  if (!isPathInside(userData, resolvedBackup)) {
    throw new Error(`数据库备份不在 XCAGI 数据目录内：${databaseBackupPath}`)
  }
  if (!fs.existsSync(resolvedBackup)) {
    throw new Error(`数据库备份不存在：${databaseBackupPath}`)
  }
  marker.databaseBackupPath = resolvedBackup
  marker.databasePath = path.join(userData, 'data', 'xcagi.db')
  fs.writeFileSync(markerPath(), JSON.stringify(marker, null, 2), 'utf8')
}

export function cancelPreparedRollback(): void {
  try { fs.unlinkSync(markerPath()) } catch {}
}

export function checkPendingRollback(): RollbackMarker | null {
  try {
    const raw = fs.readFileSync(markerPath(), 'utf8')
    return JSON.parse(raw) as RollbackMarker
  } catch {
    return null
  }
}

export function commitRollback(): void {
  try { fs.unlinkSync(markerPath()) } catch {}
}

export function checkRollbackApplied(): RollbackApplied | null {
  try {
    const raw = fs.readFileSync(appliedPath(), 'utf8')
    return JSON.parse(raw) as RollbackApplied
  } catch {
    return null
  }
}

export function consumeRollbackApplied(): RollbackApplied | null {
  const applied = checkRollbackApplied()
  if (applied) {
    try { fs.unlinkSync(appliedPath()) } catch {}
  }
  return applied
}

export interface RollbackTriggerResult {
  mode: 'none' | 'backend' | 'windows-full' | 'macos-full'
  scheduled: boolean
}

/** Restore the prior release after an unsuccessful post-update startup. */
export async function triggerRollback(reason: string): Promise<RollbackTriggerResult> {
  const marker = checkPendingRollback()
  if (!marker) {
    return { mode: 'none', scheduled: false }
  }

  const dir = rollbackDir()
  const applied: RollbackApplied & WindowsRollbackAppliedRecord = {
    appliedAt: new Date().toISOString(),
    reason,
    fromVersion: marker.toVersion,
    toVersion: marker.fromVersion
  }

  if (
    process.platform === 'win32' &&
    marker.mode === 'windows-full' &&
    marker.appPath &&
    marker.appBackupRelPath
  ) {
    const backupRoot = resolveInside(dir, marker.appBackupRelPath)
    if (!fs.existsSync(backupRoot)) {
      throw new Error(`回滚失败：完整应用备份目录不存在 ${backupRoot}`)
    }
    const options = {
      currentPid: process.pid,
      installDir: path.dirname(marker.appPath),
      backupRoot,
      appPath: marker.appPath,
      markerPath: markerPath(),
      appliedPath: appliedPath(),
      logPath: helperLogPath(),
      applied,
      ...(marker.databasePath && marker.databaseBackupPath
        ? {
            databasePath: marker.databasePath,
            databaseBackupPath: marker.databaseBackupPath,
          }
        : {}),
    }
    await launchWindowsFullRollback(options)
    return { mode: 'windows-full', scheduled: true }
  }

  if (process.platform === 'darwin' && marker.mode === 'macos-full' && marker.appBundlePath && marker.appBackupRelPath) {
    const backupRoot = resolveInside(dir, marker.appBackupRelPath)
    if (!fs.existsSync(backupRoot)) throw new Error(`回滚失败：完整应用备份目录不存在 ${backupRoot}`)
    await launchMacOSFullRollback({
      currentPid: process.pid,
      appPath: marker.appBundlePath,
      backupRoot,
      markerPath: markerPath(),
      appliedPath: appliedPath(),
      logPath: helperLogPath(),
      applied,
      ...(marker.databasePath && marker.databaseBackupPath
        ? { databasePath: marker.databasePath, databaseBackupPath: marker.databaseBackupPath }
        : {}),
    })
    return { mode: 'macos-full', scheduled: true }
  }

  if (!marker.backupRelPath) {
    throw new Error('回滚失败：marker 缺少 backend 备份路径')
  }
  const backupRoot = resolveInside(dir, marker.backupRelPath)
  if (!fs.existsSync(backupRoot)) {
    throw new Error(`回滚失败：备份目录不存在 ${backupRoot}`)
  }

  const backendDir = path.dirname(marker.backendPath)
  replaceDirectoryFromStaging(backupRoot, backendDir)

  fs.writeFileSync(appliedPath(), JSON.stringify(applied, null, 2), 'utf8')

  try { fs.unlinkSync(markerPath()) } catch {}
  return { mode: 'backend', scheduled: false }
}
