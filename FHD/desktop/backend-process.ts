import { app, dialog } from 'electron'
import { execFile, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import {
  APP_NAME,
  DEFAULT_PORT,
  DESKTOP_BACKEND_BIND_HOST,
  backendEditionEnv,
  backendExecutable,
  isPortAvailable,
  packagedBackendCandidates,
  portOccupiedHint,
  readPackagedProductSku,
  repoRoot,
} from './desktop-config'
import { desktopRuntime } from './runtime-state'
import {
  attachDatabaseBackupToRollback,
  cancelPreparedRollback,
  prepareRollback,
  triggerRollback,
  type RollbackTriggerResult,
} from './rollback'
import { terminateChildProcess, waitForChildExit } from './backend-lifecycle'
import { desktopBackendEnv } from './backend-env'
import { sanitizeBackendProxyEnv } from './backend-env-utils'
import { createForceUpgradeHandler } from './desktop-resilience'

export const POST_UPDATE_STABILITY_MS = 5_000

function rotateBackendLogIfNeeded(logPath: string): void {
  const maxBytes = 8 * 1024 * 1024
  try {
    if (!fs.existsSync(logPath)) {
      return
    }
    if (fs.statSync(logPath).size < maxBytes) {
      return
    }
    const rotated = `${logPath}.1`
    if (fs.existsSync(rotated)) {
      fs.unlinkSync(rotated)
    }
    fs.renameSync(logPath, rotated)
  } catch {
    /* ignore rotation failures */
  }
}

function ensureBackendLogStream(): fs.WriteStream | null {
  if (desktopRuntime.backendLogStream) {
    return desktopRuntime.backendLogStream
  }
  try {
    const logDir = path.join(app.getPath('userData'), 'logs')
    fs.mkdirSync(logDir, { recursive: true })
    const logPath = path.join(logDir, 'electron-backend.log')
    rotateBackendLogIfNeeded(logPath)
    desktopRuntime.backendLogStream = fs.createWriteStream(logPath, {
      flags: 'a'
    })
    desktopRuntime.backendLogStream.write(`\n[${new Date().toISOString()}] XCAGI desktop backend bootstrap\n`)
    desktopRuntime.backendLogStream.write(
      JSON.stringify(
        {
          platform: process.platform,
          arch: process.arch,
          packaged: app.isPackaged,
          resourcesPath: app.isPackaged ? process.resourcesPath : null,
          userData: app.getPath('userData'),
          sku: readPackagedProductSku() || 'generic'
        },
        null,
        2
      ) + '\n'
    )
    return desktopRuntime.backendLogStream
  } catch {
    return null
  }
}

export function writeBackendLog(line: string): void {
  try {
    ensureBackendLogStream()?.write(line)
  } catch {
    /* ignore logging failures */
  }
}

export const checkForceUpgrade = createForceUpgradeHandler({
  appName: APP_NAME,
  writeLog: writeBackendLog,
  beforeInstall: runBackendMigrationWithRollback,
  onInstallFailed: cancelPreparedRollback,
  prepareQuit: stopBackend,
})

export function packagedBackendHealthTimeoutMs(): number {
  if (!app.isPackaged) {
    return 60_000
  }
  // 首次启动：Alembic、Mod 种子、太阳鸟花名册等可能超过 60s
  return process.platform === 'win32' ? 180_000 : 120_000
}

/** 轻量就绪探测：/api/ping 无 NeuroBus 载荷，轮询更快。 */
export async function waitForBackendPing(
  port: number,
  timeoutMs = packagedBackendHealthTimeoutMs()
): Promise<void> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/ping`, {
        signal: AbortSignal.timeout(2_000)
      })
      const server = (response.headers.get('server') || '').toLowerCase()
      if (response.ok && server.includes('uvicorn')) {
        desktopRuntime.startupMarks.backendHealthMs = Date.now() - (desktopRuntime.startupMarks.backendSpawnMs ?? started)
        return
      }
      if (server.includes('airtunes')) {
        console.warn(`[xcagi-desktop] 端口 ${port} 被 macOS 隔空播放占用，等待 XCAGI 后端…`)
      }
    } catch {
      /* backend still booting */
    }
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  const airplayHint =
    port === 5000
      ? ' 5000 是历史开发端口，正式桌面版默认端口为 17500；请清理 XCAGI_DESKTOP_PORT 后重启。'
      : ''
  const firstBootHint = app.isPackaged
    ? ' 若仍失败，请查看数据目录 logs/ 下后端日志，或从菜单导出诊断包。'
    : ''
  throw new Error(
    `后端 /api/ping 在 ${timeoutMs}ms 内未就绪（端口 ${port}）。${airplayHint}${firstBootHint}`
  )
}

/** @deprecated 使用 waitForBackendPing；保留别名供测试/旧引用。 */
export const waitForBackendHealth = waitForBackendPing

/** ping 就绪且业务路由已挂载（fast-start deferred 完成后）再加载主应用。 */
export async function waitForBackendApplicationReady(
  port: number,
  timeoutMs = packagedBackendHealthTimeoutMs(),
  options?: { skipPing?: boolean }
): Promise<void> {
  if (!options?.skipPing) {
    await waitForBackendPing(port, timeoutMs)
  }
  const started = Date.now()
  const remaining = () => Math.max(0, timeoutMs - (Date.now() - started))
  while (remaining() > 0) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`, {
        signal: AbortSignal.timeout(2_000)
      })
      if (response.ok) {
        const body = (await response.json()) as {
          appRoutesReady?: boolean
          readyForUi?: boolean
        }
        const routesReady = body.appRoutesReady ?? body.readyForUi
        if (routesReady !== false) {
          return
        }
      }
    } catch {
      /* routes still registering */
    }
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  console.warn('[xcagi-desktop] appRoutesReady 未在时限内为 true，仍加载主应用')
}

