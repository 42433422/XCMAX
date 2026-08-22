/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}

interface Window {
  xcagiDesktop?: {
    platform: NodeJS.Platform
    versions: Record<string, string>
    getAppIdentity?: () => Promise<{
      name?: string
      version?: string
      isPackaged?: boolean
      install?: {
        appPath?: string | null
        canonicalAppPath?: string | null
        isCanonical?: boolean
        canSelfUpdate?: boolean
        reason?: string
      }
    }>
    getDataDir: () => Promise<string>
    /** One-shot, local-only renderer entry hint from Electron's persisted cookie store. */
    consumeBootstrapSessionHint?: () => Promise<boolean>
    checkForUpdates: () => Promise<unknown>
    getUpdateStatus?: () => Promise<{ type: string; data?: unknown } | null>
    downloadUpdate: () => Promise<unknown>
    installUpdate: () => Promise<void>
    onUpdateEvent: (callback: (event: unknown) => void) => () => void
    getPairingQrPayload?: () => Promise<string>
    showNotification: (title: string, body: string) => Promise<void>
    setBadge: (count: number) => Promise<void>
    getAutoLaunch?: () => Promise<boolean>
    setAutoLaunch?: (enabled: boolean) => Promise<{ ok: boolean; reason?: string }>
    /** @returns pending xcagi:// deep link URL once, or null. */
    consumeDeepLink?: () => Promise<string | null>
    onDeepLink?: (callback: (url: string) => void) => () => void
    onVoiceInvoke?: (callback: () => void) => () => void
  }
  handleAutoAction?: (action: unknown, userMessage?: string) => void
}
