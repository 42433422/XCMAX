import { BrowserWindow, app, dialog, globalShortcut } from 'electron'
import path from 'node:path'
import { configureOtaProxyCommandLine, applyOtaProxyBypass } from './ota-proxy'
import {
  DEFAULT_PORT,
  ED25519_PUBLIC_KEY_PEM,
  SKU_UPDATE_URL,
  readPackagedProductSku,
} from './desktop-config'
import { desktopRuntime } from './runtime-state'
import {
  commitRollback,
  checkPendingRollback,
  consumeRollbackApplied,
} from './rollback'
import { readLocalBuildSha, readLocalProductVersion } from './updater'
import { reportPendingUpdateInstallation } from './update-install-receipts'
import { AutonomyController } from './autonomy/controller'
import { DesktopAutonomyAdapter } from './autonomy/desktop-adapter'
import { backendCrashPolicy } from './autonomy/policies/backend-crash.policy'
import { degradedRemediationPolicy } from './autonomy/policies/degraded-remediation.policy'
import { updateRollbackPolicy } from './autonomy/policies/update-rollback.policy'
import { initializeLocalCrashReporting } from './desktop-resilience'
import { findDeepLinkArg } from './desktop-navigation'
import { warmPersistedDesktopSessionCookieStore } from './session-cookie-warmup'
import {
  startBackend,
  stopBackend,
  triggerRollbackSafe,
  waitForPostUpdateStartupStability,
  writeBackendLog,
  handleBackendSpawnError,
} from './backend-process'
import {
  createWindow,
  showMainWindow,
  toggleMainWindow,
  updateSplashProgress,
  waitForMainApplicationReady,
  broadcastToRenderer,
} from './window-manager'
import { configureDesktopMediaPermissions, installDesktopCspDefenseInDepth } from './session-security'
import {
  captureFullScreenScreenshot,
  consumeReleaseNotes,
  createMenu,
  createTray,
  handleDeepLink,
  patchDesktopSettings,
  readDesktopSettings,
  setAutoLaunchEnabled,
} from './app-shell'
import { registerDesktopIpcHandlers } from './ipc-handlers'

// 与 paths.py / 安装器太阳鸟种子目录一致（勿用 package.json 默认 xcagi-desktop）
// 注：单测环境通过 XCAGI_DESKTOP_TEST=1 跳过 bootstrap()，但模块顶层仍有副作用，
// 测试中通过 vi.mock('electron') 替换 app，故下列两行在测试环境下也安全。
app.setPath('userData', process.env.XCAGI_DESKTOP_USER_DATA_DIR?.trim() || path.join(app.getPath('appData'), 'XCAGI'))
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')
// OTA 代理绕过 commandLine 开关（含 win32 系统代理不可达时的直连兜底）。
configureOtaProxyCommandLine()

/** E2E（Playwright-Electron）模式：隔离真实系统副作用（登录项/协议注册/全局快捷键/OTA）。 */
const isE2ERun = process.env.XCAGI_DESKTOP_E2E === '1'

