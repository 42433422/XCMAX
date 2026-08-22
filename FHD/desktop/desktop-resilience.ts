import { app, crashReporter, dialog } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import {
  downloadUpdate,
  installUpdate,
  isForceUpgradeRequired,
  readLocalProductVersion,
} from './updater'

type WriteLog = (line: string) => void
type BeforeInstall = NonNullable<Parameters<typeof installUpdate>[0]>
type OnInstallFailed = NonNullable<Parameters<typeof installUpdate>[1]>

interface CrashReportingOptions {
  port: number
  writeLog: WriteLog
}

interface ForceUpgradeOptions {
  appName: string
  writeLog: WriteLog
  beforeInstall: BeforeInstall
  onInstallFailed: OnInstallFailed
}

async function uploadCrashReports(options: CrashReportingOptions): Promise<void> {
  const crashDir = app.getPath('crashDumps')
  try {
    const entries = fs.readdirSync(crashDir, { withFileTypes: true })
    const pending = entries.filter(
      entry => entry.isFile() && !entry.name.endsWith('.uploaded') && !entry.name.endsWith('.uploading'),
    )
    if (!pending.length) return

    const markerDir = path.join(crashDir, '.uploaded-markers')
    fs.mkdirSync(markerDir, { recursive: true })
    for (const entry of pending) {
      const filePath = path.join(crashDir, entry.name)
      const markerPath = path.join(markerDir, `${entry.name}.ok`)
      if (fs.existsSync(markerPath)) continue
      try {
        const fileBuffer = fs.readFileSync(filePath)
        const formData = new FormData()
        formData.append('minidump', new Blob([fileBuffer]), entry.name)
        const response = await fetch(
          `http://127.0.0.1:${options.port}/api/desktop/crash-report`,
          {
            method: 'POST',
            body: formData,
            signal: AbortSignal.timeout(10_000),
          },
        )
        if (!response.ok) throw new Error(`crash upload rejected: HTTP ${response.status}`)
        fs.writeFileSync(markerPath, new Date().toISOString(), 'utf8')
        options.writeLog(`[crash] uploaded ${entry.name} to backend\n`)
      } catch {
        options.writeLog(`[crash] upload failed for ${entry.name}, will retry next startup\n`)
      }
    }
  } catch {
    // crash directory is optional until Electron creates it
  }
}

async function sendJsCrashReport(
  options: CrashReportingOptions,
  payload: { type: string; error: string; stack?: string },
): Promise<void> {
  try {
    await fetch(`http://127.0.0.1:${options.port}/api/desktop/crash-report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...payload,
        ts: new Date().toISOString(),
        appVersion: readLocalProductVersion(),
        toolchainVersion: app.getVersion(),
      }),
      signal: AbortSignal.timeout(5_000),
    })
  } catch {
    // the backend may be unavailable during startup or shutdown
  }
}

export function initializeLocalCrashReporting(options: CrashReportingOptions): void {
  try {
    const crashDir = path.join(app.getPath('userData'), 'crash-dumps')
    fs.mkdirSync(crashDir, { recursive: true })
    app.setPath('crashDumps', crashDir)
    crashReporter.start({ uploadToServer: false, compress: true })
    options.writeLog(`[crash] local crash capture enabled dir=${crashDir}\n`)
  } catch (error) {
    options.writeLog(
      `[crash] initialization failed: ${error instanceof Error ? error.message : String(error)}\n`,
    )
  }
  process.on('uncaughtExceptionMonitor', error => {
    options.writeLog(`[crash] main uncaughtException: ${error.stack || error.message}\n`)
    void sendJsCrashReport(options, {
      type: 'uncaughtException',
      error: error.message,
      stack: error.stack,
    })
  })
  process.on('unhandledRejection', reason => {
    const message = reason instanceof Error ? reason.stack || reason.message : String(reason)
    options.writeLog(`[crash] main unhandledRejection: ${message}\n`)
    void sendJsCrashReport(options, {
      type: 'unhandledRejection',
      error: String(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
    })
  })
  setTimeout(() => void uploadCrashReports(options), 30_000)
}

/**
 * 渲染进程错误遥测：复用现有后端 crash-report 通道持久化（后端负责聚合与上报），
 * 避免再造新端点。best-effort，后端不可用则静默丢弃。
 */
export function reportRendererError(
  options: CrashReportingOptions,
  payload: { type: string; error: string; stack?: string },
): void {
  void sendJsCrashReport(options, payload)
}

export function createForceUpgradeHandler(options: ForceUpgradeOptions): () => Promise<void> {
  let dialogOpen = false
  return async () => {
    if (!isForceUpgradeRequired() || dialogOpen) return
    dialogOpen = true
    options.writeLog('[force-upgrade] 当前版本低于最低兼容版本，触发强制升级\n')
    try {
      const { response } = await dialog.showMessageBox({
        type: 'warning',
        title: options.appName,
        message: '当前版本过低，需要更新',
        detail:
          '当前使用的 XCAGI 版本已低于最低兼容版本，部分功能可能不可用。\n\n' +
          '请点击「立即更新」下载最新版本，或从官网下载安装包手动更新。',
        buttons: ['立即更新', '退出'],
        defaultId: 0,
        cancelId: 1,
      })
      if (response !== 0) {
        app.quit()
        return
      }
      options.writeLog('[force-upgrade] 用户确认强制升级，开始下载…\n')
      await downloadUpdate()
      options.writeLog('[force-upgrade] 下载完成，准备安装…\n')
      await installUpdate(options.beforeInstall, options.onInstallFailed)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      options.writeLog(`[force-upgrade] 强制升级失败: ${message}\n`)
      await dialog.showMessageBox({
        type: 'error',
        title: options.appName,
        message: '强制升级失败',
        detail: `${message}\n\n请从官网下载最新安装包手动更新。`,
      })
    } finally {
      dialogOpen = false
    }
  }
}