/** 分阶段就绪：TCP 后即可出窗；desktop/status 软等待，不阻塞 60s 全量 Mod。 */
export async function waitForBackendStatus(port: number, timeoutMs = 60_000): Promise<Record<string, unknown> | null> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`)
      if (response.ok) {
        desktopRuntime.startupMarks.desktopStatusMs = Date.now() - (desktopRuntime.startupMarks.backendSpawnMs ?? started)
        return (await response.json()) as Record<string, unknown>
      }
    } catch {
      /* backend still importing routers */
    }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  console.warn(`[xcagi-desktop] /api/desktop/status 未在 ${timeoutMs}ms 内就绪，仍加载前端`)
  return null
}

/**
 * 检查启动自检 + 自动恢复状态，必要时弹窗提示用户。
 *
 * 后端启动时 recover_if_corrupt 会检测主库：
 * - action=ok：库健康，不弹
 * - action=restored：库损坏但已从备份恢复，弹警告（数据可能回退到上次备份）
 * - action=corrupt_no_backup：库损坏且无可用备份，弹错误（严重，可能丢失数据）
 */
export async function showDbRecoveryDialogIfNeeded(status: Record<string, unknown> | null): Promise<void> {
  if (!status) return
  const recovery = status.dbRecovery as { action?: string; detail?: string | null } | undefined
  if (!recovery || recovery.action === 'ok') return

  if (recovery.action === 'corrupt_no_backup') {
    await dialog.showMessageBox({
      type: 'error',
      title: APP_NAME,
      message: '数据库损坏且无可用备份',
      detail:
        'XCAGI 启动时检测到数据库损坏，但未找到可用的备份文件。\n\n' +
        '应用仍会启动，但可能无法访问历史数据。请从菜单「导出诊断包」收集日志后联系技术支持。\n' +
        '建议尽快从外部备份（如 USB 备份）恢复 data/xcagi.db。'
    })
    return
  }

  if (recovery.action === 'restored') {
    const fromBackup = recovery.detail || '未知备份'
    await dialog.showMessageBox({
      type: 'warning',
      title: APP_NAME,
      message: '数据库已从备份自动恢复',
      detail:
        `XCAGI 启动时检测到数据库损坏，已自动从备份恢复：${fromBackup}\n\n` +
        '最近一次备份之后产生的数据可能丢失。请检查关键业务数据是否完整。\n' +
        '如需手动恢复更早的备份，请从菜单「打开数据目录」找到 backups/ 文件夹。'
    })
  }
}

export async function startBackend(): Promise<void> {
  if (desktopRuntime.backendProcess) {
    return
  }

  const executable = backendExecutable()
  if (app.isPackaged && !fs.existsSync(executable.command)) {
    const candidates = packagedBackendCandidates().map(candidate => `- ${candidate}`).join('\n')
    const detail =
      `找不到后端程序：${executable.command}\n\n` +
      `已检查：\n${candidates}\n\n` +
      `请确认安装包包含 resources/backend/${process.platform === 'win32' ? 'xcagi-backend.exe' : 'xcagi-backend'}。`
    writeBackendLog(`[error] ${detail}\n`)
    void dialog.showErrorBox(APP_NAME, detail)
    return
  }

  // 桌面模式不做端口避让：启动前预检 DEFAULT_PORT，被占则直接引导用户，避免后端
  // 启动后立即退出再触发无意义的自动重启。
  const portFree = await isPortAvailable(DEFAULT_PORT)
  if (!portFree) {
    const hint = portOccupiedHint(DEFAULT_PORT)
    writeBackendLog(`[error] port ${DEFAULT_PORT} occupied, abort backend spawn\n`)
    void dialog.showErrorBox(APP_NAME, hint)
    return
  }

  desktopRuntime.startupMarks.backendSpawnMs = Date.now()
  writeBackendLog(`[spawn] ${executable.command} ${executable.args.join(' ')}\n`)
  writeBackendLog(`[cwd] ${executable.cwd}\n`)
  const child = spawn(executable.command, executable.args, {
    cwd: executable.cwd,
    env: desktopBackendEnv({
      ...sanitizeBackendProxyEnv(process.env),
      XCAGI_DESKTOP_MODE: '1',
      XCAGI_DATA_DIR: app.getPath('userData'),
      // 备份文件名携带应用版本（xcagi-<version>-<ts>.db）；缺失时 run_fastapi 退回 "unknown"。
      XCAGI_VERSION: app.getVersion(),
      XCAGI_API_HOST: DESKTOP_BACKEND_BIND_HOST,
      XCAGI_UVICORN_RELOAD: '0',
      XCAGI_GLOBAL_RATE_LIMIT: '0',
      // Market primary (xiaomi) often failovers before first delta; give headroom.
      XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC:
        process.env.XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC || '45',
      LOG_LEVEL: process.env.LOG_LEVEL || (app.isPackaged ? 'WARNING' : 'INFO'),
      XCAGI_DESKTOP_FAST_START: '1',
      ...backendEditionEnv(),
      PYTHONUTF8: '1'
    }, app.isPackaged ? undefined : repoRoot()),
    windowsHide: true
  })
  desktopRuntime.backendProcess = child
  child.stdout.on('data', data => {
    process.stdout.write(`[xcagi-backend] ${data}`)
    writeBackendLog(`[stdout] ${data}`)
  })
  child.stderr.on('data', data => {
    process.stderr.write(`[xcagi-backend] ${data}`)
    writeBackendLog(`[stderr] ${data}`)
  })
  child.on('error', error => {
    handleBackendSpawnError(error)
  })
  child.on('exit', code => {
    const uptimeMs = Date.now() - (desktopRuntime.startupMarks.backendSpawnMs ?? Date.now())
    writeBackendLog(`[exit] backend process exited code=${code} uptime=${uptimeMs}ms\n`)
    desktopRuntime.backendProcess = null
    if (app.isQuitting) {
      return
    }
    // 通知自治控制器 backend 退出（控制器据此追踪崩溃频率，5min ≥3 次则自动回滚）
    desktopRuntime.autonomyController?.ingest({
      source: 'backend_exit',
      kind: 'backend_exit',
      severity: 'crit',
      detail: `backend exited code=${code} uptime=${uptimeMs}ms`,
      ts: Date.now(),
      payload: { code, uptimeMs, restartCount: desktopRuntime.restartCount },
    })
    // 快速退出（< 5 秒）：通常是端口占用或配置错误，不自动重启以免浪费用户时间
    if (uptimeMs < 5000) {
      void dialog.showErrorBox(
        APP_NAME,
        `后端服务启动后立即退出（code=${code}）。\n\n请查看数据目录 logs/ 下后端日志，或从菜单导出诊断包。`
      )
      return
    }
    desktopRuntime.restartCount += 1
    if (desktopRuntime.restartCount <= 3) {
      setTimeout(() => void startBackend(), 1500)
      return
    }
    void dialog.showErrorBox(APP_NAME, `后端服务已退出（code=${code}），请重启 XCAGI。`)
  })
}

export async function runBackendMigrationWithRollback(toVersion: string): Promise<void> {
  try {
    await prepareRollback(toVersion)
    await runBackendMigration()
  } catch (error) {
    cancelPreparedRollback()
    throw error
  }
}

/** 触发回滚但吞掉自身错误，避免回滚失败导致二次崩溃 */
export async function triggerRollbackSafe(reason: string): Promise<RollbackTriggerResult | null> {
  try {
    const result = await triggerRollback(reason)
    writeBackendLog(`[rollback] 已触发回滚 mode=${result.mode} scheduled=${result.scheduled}：${reason}\n`)
    return result
  } catch (e) {
    writeBackendLog(`[rollback] 回滚失败：${e instanceof Error ? e.message : e}\n`)
    return null
  }
}

function runBackendMigration(): Promise<string> {
  const executable = backendExecutable()
  return new Promise((resolve, reject) => {
    const child = spawn(executable.command, [...executable.args, '--migrate-only', '--backup'], {
      cwd: executable.cwd,
      env: desktopBackendEnv({
        ...sanitizeBackendProxyEnv(process.env),
        XCAGI_DESKTOP_MODE: '1',
        XCAGI_DATA_DIR: app.getPath('userData'),
        XCAGI_UVICORN_RELOAD: '0',
        XCAGI_GLOBAL_RATE_LIMIT: '0',
        ...backendEditionEnv(),
        PYTHONUTF8: '1'
      }, app.isPackaged ? undefined : repoRoot()),
      windowsHide: true
    })
    let stderr = ''
    let stdout = ''
    let databaseBackupPath = ''
    let backupAttachError: unknown
    child.stderr.on('data', data => {
      stderr += String(data)
      process.stderr.write(`[xcagi-migrate] ${data}`)
    })
    child.stdout.on('data', data => {
      stdout += String(data)
      process.stdout.write(`[xcagi-migrate] ${data}`)
      if (!databaseBackupPath) {
        const match = stdout.match(/^XCAGI_MIGRATION_BACKUP=(.+)$/m)
        const candidate = match?.[1]?.trim() || ''
        if (candidate) {
          try {
            attachDatabaseBackupToRollback(candidate)
            databaseBackupPath = candidate
          } catch (error) {
            backupAttachError = error
            child.kill()
          }
        }
      }
    })
    child.on('error', reject)
    child.on('exit', code => {
      if (backupAttachError) {
        reject(backupAttachError)
        return
      }
      if (code === 0) {
        resolve(databaseBackupPath)
      } else {
        reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`))
      }
    })
  })
}

