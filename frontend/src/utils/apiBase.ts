import { XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY } from './xcagiStorageKeys'

/**
 * Mod 列表、loading-status、routes 等读请求上限。
 * 冷启动时 lifespan 中 load_all_mods + 数据库初始化可能超过 1min；并行启动后仍可能偶发较慢，故与路由预取对齐放宽。
 */
export const DEFAULT_MOD_API_TIMEOUT_MS = 180_000

export type ApiFetchInit = RequestInit & { timeoutMs?: number }

/** 是否为 ``apiFetch`` 的限时中止（便于友好提示，避免控制台刷屏成「失败」） */
export function isApiFetchTimeoutError(e: unknown): boolean {
  if (e instanceof DOMException && e.name === 'AbortError') {
    return e.message.includes('apiFetch timeout')
  }
  if (e instanceof Error && e.name === 'AbortError') {
    return e.message.includes('apiFetch timeout')
  }
  return false
}

function mergeAbortSignals(a: AbortSignal, b: AbortSignal): AbortSignal {
  if (a.aborted) return a
  if (b.aborted) return b
  const c = new AbortController()
  const kick = (src: AbortSignal) => {
    if (!c.signal.aborted) {
      try {
        c.abort(src.reason)
      } catch {
        c.abort()
      }
    }
  }
  a.addEventListener('abort', () => kick(a), { once: true })
  b.addEventListener('abort', () => kick(b), { once: true })
  return c.signal
}

/**
 * Mod 等 API 的基址。
 * - 未设置时：用相对路径（与页面同源）。Vite dev（如 :5001）下走 vite.config 里 /api 代理。
 * - 生产/特殊联调可设 ``VITE_API_BASE`` / ``VITE_API_BASE_URL`` 为完整 API 源（非本机 loopback）。
 *
 * Loopback 基址特例：构建或环境里常写 ``http://127.0.0.1:5000``。若用户用局域网 IP 打开页面
 * （如 ``http://192.168.*.*:5001`` 或 FastAPI 托管的 ``:5000``），浏览器仍请求 127.0.0.1 会构成跨域，
 * ``credentials: 'include'`` 下 CORS 须精确匹配 Origin，易整页 ``Failed to fetch``。
 * 故对 **纯 loopback/localhost** 的 API 基址一律改走相对路径 ``/api``（与当前页面同源）。
 */
export function getApiBase(): string {
  const a = import.meta.env.VITE_API_BASE as string | undefined
  const b = import.meta.env.VITE_API_BASE_URL as string | undefined
  const raw = (typeof a === 'string' && a.trim() ? a : b) as string | undefined
  if (typeof raw === 'string' && raw.trim()) {
    const base = raw.trim().replace(/\/$/, '')
    if (/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(base)) {
      return ''
    }
    return base
  }
  return ''
}

/** 与当前站点同源的 API 路径，或 dev 下拼到后端根 */
export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const base = getApiBase()
  return base ? `${base}${p}` : p
}

export function getClientModsUiOffHeader(): Record<string, string> {
  try {
    const off = localStorage.getItem('xcagi_client_mods_ui_off') === '1';
    return off ? { 'X-Client-Mods-Off': '1' } : {};
  } catch {
    return {};
  }
}

/** 与 ``installFetchDbReadToken`` / 业务库按 Mod 分表一致；签名由服务端 dev 模式放宽校验。 */
export function getActiveExtensionModHeaders(): Record<string, string> {
  try {
    const id = String(localStorage.getItem(XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY) || '').trim();
    if (!id) return {};
    return { 'X-XCAGI-Active-Mod-Id': id };
  } catch {
    return {};
  }
}

/** 与 ``vite.config.js`` 中 /api 代理 target 一致；仅作 DEV 下网络失败时的单次回退。 */
const DEV_API_LOOPBACK_FALLBACK = 'http://127.0.0.1:5000'

