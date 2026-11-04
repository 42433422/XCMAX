import { app } from 'electron'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import {
  launchWindowsFullRollback,
  type WindowsRollbackAppliedRecord,
} from './rollback-windows.js'
import { launchMacOSFullRollback } from './rollback-macos.js'
import { promoteLegacyMacRollback } from './legacy-macos-recovery.js'
import { assertLedgerOutsideRollbackTarget, modelUsageLedgerPath } from './model-usage-rollback.js'

const ROLLBACK_DIR = 'rollback'
const ROLLBACK_MARKER = 'rollback-marker.json'
const ROLLBACK_APPLIED = 'rollback-applied.json'
let preservePreparedRollback = false

export interface RollbackMarker {
  operationId?: string
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
  expectedAppFiles?: Record<string, string>
  expectedDatabaseSha256?: string
  databaseOriginallyAbsent?: boolean
  ownedUserDataRoot?: string
  ownedBackupRoot?: string
  expectedOwnedFiles?: Record<string, string>
  expectedOwnedDirectories?: string[]
  recoveryRequired?: boolean
}

export interface RollbackApplied {
  operationId?: string
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

function validateOwnedRollbackMarker(marker: RollbackMarker, rollbackRoot: string): void {
  if (!marker.ownedUserDataRoot && !marker.ownedBackupRoot && !marker.expectedOwnedFiles && !marker.expectedOwnedDirectories) return
  const userData = path.resolve(app.getPath('userData'))
  if (path.resolve(marker.ownedUserDataRoot || '') !== userData || !marker.ownedBackupRoot || !marker.expectedOwnedFiles || !marker.expectedOwnedDirectories) {
    throw new Error('Windows Mod/数据库恢复记录不完整或用户数据根目录不匹配。')
  }
  const backupRoot = path.resolve(marker.ownedBackupRoot)
  if (!isPathInside(rollbackRoot, backupRoot) || backupRoot === path.resolve(rollbackRoot)) {
    throw new Error('Windows Mod/数据库备份目录越出回滚目录。')
  }
  const backupRootInfo = fs.lstatSync(backupRoot)
  if (!backupRootInfo.isDirectory() || backupRootInfo.isSymbolicLink()) {
    throw new Error('Windows Mod/数据库备份根必须是普通目录。')
  }
  const dbName = /^(products|inventory|voice_learning|error_collection)(__[a-z0-9_-]+)?\.db(?:-(?:wal|shm|journal))?$/i
  const dataDbName = /^.+\.db(?:-(?:wal|shm|journal))?$/i
  for (const [relative, expectedHash] of Object.entries(marker.expectedOwnedFiles)) {
    const pieces = relative.split(/[\\/]/)
    const modPath = pieces[0]?.toLowerCase() === 'mods' && pieces.length >= 2
    const allowed = modPath
      || pieces.length === 1 && dbName.test(pieces[0] || '')
      || pieces[0]?.toLowerCase() === 'data' && (pieces.length === 2 && dataDbName.test(pieces[1] || '') && !/^xcagi\.db(?:-(?:wal|shm|journal))?$/i.test(pieces[1] || '') || pieces[1]?.toLowerCase() === 'mod_dbs' && pieces.length >= 3 && dataDbName.test(pieces[pieces.length - 1] || ''))
    if (!allowed || pieces.some(piece => !piece || piece === '.' || piece === '..') || !/^[0-9a-f]{64}$/i.test(expectedHash)) {
      throw new Error(`Windows Mod/数据库恢复记录路径或哈希无效：${relative}`)
    }
    const backupFile = resolveInside(backupRoot, relative)
    if (!isPathInside(backupRoot, backupFile) || !fs.existsSync(backupFile) || !fs.lstatSync(backupFile).isFile() || fs.lstatSync(backupFile).isSymbolicLink()) {
      throw new Error(`Windows Mod/数据库备份文件缺失或链接无效：${relative}`)
    }
    const digest = hashFileSync(backupFile)
    if (digest !== expectedHash.toLowerCase()) throw new Error(`Windows Mod/数据库备份校验失败：${relative}`)
  }
  for (const relative of marker.expectedOwnedDirectories) {
    const pieces = relative.split(/[\\/]/)
    const allowed = pieces[0]?.toLowerCase() === 'mods' && pieces.length >= 1
      || pieces[0]?.toLowerCase() === 'data' && (pieces.length === 1 || pieces[1]?.toLowerCase() === 'mod_dbs')
    if (!allowed || pieces.some(piece => !piece || piece === '.' || piece === '..')) {
      throw new Error(`Windows Mod/数据库恢复记录目录无效：${relative}`)
    }
    const directory = resolveInside(backupRoot, relative)
    if (!isPathInside(backupRoot, directory) || !fs.existsSync(directory) || !fs.lstatSync(directory).isDirectory() || fs.lstatSync(directory).isSymbolicLink()) {
      throw new Error(`Windows Mod/数据库备份目录缺失或链接无效：${relative}`)
    }
  }
}

function isOwnedModPath(relative: string, directory: boolean): boolean {
  const pieces = relative.split(/[\\/]/)
  return pieces[0]?.toLowerCase() === 'mods'
    && pieces.length >= (directory ? 1 : 2)
    && pieces.every(piece => Boolean(piece) && piece !== '.' && piece !== '..')
}

function isOwnedDatabasePath(relative: string): boolean {
  const pieces = relative.split(/[\\/]/)
  const dbName = /^.+\.db(?:-(?:wal|shm|journal))?$/i
  if (pieces.length === 1) return /^(products|inventory|voice_learning|error_collection)(__[a-z0-9_-]+)?\.db(?:-(?:wal|shm|journal))?$/i.test(pieces[0] || '')
  if (pieces[0]?.toLowerCase() !== 'data') return false
  if (pieces.length === 2) return dbName.test(pieces[1] || '') && !/^xcagi\.db(?:-(?:wal|shm|journal))?$/i.test(pieces[1] || '')
  return pieces[1]?.toLowerCase() === 'mod_dbs' && dbName.test(pieces[pieces.length - 1] || '')
}

function hashFileSync(file: string): string {
  const descriptor = fs.openSync(file, 'r')
  const hash = createHash('sha256')
  const buffer = Buffer.allocUnsafe(1024 * 1024)
  try {
    let bytesRead: number
    do {
      bytesRead = fs.readSync(descriptor, buffer, 0, buffer.length, null)
      if (bytesRead > 0) hash.update(buffer.subarray(0, bytesRead))
    } while (bytesRead > 0)
    return hash.digest('hex')
  } finally {
    fs.closeSync(descriptor)
  }
}

function enumerateOwnedFiles(userData: string): string[] {
  const files: string[] = []
  if (fs.existsSync(userData) && (!fs.lstatSync(userData).isDirectory() || fs.lstatSync(userData).isSymbolicLink())) throw new Error('回滚快照拒绝链接用户数据目录。')
  const modsRoot = path.join(userData, 'mods')
  if (fs.existsSync(modsRoot)) {
    if (!fs.lstatSync(modsRoot).isDirectory() || fs.lstatSync(modsRoot).isSymbolicLink()) throw new Error('回滚快照拒绝链接 Mod 目录。')
    const visit = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const candidate = path.join(dir, entry.name)
        const relative = path.relative(userData, candidate)
        if (entry.isSymbolicLink()) throw new Error(`回滚快照拒绝 Mod 链接路径：${relative}`)
        if (entry.isDirectory()) visit(candidate)
        else if (entry.isFile()) files.push(candidate)
      }
    }
    visit(modsRoot)
  }
  const rootDbPattern = /^(products|inventory|voice_learning|error_collection)(__[a-z0-9_-]+)?\.db(?:-(?:wal|shm|journal))?$/i
  for (const entry of fs.readdirSync(userData, { withFileTypes: true })) {
    if (entry.isFile() && rootDbPattern.test(entry.name)) files.push(path.join(userData, entry.name))
    if (entry.isSymbolicLink() && rootDbPattern.test(entry.name)) throw new Error(`回滚快照拒绝数据库链接：${entry.name}`)
  }
  const dataRoot = path.join(userData, 'data')
  const addDbFiles = (dir: string, recursive: boolean) => {
    if (!fs.existsSync(dir)) return
    if (!fs.lstatSync(dir).isDirectory() || fs.lstatSync(dir).isSymbolicLink()) throw new Error(`回滚快照拒绝链接数据库目录：${path.relative(userData, dir)}`)
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const candidate = path.join(dir, entry.name)
      const relative = path.relative(userData, candidate)
      if (entry.isSymbolicLink()) throw new Error(`回滚快照拒绝数据库链接：${relative}`)
      if (entry.isDirectory() && recursive) addDbFiles(candidate, true)
      else if (entry.isFile() && /\.db(?:-(?:wal|shm|journal))?$/i.test(entry.name) && !(relative.split(path.sep).length === 2 && relative.split(path.sep)[0]?.toLowerCase() === 'data' && /^xcagi\.db(?:-(?:wal|shm|journal))?$/i.test(entry.name))) files.push(candidate)
    }
  }
  addDbFiles(dataRoot, false)
  addDbFiles(path.join(dataRoot, 'mod_dbs'), true)
  return [...new Set(files)].sort((a, b) => a.localeCompare(b))
}

