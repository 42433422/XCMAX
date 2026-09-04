import { app } from 'electron'
import { autoUpdater } from 'electron-updater'
import { resolveDesktopInstallIdentity } from './installation-identity'
import { getDownloadedUpdateState } from './updater'
import {
  appendUpdaterEvent,
  discardPendingUpdateInstallReceipt,
  stageUpdateInstallReceipt,
} from './update-install-receipts'

/**
 * OTA may only replace the one official macOS application copy. A DMG-mounted
 * app or an internal acceptance copy has the same bundle id and user data, but
 * allowing it to self-update would leave two competing XCAGI installations.
 */
export function getDesktopInstallIdentity() {
  return resolveDesktopInstallIdentity({
    platform: process.platform,
    isPackaged: app.isPackaged,
    executablePath: process.execPath,
  })
}

export function assertSelfUpdateInstallSupported(): void {
  const identity = getDesktopInstallIdentity()
  if (!identity.canSelfUpdate) {
    throw new Error(identity.reason || '当前安装副本不支持在线更新')
  }
}

export async function installUpdate(
  beforeInstall?: (toVersion: string) => Promise<void>,
  onInstallFailed?: () => Promise<void> | void,
  prepareQuit?: () => Promise<void> | void,
): Promise<void> {
  const state = getDownloadedUpdateState()
  if (!state.downloaded) {
    throw new Error('尚未下载更新包，请先在更新面板确认下载')
  }
  try {
    if (beforeInstall) {
      const version = state.version || 'unknown'
      const identity = state.buildSha ? `${version}+${state.buildSha.slice(0, 12)}` : version
      await beforeInstall(identity)
    }
    stageUpdateInstallReceipt({ targetVersion: state.version || 'unknown', targetBuildSha: state.buildSha, channel: process.env.XCAGI_UPDATE_CHANNEL })
    appendUpdaterEvent('install_start', {})
    // macOS 原生 quitAndInstall 经 [NSApp terminate] 触发退出，will-quit 中的异步
    // 后端优雅关闭在该路径下不可靠，会致 ShipIt 无限等待（2026-09-03 实测）。
    // 先在 JS 层同步等待后端停止，再交出退出控制权。
    if (prepareQuit) {
      await prepareQuit()
    }
    autoUpdater.quitAndInstall(false, true)
  } catch (error) {
    discardPendingUpdateInstallReceipt()
    let cleanupError: unknown
    try {
      await onInstallFailed?.()
    } catch (caught) {
      cleanupError = caught
    }
    appendUpdaterEvent('install_failed', {
      message: error instanceof Error ? error.message : String(error),
      cleanupError: cleanupError instanceof Error ? cleanupError.message : String(cleanupError || ''),
    })
    if (cleanupError) {
      throw new Error(
        `${error instanceof Error ? error.message : String(error)}；清理回滚准备失败：${
          cleanupError instanceof Error ? cleanupError.message : String(cleanupError)
        }`,
      )
    }
    throw error
  }
}