export async function stopBackend(): Promise<void> {
  const child = desktopRuntime.backendProcess
  desktopRuntime.backendProcess = null
  if (!child) {
    return
  }
  writeBackendLog(`[${new Date().toISOString()}] backend stop requested\n`)
  let result = 'already-exited'
  if (process.platform === 'win32' && child.pid) {
    const exited = waitForChildExit(child, 2500)
    await new Promise<void>(resolve => {
      execFile('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true }, () => resolve())
    })
    result = (await exited) ? 'killed' : 'kill-timeout'
  } else {
    result = await terminateChildProcess(child)
  }
  desktopRuntime.backendLogStream?.end(`[${new Date().toISOString()}] backend log closed result=${result}\n`)
  desktopRuntime.backendLogStream = null
}

export function handleBackendSpawnError(error: Error): void {
  desktopRuntime.backendProcess = null
  writeBackendLog(`[error] backend spawn failed: ${error.message}\n`)
  if (app.isQuitting) {
    return
  }
  void dialog.showErrorBox(
    APP_NAME,
    `后端服务启动失败：${error.message}\n\n应用将退出，请重启 XCAGI。`,
  )
  app.quit()
}

export async function waitForPostUpdateStartupStability(
  durationMs = POST_UPDATE_STABILITY_MS,
): Promise<void> {
  const deadline = Date.now() + durationMs
  while (Date.now() < deadline) {
    if (!desktopRuntime.backendProcess) {
      throw new Error('更新后观察期内 backend 进程退出')
    }
    if (!desktopRuntime.mainWindow || desktopRuntime.mainWindow.isDestroyed()) {
      throw new Error('更新后观察期内主窗口退出')
    }
    if (desktopRuntime.rendererFailedDuringStartup) {
      throw new Error('更新后观察期内 renderer 进程崩溃')
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  await waitForBackendPing(DEFAULT_PORT, 5_000)
}
