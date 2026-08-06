import { app } from 'electron'
import { resolveDesktopInstallIdentity } from './installation-identity'

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
