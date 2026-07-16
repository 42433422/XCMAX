import { app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import {
  launchWindowsFullRollback,
  type WindowsRollbackAppliedRecord,
} from './rollback-windows.js'

/**
 * 自动更新回滚机制
 *
 * 设计：
 * 1. beforeInstall 钩子中（quitAndInstall 之前）调用 prepareRollback()
 *    - 把当前版本号、可执行文件路径、关键资源路径写入 rollback-marker.json
 *    - Windows 在 userData/rollback/ 下备份完整安装目录
 *    - 其他平台保留 backend 目录备份
 * 2. 更新后首次启动时，checkPendingRollback() 检测 marker 是否存在
 *    - 如果存在，说明是"更新后首次启动"，进入观察期
 * 3. 启动成功后（后端 health 通过 + 窗口创建成功）调用 commitRollback()
 *    - 删除 marker，保留备份（供下次更新用）
 * 4. 启动失败时（后端 health 超时、createWindow 抛错）调用 triggerRollback()
 *    - Windows 由安装目录外的 PowerShell helper 在进程退出后恢复完整应用
 *    - 其他平台从备份还原 backend 可执行文件
 *    - 如迁移前生成了数据库备份，Windows 同时恢复数据库
 *    - 写入 rollback-applied.json，下次启动提示用户
 *    - 退出 app，让用户重启
 *
 * 安全边界：
 * - Windows 的更新准备必须成功备份完整安装目录，否则阻断 quitAndInstall
 * - 数据库迁移前备份失败时同样阻断更新
 * - 回滚 helper 使用同盘 staging + rename，并在替换失败时恢复新版本目录
 * - 非 Windows 平台仍是 backend-only，不能宣称完整应用回滚
 */

const ROLLBACK_DIR = 'rollback'
const ROLLBACK_MARKER = 'rollback-marker.json'
const ROLLBACK_APPLIED = 'rollback-applied.json'
const ROLLBACK_BACKEND_NAME = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'

export interface RollbackMarker {
  mode?: 'backend' | 'windows-full'
  /** 触发回滚准备时的版本号（来自 app.getVersion 或 version.txt） */
  fromVersion: string
  /** 即将安装的新版本号（来自 update-downloaded 事件） */
  toVersion: string
  /** 备份时间戳 ISO */
  preparedAt: string
  /** 打包后的 backend 可执行文件路径（resourcesPath/backend/xcagi-backend[.exe]） */
  backendPath: string
  /** 备份文件在 userData/rollback/ 下的相对路径 */
  backupRelPath?: string
  /** Windows 完整安装目录中的主可执行文件 */
  appPath?: string
  /** Windows 完整安装目录备份在 rollback/ 下的相对路径 */
  appBackupRelPath?: string
  /** 迁移前 SQLite 备份及其恢复目标 */
  databaseBackupPath?: string
  databasePath?: string
}

export interface RollbackApplied {
  /** 回滚发生时间 */
  appliedAt: string
  /** 回滚原因 */
  reason: string
  /** 从哪个版本回滚到哪个版本 */
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

function replaceDirectoryFromStaging(source: string, destination: string): void {
  const staging = `${destination}.tmp-${process.pid}-${Date.now()}`
  const failed = `${destination}.failed-${process.pid}-${Date.now()}`
  try {
    fs.rmSync(staging, { recursive: true, force: true })
    fs.rmSync(failed, { recursive: true, force: true })
    fs.cpSync(source, staging, { recursive: true, force: true })
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

/** 解析打包后的 backend 可执行文件路径（与 main.ts findPackagedBackendExecutable 一致） */
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

/**
 * 在 quitAndInstall 之前调用：Windows 备份完整安装目录，其他平台备份 backend，
 * 然后写入 marker。
 * 如果备份失败，抛出错误（应阻止更新继续）。
 */
export async function prepareRollback(toVersion: string): Promise<void> {
  if (!app.isPackaged) {
    // dev 模式无需回滚（无打包产物）
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

  // 清理旧的 applied 标记
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

/**
 * 启动时检查是否有 pending rollback marker。
 * 返回 marker 表示处于"更新后首次启动观察期"。
 */
export function checkPendingRollback(): RollbackMarker | null {
  try {
    const raw = fs.readFileSync(markerPath(), 'utf8')
    return JSON.parse(raw) as RollbackMarker
  } catch {
    return null
  }
}

/**
 * 启动成功后调用：删除 marker，保留备份（下次更新覆盖）。
 * 同时清理旧的 rollback-applied 标记（如果存在，提示用户已恢复）。
 */
export function commitRollback(): void {
  try { fs.unlinkSync(markerPath()) } catch {}
}

/**
 * 检查上次启动是否触发过回滚（用于 UI 提示）。
 */
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
  mode: 'none' | 'backend' | 'windows-full'
  scheduled: boolean
}

/**
 * 启动失败时调用：从备份还原 backend，写入 applied 标记，退出 app。
 */
export async function triggerRollback(reason: string): Promise<RollbackTriggerResult> {
  const marker = checkPendingRollback()
  if (!marker) {
    // 无 marker 说明不是更新后首次启动，无法回滚
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

  if (!marker.backupRelPath) {
    throw new Error('回滚失败：marker 缺少 backend 备份路径')
  }
  const backupRoot = resolveInside(dir, marker.backupRelPath)
  if (!fs.existsSync(backupRoot)) {
    throw new Error(`回滚失败：备份目录不存在 ${backupRoot}`)
  }

  // 还原 backend 目录
  const backendDir = path.dirname(marker.backendPath)
  replaceDirectoryFromStaging(backupRoot, backendDir)

  fs.writeFileSync(appliedPath(), JSON.stringify(applied, null, 2), 'utf8')

  // 删除 marker（已应用回滚）
  try { fs.unlinkSync(markerPath()) } catch {}
  return { mode: 'backend', scheduled: false }
}