function canRetryApiOnDevLoopback(originalInput: string): boolean {
  if (!import.meta.env.DEV) return false
  if (getApiBase() !== '') return false
  if (typeof window === 'undefined') return false
  const h = window.location.hostname
  if (h !== '127.0.0.1' && h !== 'localhost') return false
  if (/^https?:\/\//i.test(originalInput)) return false
  const path = originalInput.startsWith('/') ? originalInput : `/${originalInput}`
  return path.startsWith('/api/')
}

/** 与 ``pushClientModsOffState`` 一致：原版模式开关涉及 UI 回滚，不宜过短；后台同步与之对齐。 */
const CLIENT_MODS_OFF_SYNC_TIMEOUT_MS = 25_000

export function apiFetch(input: string, init?: ApiFetchInit): Promise<Response> {
  const url = input.startsWith('http') ? input : apiUrl(input)
  const {
    timeoutMs,
    signal: userSignal,
    headers: userHeaders,
    ...rest
  } = init || {}

  const modsOffHeaders = getClientModsUiOffHeader()
  const modScopeHeaders = getActiveExtensionModHeaders()
  const headers = {
    ...modsOffHeaders,
    ...modScopeHeaders,
    ...userHeaders,
  }

  let timeoutId: number | undefined
  let signal = userSignal

  if (typeof timeoutMs === 'number' && timeoutMs > 0) {
    const to = new AbortController()
    timeoutId = window.setTimeout(() => {
      to.abort(new DOMException(`apiFetch timeout after ${timeoutMs}ms`, 'AbortError'))
    }, timeoutMs)
    signal = userSignal ? mergeAbortSignals(userSignal, to.signal) : to.signal
  }

  const fetchInit = { ...rest, headers, signal }

  const perform = async (): Promise<Response> => {
    try {
      return await fetch(url, fetchInit)
    } catch (e) {
      if (canRetryApiOnDevLoopback(input)) {
        const path = input.startsWith('/') ? input : `/${input}`
        return fetch(`${DEV_API_LOOPBACK_FALLBACK}${path}`, fetchInit)
      }
      throw e
    }
  }

  const p = perform()

  if (timeoutId != null) {
    return p.finally(() => {
      window.clearTimeout(timeoutId!)
    })
  }
  return p
}

const STATE_KEY = 'xcagi_client_mods_ui_off'

/** 设置页切换「原版模式」时使用：失败则抛错以便回滚 UI，不静默 reload */
export async function pushClientModsOffState(clientModsOff: boolean): Promise<void> {
  const res = await apiFetch('/api/state/client-mods-off', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_mods_off: clientModsOff }),
    timeoutMs: CLIENT_MODS_OFF_SYNC_TIMEOUT_MS,
  })
  if (!res.ok) {
    const err = new Error(`同步原版模式失败（HTTP ${res.status}）`)
    console.warn('[apiBase]', err.message)
    throw err
  }
}

export function syncClientModsStateToBackend(): Promise<void> {
  const isOff = localStorage.getItem(STATE_KEY) === '1'
  return apiFetch('/api/state/client-mods-off', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_mods_off: isOff }),
    timeoutMs: CLIENT_MODS_OFF_SYNC_TIMEOUT_MS,
  }).then(res => {
    if (!res.ok) {
      console.warn('[apiBase] 同步原版模式状态到后端失败:', res.status)
    }
  }).catch(err => {
    // 启动阶段后端 / 代理未就绪时易触发限时中止；此为后台同步，避免 console.warn 刷屏并经 clientDebugLog 镜像到服务端
    if (isApiFetchTimeoutError(err)) {
      if (import.meta.env.DEV) {
        console.debug(
          '[apiBase] 同步原版模式状态超时（后端或代理可能仍在启动）；可刷新页面或在设置中再次切换原版模式',
          err
        )
      }
      return
    }
    console.warn('[apiBase] 同步原版模式状态到后端失败:', err)
  })
}

export function readClientModsOffState(): boolean {
  return localStorage.getItem(STATE_KEY) === '1'
}