function enumerateOwnedDirectories(userData: string): string[] {
  const directories = new Set<string>()
  const addTree = (root: string, includeRoot: boolean) => {
    if (!fs.existsSync(root)) return
    if (!fs.lstatSync(root).isDirectory() || fs.lstatSync(root).isSymbolicLink()) throw new Error(`回滚快照拒绝链接目录：${path.relative(userData, root)}`)
    if (includeRoot) directories.add(path.relative(userData, root))
    const visit = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue
        const candidate = path.join(dir, entry.name)
        const relative = path.relative(userData, candidate)
        if (entry.isSymbolicLink()) throw new Error(`回滚快照拒绝链接目录：${relative}`)
        directories.add(relative)
        visit(candidate)
      }
    }
    visit(root)
  }
  addTree(path.join(userData, 'mods'), true)
  const dataRoot = path.join(userData, 'data')
  if (fs.existsSync(dataRoot)) directories.add('data')
  addTree(path.join(dataRoot, 'mod_dbs'), true)
  return [...directories].sort((a, b) => a.localeCompare(b))
}

function snapshotWindowsOwnedState(userData: string, backupRoot: string): { files: Record<string, string>; directories: string[] } {
  const files = enumerateOwnedFiles(userData)
  const directories = enumerateOwnedDirectories(userData)
  const maximumSingleFile = 8 * 1024 ** 3
  const maximumSnapshot = 50 * 1024 ** 3
  let total = 0
  for (const file of files) {
    const relative = path.relative(userData, file)
    if (!isPathInside(userData, file) || !(isOwnedModPath(relative, false) || isOwnedDatabasePath(relative))) throw new Error(`Mod 或数据库快照路径越界：${relative}`)
    const info = fs.lstatSync(file)
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Mod 或数据库快照拒绝链接路径：${relative}`)
    if (info.size > maximumSingleFile) throw new Error(`单个 Mod 或数据库文件超过 8 GiB 安全边界：${relative}`)
    total += info.size
    if (total > maximumSnapshot) throw new Error('Mod 与数据库总快照超过 50 GiB 安全边界。')
  }
  const disk = fs.statfsSync(userData)
  const free = disk.bavail * disk.bsize
  if (free < total + Math.max(1024 ** 3, Math.ceil(total / 10))) throw new Error('可用磁盘空间不足以保留已授权 Mod 与数据库快照。')
  if (fs.existsSync(`${backupRoot}.xcagi-rollback-staging`) || fs.existsSync(`${backupRoot}.xcagi-failed`)) throw new Error('发现未处理的 Mod/数据库回滚暂存或失败现场。')
  fs.mkdirSync(backupRoot, { recursive: false })
  for (const relative of directories) fs.mkdirSync(resolveInside(backupRoot, relative), { recursive: true })
  const inventory: Record<string, string> = {}
  for (const file of files) {
    const relative = path.relative(userData, file)
    const target = resolveInside(backupRoot, relative)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.copyFileSync(file, target, fs.constants.COPYFILE_EXCL)
    const sourceHash = hashFileSync(file)
    const backupHash = hashFileSync(target)
    if (sourceHash !== backupHash) throw new Error(`Mod 或数据库快照校验失败：${relative}`)
    inventory[relative] = sourceHash
  }
  return { files: inventory, directories }
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
    try {
      fs.rmSync(failed, { recursive: true, force: true, maxRetries: 3 })
    } catch (error) {
      console.warn(`[rollback] Obsolete backup retained after replacement: ${failed}`, error)
    }
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
  return app.isPackaged ? app.getPath('exe') : ''
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
  for (const candidate of ['build-info.json', 'backend/build-info.json']) {
    try {
      const parsed = JSON.parse(fs.readFileSync(path.join(process.resourcesPath, candidate), 'utf8')) as { gitSha?: string; buildSha?: string }
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
  if (checkPendingRollback()) {
    throw new Error('已有未完成的更新回滚记录；完成恢复或健康确认前不能覆盖其快照。')
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
    const ownedBackupRoot = path.join(dir, 'windows-owned-state-current')
    if (
      isPathInside(installDir, appBackupRoot) ||
      isPathInside(appBackupRoot, installDir)
    ) {
      throw new Error(
        `回滚备份失败：安装目录与备份目录不能互相嵌套（install=${installDir}, backup=${appBackupRoot}）`,
      )
    }
    const userData = path.resolve(app.getPath('userData'))
    const ownedState = snapshotWindowsOwnedState(userData, ownedBackupRoot)
    replaceDirectoryFromStaging(installDir, appBackupRoot)
    marker = {
      mode: 'windows-full',
      fromVersion,
      toVersion,
      preparedAt: new Date().toISOString(),
      backendPath,
      appPath,
      appBackupRelPath: path.relative(dir, appBackupRoot),
      ownedUserDataRoot: userData,
      ownedBackupRoot,
      expectedOwnedFiles: ownedState.files,
      expectedOwnedDirectories: ownedState.directories,
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
  if (process.platform === 'win32') marker.operationId = randomUUID()
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
  if (preservePreparedRollback || checkPendingRollback()?.recoveryRequired) return
  try { fs.unlinkSync(markerPath()) } catch {}
}

function persistWindowsRollbackMarker(marker: RollbackMarker): void {
  const destination = markerPath()
  const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`
  fs.writeFileSync(temporary, JSON.stringify(marker, null, 2), { encoding: 'utf8', flag: 'wx', mode: 0o600 })
  const descriptor = fs.openSync(temporary, 'r+')
  try { fs.fsyncSync(descriptor) } finally { fs.closeSync(descriptor) }
  fs.renameSync(temporary, destination)
}

export function markPreparedRollbackRecoveryRequired(): void {
  const marker = checkPendingRollback()
  if (!marker || marker.mode !== 'windows-full') throw new Error('Windows 迁移前缺少完整恢复记录。')
  marker.recoveryRequired = true
  // Arm and durably replace the recovery state before starting migration.
  // If persistence fails, the migration child is never launched.
  preservePreparedRollback = true
  persistWindowsRollbackMarker(marker)
}

export function clearPreparedRollbackRecoveryRequired(): void {
  const marker = checkPendingRollback()
  if (!marker || marker.mode !== 'windows-full') throw new Error('Windows 迁移成功但缺少完整恢复记录。')
  marker.recoveryRequired = false
  persistWindowsRollbackMarker(marker)
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
  const marker = checkPendingRollback()
  if (marker?.recoveryRequired) throw new Error('Windows 回滚恢复意图仍然生效，不能健康提交或清理快照。')
  if (marker?.mode === 'windows-full' && marker.ownedBackupRoot) {
    validateOwnedRollbackMarker(marker, rollbackDir())
  }
  preservePreparedRollback = false
  try {
    fs.unlinkSync(markerPath())
  } catch {
    return
  }
  if (marker?.mode !== 'windows-full' || !marker.ownedBackupRoot) return
  const userData = path.resolve(app.getPath('userData'))
  const rollbackRoot = path.join(userData, 'rollback')
  const ownedBackupRoot = path.resolve(marker.ownedBackupRoot)
  if (
    ownedBackupRoot === rollbackRoot ||
    !isPathInside(rollbackRoot, ownedBackupRoot) ||
    path.basename(ownedBackupRoot).toLowerCase() !== 'windows-owned-state-current'
  ) return
  try {
    fs.rmSync(ownedBackupRoot, { recursive: true, force: true, maxRetries: 3 })
  } catch (error) {
    console.error(`[rollback] 已健康确认，但当前 Mod/数据库快照清理失败，保留路径 ${ownedBackupRoot}`, error)
  }
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

export async function triggerRollback(reason: string, beforeRestore?: () => Promise<void>): Promise<RollbackTriggerResult> {
  let marker = checkPendingRollback()
  if (!marker) {
    return { mode: 'none', scheduled: false }
  }
  if (!beforeRestore && fs.existsSync(`${modelUsageLedgerPath(app.getPath('userData'), process.env, path.dirname(marker.backendPath))}.sqlite3`)) {
    throw new Error('计量账本需要停写并交接后才能回滚；请通过后端生命周期入口执行。')
  }

  const dir = rollbackDir()
  if (process.platform === 'darwin' && (!marker.mode || marker.mode === 'backend')) {
    if (!marker.backupRelPath) throw new Error('回滚失败：marker 缺少 backend 备份路径')
    const backendBackup = resolveInside(dir, marker.backupRelPath)
    if (!fs.existsSync(backendBackup)) throw new Error(`回滚失败：备份目录不存在 ${backendBackup}`)
    const bundle = resolveMacOSAppBundlePath(resolvePackagedAppPath() || '')
    marker = promoteLegacyMacRollback(marker, dir, bundle, backendBackup)
  }
  if (process.platform === 'darwin' && (marker.mode !== 'macos-full' || !marker.appBundlePath || !marker.appBackupRelPath)) {
    throw new Error('完整旧版应用备份不足：Mac 回滚标记不完整或来自其他平台；保留当前应用、数据库和标记')
  }
  const applied: RollbackApplied & WindowsRollbackAppliedRecord = {
    ...(process.platform === 'win32' ? { operationId: marker.operationId || randomUUID() } : {}),
    appliedAt: new Date().toISOString(),
    reason,
    fromVersion: marker.toVersion,
    toVersion: marker.fromVersion
  }

  const windows = process.platform === 'win32' && marker.mode === 'windows-full' && marker.appPath
  const macos = process.platform === 'darwin' && marker.mode === 'macos-full' && marker.appBundlePath
  assertLedgerOutsideRollbackTarget(
    modelUsageLedgerPath(app.getPath('userData'), process.env, path.dirname(marker.backendPath)),
    windows ? path.dirname(windows) : macos || path.dirname(marker.backendPath),
  )
  if (windows && marker.ownedUserDataRoot) {
    const ledger = modelUsageLedgerPath(app.getPath('userData'), process.env, path.dirname(marker.backendPath))
    const relative = path.relative(marker.ownedUserDataRoot, ledger)
    if (isOwnedModPath(relative, false) || isOwnedDatabasePath(relative)) {
      throw new Error('计量账本位于将被恢复的 Mod/数据库快照内，已中止回滚；请先迁移账本至独立持久目录。')
    }
  }
  if ((windows || macos) && marker.appBackupRelPath) {
    const backupRoot = resolveInside(dir, marker.appBackupRelPath)
    if (!fs.existsSync(backupRoot)) throw new Error(`回滚失败：完整应用备份目录不存在 ${backupRoot}`)
    const options = {
      currentPid: process.pid, backupRoot, appPath: (windows || macos) as string,
      markerPath: markerPath(), appliedPath: appliedPath(), logPath: helperLogPath(), applied,
      ...(marker.databasePath && (marker.databaseBackupPath || (windows && marker.databaseOriginallyAbsent === true))
        ? { databasePath: marker.databasePath, databaseBackupPath: marker.databaseBackupPath }
        : {}),
    }
    if (windows) {
      validateOwnedRollbackMarker(marker, dir)
      await beforeRestore?.()
      await launchWindowsFullRollback({ ...options, installDir: path.dirname(windows), expectedAppFiles: marker.expectedAppFiles, expectedDatabaseSha256: marker.expectedDatabaseSha256, databaseOriginallyAbsent: marker.databaseOriginallyAbsent, ownedUserDataRoot: marker.ownedUserDataRoot, ownedBackupRoot: marker.ownedBackupRoot, expectedOwnedFiles: marker.expectedOwnedFiles, expectedOwnedDirectories: marker.expectedOwnedDirectories })
    }
    else {
      await beforeRestore?.()
      await launchMacOSFullRollback(options)
    }
    return { mode: windows ? 'windows-full' : 'macos-full', scheduled: true }
  }

  if (!marker.backupRelPath) {
    throw new Error('回滚失败：marker 缺少 backend 备份路径')
  }
  const backupRoot = resolveInside(dir, marker.backupRelPath)
  if (!fs.existsSync(backupRoot)) {
    throw new Error(`回滚失败：备份目录不存在 ${backupRoot}`)
  }

  const backendDir = path.dirname(marker.backendPath)
  await beforeRestore?.()
  replaceDirectoryFromStaging(backupRoot, backendDir)

  fs.writeFileSync(appliedPath(), JSON.stringify(applied, null, 2), 'utf8')

  try { fs.unlinkSync(markerPath()) } catch {}
  return { mode: 'backend', scheduled: false }
}