function bootstrap(): void {
  const gotLock = app.requestSingleInstanceLock()
  if (!gotLock) {
    app.quit()
  } else {
    initializeLocalCrashReporting({ port: DEFAULT_PORT, writeLog: writeBackendLog })

    // macOS：深链通过 open-url 到达（独立于 single-instance argv）。
    app.on('open-url', (event, rawUrl) => {
      event.preventDefault()
      if (!rawUrl?.startsWith('xcagi://')) return
      handleDeepLink(rawUrl)
    })

    app.on('second-instance', (_event, commandLine) => {
      const deepLink = findDeepLinkArg(commandLine)
      if (deepLink) {
        handleDeepLink(deepLink)
      }
      const mainWindow = desktopRuntime.mainWindow
      if (mainWindow && !mainWindow.isDestroyed()) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
      }
    })

    app.on('before-quit', () => {
      app.isQuitting = true
    })

    // will-quit runs after BrowserWindows have closed, so renderer keep-alive
    // connections no longer prevent the backend from shutting down gracefully.
    app.on('will-quit', event => {
      globalShortcut.unregisterAll()
      if (desktopRuntime.backendShutdownComplete) {
        return
      }
      event.preventDefault()
      if (!desktopRuntime.backendShutdownPromise) {
        desktopRuntime.backendShutdownPromise = stopBackend().finally(() => {
          desktopRuntime.backendShutdownComplete = true
          app.quit()
        })
      }
    })

    app.whenReady().then(async () => {
      await applyOtaProxyBypass()
      desktopRuntime.desktopBootstrapSessionHintAvailable = await warmPersistedDesktopSessionCookieStore(DEFAULT_PORT)
      if (desktopRuntime.desktopBootstrapSessionHintAvailable) {
        writeBackendLog('[session] restored persisted desktop session cookie before renderer startup\n')
      }
      const sku = readPackagedProductSku()
      if (sku && !process.env.XCAGI_UPDATE_URL) {
        process.env.XCAGI_UPDATE_URL = SKU_UPDATE_URL[sku]
      }
      // 嵌入 Ed25519 公钥，启用 update 元数据二次签名校验
      if (!process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY) {
        process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = ED25519_PUBLIC_KEY_PEM
      }

      if (!isE2ERun) {
        // 注册系统默认协议处理器（xcagi:// 深链），失败不阻塞启动。
        try {
          app.setAsDefaultProtocolClient('xcagi')
        } catch {
          /* 深链注册失败仅降低对外唤起能力 */
        }

        // 开机自启：首次运行默认开启（匹配"常驻托盘 + 秒开"定位），用户可随时关闭。
        if (!readDesktopSettings().autoLaunchInitialized) {
          const init = setAutoLaunchEnabled(true)
          patchDesktopSettings({ autoLaunchInitialized: true })
          if (!init.ok) {
            writeBackendLog(`[autolaunch] initial enable failed: ${init.reason}\n`)
          }
        }
      }

      registerDesktopIpcHandlers()

      configureDesktopMediaPermissions()
      installDesktopCspDefenseInDepth()
      createMenu()
      createTray()
      if (!isE2ERun) {
        // 全局快捷键：唤起 / 隐藏主窗口（常驻模式直达）
        try {
          const okToggle = globalShortcut.register('CommandOrControl+Shift+X', () => toggleMainWindow())
          if (!okToggle) writeBackendLog('[shortcut] 注册 CommandOrControl+Shift+X 失败（可能被占用）\n')
        } catch (error) {
          writeBackendLog(`[shortcut] 注册 CommandOrControl+Shift+X 异常：${error instanceof Error ? error.message : error}\n`)
        }
        // 全局截图：截图数据写入数据目录 + 复制到剪贴板，并通知渲染端。
        try {
          const okShot = globalShortcut.register('CommandOrControl+Shift+5', () => {
            void captureFullScreenScreenshot().then(result => {
              broadcastToRenderer('xcagi:screenshot-captured', result)
              if (result.ok) writeBackendLog(`[capture] saved ${result.path}\n`)
            })
          })
          if (!okShot) writeBackendLog('[shortcut] 注册 CommandOrControl+Shift+5 失败（可能被占用）\n')
        } catch (error) {
          writeBackendLog(`[shortcut] 注册 CommandOrControl+Shift+5 异常：${error instanceof Error ? error.message : error}\n`)
        }
        // 语音唤起：唤起窗口（只显示不隐藏）并通知渲染端聚焦/展开语音输入（具体语音交互由前端实现）。
        try {
          const okVoice = globalShortcut.register('CommandOrControl+Shift+V', () => {
            showMainWindow()
            broadcastToRenderer('xcagi:voice-invoke')
          })
          if (!okVoice) writeBackendLog('[shortcut] 注册 CommandOrControl+Shift+V 失败（可能被占用）\n')
        } catch (error) {
          writeBackendLog(`[shortcut] 注册 CommandOrControl+Shift+V 异常：${error instanceof Error ? error.message : error}\n`)
        }
      }

      // 更新后首次启动观察期：检查 rollback marker
      const pendingRollback = checkPendingRollback()
      if (pendingRollback) {
        writeBackendLog(`[rollback] 观察期：更新后首次启动 from=${pendingRollback.fromVersion} to=${pendingRollback.toVersion}\n`)
      }
      // 如果上次发生过回滚，提示用户
      const appliedRollback = consumeRollbackApplied()
      if (appliedRollback) {
        void dialog.showMessageBox({
          type: 'info',
          title: 'XCAGI',
          message: `XCAGI 已自动回滚到上一版本 ${appliedRollback.toVersion}`,
          detail: `原因：${appliedRollback.reason}\n\n当前版本仍可正常使用。如问题持续，请联系支持。`
        })
      }

      try {
        // 先出 Splash，再并行拉起后端，避免用户长时间无窗口反馈
        await createWindow()
        updateSplashProgress(12, '正在连接本地服务…')
        await startBackend()
        if (!desktopRuntime.backendProcess) {
          // 端口被占或后端可执行文件缺失，startBackend 已弹错误框
          // 如果是更新后首次启动，触发回滚
          if (pendingRollback) {
            const rollback = await triggerRollbackSafe('startBackend 失败：端口被占或 backend 可执行文件缺失')
            void dialog.showErrorBox(
              'XCAGI',
              !rollback
                ? '更新后启动失败，自动回滚也未能启动。请从官网下载稳定版重新安装。'
                : rollback.scheduled
                  ? '更新后启动失败，正在恢复上一版本；XCAGI 将自动重启。'
                  : '更新后启动失败，已恢复上一版本。请重启 XCAGI。',
            )
          }
          app.quit()
          return
        }
        if (pendingRollback) {
          await waitForMainApplicationReady()
          await waitForPostUpdateStartupStability()
          commitRollback()
          writeBackendLog(`[rollback] 后端、业务路由、主界面与观察期就绪，已提交（marker 删除）\n`)
        }
        try {
          const receipt = await reportPendingUpdateInstallation({
            backendPort: DEFAULT_PORT,
            installedVersion: readLocalProductVersion(),
            installedBuildSha: readLocalBuildSha(),
            rollback: appliedRollback ? { reason: appliedRollback.reason } : null,
          })
          if (receipt.reported) {
            writeBackendLog(`[updater] install receipt ${receipt.status}\n`)
          }
        } catch (error) {
          // 保留 outbox 文件，下次启动重试；不得将“上报失败”当成“安装失败”。
          writeBackendLog(`[updater] install receipt deferred: ${error instanceof Error ? error.message : error}\n`)
        }
        // 更新日志（What's New）：版本变化时弹一次原生提示（首次运行与测试/E2E 模式跳过）。
        if (!process.env.XCAGI_DESKTOP_TEST && !isE2ERun) {
          const releaseNote = consumeReleaseNotes()
          if (releaseNote && !releaseNote.isFirstRun) {
            const fromText = releaseNote.fromVersion ? `（${releaseNote.fromVersion} → ${releaseNote.toVersion}）` : ''
            const options: Electron.MessageBoxOptions = {
              type: 'info',
              title: `XCAGI 已更新${fromText}`,
              message: `XCAGI 已更新到 v${releaseNote.toVersion}`,
              detail: releaseNote.notes,
              buttons: ['知道了'],
              defaultId: 0,
            }
            const mainWindow = desktopRuntime.mainWindow
            if (mainWindow && !mainWindow.isDestroyed()) {
              void dialog.showMessageBox(mainWindow, options)
            } else {
              void dialog.showMessageBox(options)
            }
          }
        }
        // 启动自治控制器（与现有更新观察期/backend 重启逻辑共存，零回归）
        // 控制器提供新增能力：5min 内 backend 崩溃 ≥3 次自动回滚、磁盘满自动清日志、配置漂移自动纠正
        try {
          const adapter = new DesktopAutonomyAdapter({
            backendProcessRef: () => {
              const backendProcess = desktopRuntime.backendProcess
              if (!backendProcess) return null
              const pid = backendProcess.pid ?? null
              const startedAt = desktopRuntime.startupMarks.backendSpawnMs ?? null
              return { pid, running: true, startedAt }
            },
            restartCountRef: () => desktopRuntime.restartCount,
            port: DEFAULT_PORT,
            appVersion: app.getVersion(),
            buildSha: readLocalBuildSha(),
            configPath: null,
            // Phase 1：注入 backend 重启 / 版本回滚闭包
            // restartBackend 调用 startBackend()；backend exit 时 backendProcess 已被清空，可直接 spawn
            restartBackend: async () => { await startBackend() },
            // triggerRollback 复用现有 triggerRollbackSafe 吞错语义
            triggerRollback: async () => { await triggerRollbackSafe('autonomy_controller_triggered') },
            // knownGoodConfigContent 当前为 null（桌面端暂无配置文件概念，repair_config 自动拒绝）
            knownGoodConfigContent: null,
          })
          desktopRuntime.autonomyController = new AutonomyController(
            adapter,
            [backendCrashPolicy, degradedRemediationPolicy, updateRollbackPolicy],
            {
              enabled: !process.env.XCAGI_DESKTOP_TEST && !isE2ERun,
              pollIntervalMs: 5_000,
            },
          )
          desktopRuntime.autonomyController.start()
          writeBackendLog(`[autonomy] controller started\n`)
        } catch (e) {
          writeBackendLog(`[autonomy] controller start failed: ${e instanceof Error ? e.message : e}\n`)
        }
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error)
        writeBackendLog(`[rollback] 桌面启动失败: ${msg}\n`)
        if (pendingRollback) {
          const rollback = await triggerRollbackSafe(`桌面启动失败: ${msg}`)
          void dialog.showErrorBox(
            'XCAGI',
            !rollback
              ? '更新后启动失败，自动回滚也未能启动。请从官网下载稳定版重新安装。'
              : rollback.scheduled
                ? '更新后启动失败，正在恢复上一版本；XCAGI 将自动重启。'
                : msg.includes('createWindow') || msg.includes('窗口')
                  ? '更新后窗口创建失败，已恢复上一版本。请重启 XCAGI。'
                  : '更新后后端启动失败，已恢复上一版本。请重启 XCAGI。',
          )
        } else {
          void dialog.showErrorBox('XCAGI', msg)
        }
        app.quit()
      }
    })

    app.on('activate', () => {
      const mainWindow = desktopRuntime.mainWindow
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.show()
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.focus()
        return
      }
      if (BrowserWindow.getAllWindows().length === 0) {
        void createWindow()
      }
    })
  }
}

