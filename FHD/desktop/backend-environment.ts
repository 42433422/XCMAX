import path from 'node:path'
import { app } from 'electron'

type PackagedProductSku = 'personal' | 'enterprise'

function sanitizeBackendProxyEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
): Record<string, string | undefined> {
  const next: Record<string, string | undefined> = { ...env }
  for (const key of ['ALL_PROXY', 'all_proxy'] as const) {
    const raw = String(next[key] || '').trim().toLowerCase()
    if (
      raw.startsWith('socks://')
      || raw.startsWith('socks4://')
      || raw.startsWith('socks5://')
      || raw.startsWith('socks5h://')
    ) {
      delete next[key]
    }
  }
  return next
}

export function resolveDesktopUserDataPath(appDataPath: string): string {
  const override = String(process.env.XCAGI_DESKTOP_USER_DATA_DIR || '').trim()
  const acceptanceProbe =
    process.env.XCAGI_DESKTOP_ACCEPTANCE_PROBE === '1' ||
    process.env.XCAGI_DESKTOP_TEST === '1'
  if (acceptanceProbe && override) {
    return path.resolve(override)
  }
  return path.join(appDataPath, 'XCAGI')
}

export function desktopChatTransportEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined> = process.env,
  isPackaged: boolean = app.isPackaged,
): Record<string, string> {
  if (!isPackaged) return {}

  const resolved: Record<string, string> = {}
  if (!String(env.XCAGI_MODSTORE_USE_NATIVE_STREAM || '').trim()) {
    resolved.XCAGI_MODSTORE_USE_NATIVE_STREAM = '0'
  }
  // The non-native request returns one synthetic SSE chunk only after the
  // model has finished.  Do not let a missing or inherited legacy 20s
  // native-first-token budget reject that valid request before the adapter
  // can surface a real provider response (for example quota exhaustion).
  // Keep an explicit value above 20s intact for operators who deliberately
  // tune the desktop budget.
  const configuredFirstTokenTimeout = Number(
    String(env.XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC || '').trim(),
  )
  if (
    !Number.isFinite(configuredFirstTokenTimeout) ||
    configuredFirstTokenTimeout <= 20
  ) {
    // The market adapter's synchronous fallback has a 60s transport timeout.
    // Leave a small margin so its structured provider error wins the race over
    // this UI-facing guard instead of being mislabeled as a first-token timeout.
    resolved.XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC = '75'
  }
  return resolved
}

export function buildDesktopBackendEnv(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
  userDataDir: string
): Record<string, string | undefined> {
  const next = sanitizeBackendProxyEnv(env)
  const dataDir = path.join(userDataDir, 'data')
  const desktopDatabaseUrl =
    String(next.XCAGI_DESKTOP_DATABASE_URL || '').trim() || `sqlite:///${path.join(dataDir, 'xcagi.db')}`
  const desktopVectorUrl =
    String(next.XCAGI_DESKTOP_VECTOR_DB_URL || '').trim() || desktopDatabaseUrl

  return {
    ...next,
    XCAGI_DESKTOP_MODE: '1',
    XCAGI_DATA_DIR: userDataDir,
    XCAGI_DESKTOP_DATA_DIR: userDataDir,
    DATABASE_PATH: dataDir,
    DATABASE_URL: desktopDatabaseUrl,
    VECTOR_DB_URL: desktopVectorUrl
  }
}

export function buildBackendEditionEnv(
  sku: PackagedProductSku | null,
  etlCenterOverride: string | undefined = process.env.FHD_ETL_CENTER_ENABLED,
): Record<string, string> {
  if (!sku) {
    return {
      XCAGI_PRODUCT_SKU: 'generic',
      XCAGI_GENERIC_EDITION: '1',
      XCAGI_PLATFORM_SHELL: '1',
      XCAGI_DEFAULT_EDITION: 'generic',
      FHD_ETL_CENTER_ENABLED: etlCenterOverride || '0',
    }
  }
  const edition = sku === 'personal' ? 'minimal' : 'full'
  const env: Record<string, string> = {
    XCAGI_PRODUCT_SKU: sku,
    XCAGI_PLATFORM_SHELL: sku === 'enterprise' ? '0' : '1',
    XCAGI_DEFAULT_EDITION: edition,
    XCAGI_EDITION: edition,
    FHD_ETL_CENTER_ENABLED: etlCenterOverride || (sku === 'enterprise' ? '1' : '0'),
  }
  if (edition === 'minimal') env.XCAGI_MINIMAL_EDITION = '1'
  return env
}
