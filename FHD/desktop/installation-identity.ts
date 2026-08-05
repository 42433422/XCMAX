import path from 'node:path'

export const CANONICAL_MAC_APP_PATH = '/Applications/XCAGI.app'

export type DesktopInstallIdentity = {
  appPath: string | null
  canonicalAppPath: string | null
  isCanonical: boolean
  canSelfUpdate: boolean
  reason?: string
}

/**
 * Return the outer .app bundle for an Electron executable.  It is deliberately
 * based on the executable path instead of the current working directory: DMG
 * mounts, temporary acceptance copies and /Applications can otherwise share
 * the same bundle id while being different application instances.
 */
export function macAppBundlePathFromExecutable(executablePath: string): string | null {
  const normalized = path.resolve(executablePath || '')
  const marker = `${path.sep}Contents${path.sep}MacOS${path.sep}`
  const index = normalized.lastIndexOf(marker)
  if (index <= 0) return null
  const bundlePath = normalized.slice(0, index)
  return bundlePath.endsWith('.app') ? bundlePath : null
}

export function resolveDesktopInstallIdentity(input: {
  platform: NodeJS.Platform
  isPackaged: boolean
  executablePath: string
  canonicalMacAppPath?: string
}): DesktopInstallIdentity {
  if (!input.isPackaged) {
    return {
      appPath: null,
      canonicalAppPath: null,
      isCanonical: true,
      canSelfUpdate: false,
      reason: 'development-build',
    }
  }
  if (input.platform !== 'darwin') {
    return {
      appPath: null,
      canonicalAppPath: null,
      isCanonical: true,
      canSelfUpdate: true,
    }
  }

  const appPath = macAppBundlePathFromExecutable(input.executablePath)
  const canonicalAppPath = path.resolve(input.canonicalMacAppPath || CANONICAL_MAC_APP_PATH)
  const isCanonical = Boolean(appPath && path.resolve(appPath) === canonicalAppPath)
  return {
    appPath,
    canonicalAppPath,
    isCanonical,
    canSelfUpdate: isCanonical,
    ...(isCanonical
      ? {}
      : {
          reason:
            '当前 XCAGI 不是“应用程序”目录中的正式安装副本。请通过安装包替换 /Applications/XCAGI.app 后再使用在线更新。',
        }),
  }
}
