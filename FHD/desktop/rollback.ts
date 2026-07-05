import { app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

/**
 * 自动更新回滚机制
 *
 * 设计：
 * 1. beforeInstall 钩子中（quitAndInstall 之前）调用 prepareRollback()
 *    - 把当前版本号、可执行文件路径、关键资源路径写入 rollback-marker.json
 *    - 在 userData/rollback/ 下备份 backend 可执行文件（PyInstaller 包）
 * 2. 更新后首次启动时，checkPendingRollback() 检测 marker 是否存在
 *    - 如果存在，说明是"更新后首次启动"，进入观察期
 * 3. 启动成功后（后端 health 通过 + 窗口创建成功）调用 commitRollback()
 *    - 删除 marker，保留备份（供下次更新用）
 * 4. 启动失败时（后端 health 超时、createWindow 抛错）调用 triggerRollback()
 *    - 从备份还原 backend 可执行文件
 *    - 写入 rollback-applied.json，下次启动提示用户
 *    - 退出 app，让用户重启
 *
 * 回滚范围：
 * - 只回滚 backend 可执行文件（PyInstaller 包，~80MB）
 * - Electron 壳自身由 electron-updater 管理，回滚由 NSIS/pkg installer 处理
 * - 数据库迁移不可逆，故 runBackendMigration 失败也会触发回滚
 */

const ROLLBACK_DIR = 'rollback'
const ROLLBACK_MARKER = 'rollback-marker.json'
const ROLLBACK_APPLIED = 'rollback-applied.json'
const ROLLBACK_BACKEND_NAME = process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'

export interface RollbackMarker {
  /** 触发回滚准备时的版本号（来自 app.getVersion 或 version.txt） */
  fromVersion: string
  /** 即将安装的新版本号（来自 update-downloaded 事件） */
  toVersion: string
  /** 备份时间戳 ISO */
  preparedAt: string
  /** 打包后的 backend 可执行文件路径（resourcesPath/backend/xcagi-backend[.exe]） */
  backendPath: string
  /** 备份文件在 userData/rollback/ 下的相对路径 */
  backupRelPath: string
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

/**
 * 在 quitAndInstall 之前调用：备份当前 backend 可执行文件，写入 marker。
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

  const fromVersion = app.getVersion() || 'unknown'
  const dir = rollbackDir()
  fs.mkdirSync(dir, { recursive: true })

  // 备份 backend（PyInstaller 包，包含 _internal/）
  const backendDir = path.dirname(backendPath)
  const backupRoot = path.join(dir, `backend-${fromVersion}`)
  // 清理旧备份（只保留最近一份）
  try { fs.rmSync(backupRoot, { recursive: true, force: true }) } catch {}
  fs.mkdirSync(backupRoot, { recursive: true })

  // 复制整个 backend 目录（含 _internal/、product-sku.json 等）
  await copyDirRecursive(backendDir, backupRoot)

  const marker: RollbackMarker = {
    fromVersion,
    toVersion,
    preparedAt: new Date().toISOString(),
    backendPath,
    backupRelPath: path.relative(dir, backupRoot)
  }
  fs.writeFileSync(markerPath(), JSON.stringify(marker, null, 2), 'utf8')

  // 清理旧的 applied 标记
  try { fs.unlinkSync(appliedPath()) } catch {}
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
  // 如果存在 applied 标记，说明上次发生过回滚，可通知用户（这里只清理）
  try { fs.unlinkSync(appliedPath()) } catch {}
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

/**
 * 启动失败时调用：从备份还原 backend，写入 applied 标记，退出 app。
 */
export async function triggerRollback(reason: string): Promise<void> {
  const marker = checkPendingRollback()
  if (!marker) {
    // 无 marker 说明不是更新后首次启动，无法回滚
    return
  }

  const dir = rollbackDir()
  const backupRoot = path.join(dir, marker.backupRelPath)
  if (!fs.existsSync(backupRoot)) {
    throw new Error(`回滚失败：备份目录不存在 ${backupRoot}`)
  }

  // 还原 backend 目录
  const backendDir = path.dirname(marker.backendPath)
  // 先删除当前（失败的）backend 目录
  try { fs.rmSync(backendDir, { recursive: true, force: true }) } catch {}
  fs.mkdirSync(backendDir, { recursive: true })
  await copyDirRecursive(backupRoot, backendDir)

  // 写入 applied 标记
  const applied: RollbackApplied = {
    appliedAt: new Date().toISOString(),
    reason,
    fromVersion: marker.toVersion,
    toVersion: marker.fromVersion
  }
  fs.writeFileSync(appliedPath(), JSON.stringify(applied, null, 2), 'utf8')

  // 删除 marker（已应用回滚）
  try { fs.unlinkSync(markerPath()) } catch {}
}

async function copyDirRecursive(src: string, dest: string): Promise<void> {
  const entries = fs.readdirSync(src, { withFileTypes: true })
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)
    if (entry.isDirectory()) {
      fs.mkdirSync(destPath, { recursive: true })
      await copyDirRecursive(srcPath, destPath)
    } else {
      fs.copyFileSync(srcPath, destPath)
    }
  }
}