// 单测环境设置 XCAGI_DESKTOP_TEST=1 跳过启动逻辑，只测纯函数
if (!process.env.XCAGI_DESKTOP_TEST) {
  bootstrap()
}

export const __test_only = {
  createTray,
  handleBackendSpawnError,
}

// ---------------------------------------------------------------------------
// re-export 桶：main.ts 拆分前这些符号均由 main 导出，保留入口兼容
// （main.test.ts 及历史引用以 './main.js' 为入口，新代码请直接从各模块导入）。
// ---------------------------------------------------------------------------
export {
  OTA_PROXY_BYPASS_RULES,
  readWindowsInternetProxy,
  buildOtaPacScript,
  parseProxyEndpoint,
  isProxyEndpointReachable,
  isProxyEndpointReachableSync,
  resolveSystemProxyBypassMode,
  applyOtaProxyBypass,
} from './ota-proxy'
export {
  APP_NAME,
  DEFAULT_PORT,
  DESKTOP_BACKEND_BIND_HOST,
  SKU_RUNTIME_EDITION,
  SKU_UPDATE_URL,
  ED25519_PUBLIC_KEY_PEM,
  resolveDefaultDesktopPort,
  resolveDesktopBackendBindHost,
  isPortAvailable,
  portOccupiedHint,
  desktopInitialUrl,
  readPackagedProductSku,
  backendEditionEnv,
  readPackagedAppVersion,
  readFrontendCacheKey,
  shouldClearFrontendCache,
  markFrontendCacheCleared,
} from './desktop-config'
export {
  waitForBackendPing,
  waitForBackendHealth,
  waitForBackendApplicationReady,
} from './backend-process'
export {
  clampSplashProgress,
  updateSplashProgress,
  resolveDesktopSplashUrl,
} from './window-manager'
export { resolveDesktopCspInjection } from './session-security'
export {
  getAutoLaunchEnabled,
  setAutoLaunchEnabled,
  consumeReleaseNotes,
  captureFullScreenScreenshot,
} from './app-shell'
export type { ProductSku } from './desktop-config'

declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean
    }
  }
}
