/**
 * C21–C30 客户端稳定性契约。
 * 网络恢复只表示传输恢复；工具调用和写入在结果未知时不能当成成功，也不能自动再执行。
 */

export type StabilityAction = 'retry' | 'relogin' | 'admin' | 'check_result'

export interface StabilityNotice {
  kind: string
  message: string
  action: StabilityAction
  success: false
}

export const OPERATION_TIMEOUT_MS = {
  health: 3_000,
  erpRead: 10_000,
  chat: 30_000,
  tool: 30_000,
  upload: 30_000,
  download: 30_000,
} as const

const NOTICES: Record<string, { message: string; action: StabilityAction }> = {
  offline: { message: '当前网络已断开。请检查网络后重试。', action: 'retry' },
  server_down: { message: '服务暂时不可用。请稍后重试，无需重新登录。', action: 'retry' },
  token_expired: { message: '登录已过期，请重新登录。这不是网络故障。', action: 'relogin' },
  permission: { message: '当前账号没有权限。请联系管理员，不要当作网络错误重试。', action: 'admin' },
  timeout: { message: '请求超时，操作未成功。请重试；已提交的写入请先核对结果，勿重复提交。', action: 'check_result' },
  model_provider: { message: '模型服务暂时失败，本轮未成功。请稍后重试。', action: 'retry' },
  insufficient_balance: { message: '余额不足，操作未成功。请联系管理员充值后再试。', action: 'admin' },
  tool_failure: { message: '工具执行失败，未标记为成功。请查看任务状态后再决定是否重试。', action: 'check_result' },
  bad_tool_args: { message: '工具参数不正确，操作未执行。请修改后再试。', action: 'retry' },
  db_down: { message: '数据库暂时不可用，操作未成功。请联系管理员。', action: 'admin' },
  upload_failed: { message: '上传失败，文件未完成。请重试。', action: 'retry' },
  download_failed: { message: '下载失败，文件未完成。请重试。', action: 'retry' },
  backend_restart: { message: '服务正在重启。请稍后重试，无需重新登录。进行中的操作未成功。', action: 'retry' },
  interrupted: { message: '操作已中断，未标记为成功。请核对任务状态后再决定是否重试。', action: 'check_result' },
}

function notice(kind: string): StabilityNotice {
  const row = NOTICES[kind]
  return { kind, message: row.message, action: row.action, success: false }
}

export function classifyTransportFailure(input: {
  timeout?: boolean
  online?: boolean
  message?: string
  status?: number
  errorCode?: string
}): StabilityNotice {
  const message = String(input.message || '')
  const lower = message.toLowerCase()
  const code = String(input.errorCode || '').toLowerCase()
  if (code && NOTICES[code]) return notice(code)
  if (input.status === 401 || code === 'http_401') return notice('token_expired')
  if (input.status === 403 || code === 'permission' || code === 'http_403') return notice('permission')
  if (code === 'insufficient_balance' || message.includes('余额不足')) return notice('insufficient_balance')
  if (code === 'model_provider' || message.includes('模型服务') || message.includes('模型连接')) return notice('model_provider')
  if (code === 'bad_tool_args') return notice('bad_tool_args')
  if (code === 'tool_failure') return notice('tool_failure')
  if (code === 'db_down' || message.includes('数据库不可用')) return notice('db_down')
  if (code === 'upload_failed') return notice('upload_failed')
  if (code === 'download_failed') return notice('download_failed')
  if (code === 'backend_restart' || message.includes('正在重启')) return notice('backend_restart')
  if (input.timeout || message.includes('请求超时') || lower.includes('timeout') || lower.includes('timed out')) {
    return notice('timeout')
  }
  if (input.online === false || lower.includes('offline') || message.includes('离线') || message.includes('网络已断开')) {
    return notice('offline')
  }
  if (lower.includes('econnrefused') || message.includes('连接被拒绝')) return notice('server_down')
  if (lower.includes('failed to fetch') || lower.includes('networkerror') || lower.includes('network')) {
    return notice('server_down')
  }
  return notice('server_down')
}

/** 给已有产品文案用：保留「连不上电脑执行端」的中继口径，其余传输失败分开写。 */
export function classifyRawError(raw: string): string | null {
  const msg = raw.trim()
  const lower = msg.toLowerCase()
  if (!msg) return null
  if (lower.includes('401') || msg.includes('未授权') || msg.includes('未登录')) return null
  if (lower.includes('403') || msg.includes('无权限')) return null
  if (lower.includes('failed to connect')) return null
  if (lower.includes('etimedout') || msg.includes('请求超时') || lower.includes('timeout') || lower.includes('timed out') || lower.includes('timedout')) {
    return notice('timeout').message
  }
  if (lower.includes('econnrefused') || msg.includes('连接被拒绝') || msg.includes('正在重启')) return notice('backend_restart').message
  if (
    lower.includes('failed to fetch')
    || lower.includes('networkerror')
    || lower.includes('network')
    || lower.includes('offline')
    || msg.includes('离线')
  ) {
    return notice('offline').message
  }
  if (msg.includes('余额不足')) return notice('insufficient_balance').message
  if (msg.includes('数据库不可用')) return notice('db_down').message
  return null
}

export function createTraceId(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return cryptoObj.randomUUID().replace(/-/g, '')
  }
  return `trace${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`
}

const recentSubmits = new Map<string, number>()

export function isDuplicateUnsafeSubmit(key: string, now = Date.now(), windowMs = 800): boolean {
  const prev = recentSubmits.get(key)
  recentSubmits.set(key, now)
  if (recentSubmits.size > 200) {
    const cutoff = now - windowMs
    for (const [item, at] of recentSubmits) {
      if (at < cutoff) recentSubmits.delete(item)
    }
  }
  return prev != null && now - prev < windowMs
}

export function resetUnsafeSubmitGuard(): void {
  recentSubmits.clear()
}

export class RefreshSingleFlight {
  private inflight: Promise<boolean> | null = null
  private refresher: (() => Promise<boolean>) | null = null
  calls = 0

  setRefresher(fn: (() => Promise<boolean>) | null): void {
    this.refresher = fn
  }

  get enabled(): boolean {
    return this.refresher != null
  }

  run(): Promise<boolean> {
    if (!this.refresher) return Promise.resolve(false)
    if (!this.inflight) {
      this.calls += 1
      const job = this.refresher()
      this.inflight = Promise.resolve(job)
        .then((ok) => ok === true)
        .catch(() => false)
        .finally(() => {
          this.inflight = null
        })
    }
    return this.inflight
  }
}

type SideState = 'running' | 'succeeded' | 'unknown' | 'failed'

function unknownOutcome(error: unknown): boolean {
  const status = Number((error as { status?: number } | null)?.status)
  const data = (error as { data?: { stability?: { kind?: string } } } | null)?.data
  const kind = data?.stability?.kind || ''
  if (kind === 'timeout' || kind === 'offline' || kind === 'server_down' || kind === 'backend_restart' || kind === 'interrupted') {
    return true
  }
  return status === 0
}

export class SideEffectGate {
  private entries = new Map<string, { state: SideState; promise?: Promise<unknown>; result?: unknown }>()

  submit<T>(key: string, run: () => Promise<T>, confirmUnknown = false): Promise<T> {
    const existing = this.entries.get(key)
    if (existing?.state === 'running' && existing.promise) return existing.promise as Promise<T>
    if (existing?.state === 'succeeded') return Promise.resolve(existing.result as T)
    if (existing?.state === 'unknown' && !confirmUnknown) {
      return Promise.reject(new Error('结果未知，请先核对服务端后再提交。该操作未标记为成功。'))
    }
    const promise = run()
      .then((result) => {
        this.entries.set(key, { state: 'succeeded', result })
        return result
      })
      .catch((error: unknown) => {
        this.entries.set(key, { state: unknownOutcome(error) ? 'unknown' : 'failed' })
        throw error
      })
    this.entries.set(key, { state: 'running', promise })
    return promise
  }
}

export class SseConnectionRegistry {
  live = 0
  opened = 0
  closed = 0
  private attempts = new Map<string, number>()
  readonly maxReconnects = 12

  open(id: string): void {
    this.live += 1
    this.opened += 1
    this.attempts.set(id, 0)
  }

  close(id: string): void {
    if (!this.attempts.has(id)) return
    this.attempts.delete(id)
    this.live = Math.max(0, this.live - 1)
    this.closed += 1
  }

  allowReconnect(id: string): boolean {
    const used = this.attempts.get(id) ?? 0
    if (used >= this.maxReconnects) return false
    this.attempts.set(id, used + 1)
    return true
  }

  noteConnected(id: string): void {
    this.attempts.set(id, 0)
  }
}

export const sseConnections = new SseConnectionRegistry()

const STABILITY_NOTICE_ID = 'stability-notice'
/** 首次失败先静默观察；这段时间内恢复就不打扰用户。 */
const TRANSIENT_GRACE_MS = 4_000
let pendingNoticeTimer: number | undefined
let consecutiveFailures = 0

export function dismissStabilityNotice(): void {
  if (typeof document === 'undefined') return
  document.getElementById(STABILITY_NOTICE_ID)?.remove()
}

function clearPendingNotice(): void {
  if (pendingNoticeTimer !== undefined) {
    window.clearTimeout(pendingNoticeTimer)
    pendingNoticeTimer = undefined
  }
}

/**
 * 传输失败只在持续存在或用户操作受阻时轻量提示：
 * 单次失败静默 4 秒，期间恢复则不出现任何提示；连续失败立即提示。
 */
export function noteTransportFailure(message: string): void {
  consecutiveFailures += 1
  if (typeof window === 'undefined') return
  if (consecutiveFailures >= 2) {
    clearPendingNotice()
    publishStabilityNotice(message)
    return
  }
  if (pendingNoticeTimer !== undefined) return
  pendingNoticeTimer = window.setTimeout(() => {
    pendingNoticeTimer = undefined
    publishStabilityNotice(message)
  }, TRANSIENT_GRACE_MS)
}

/** 任意请求成功即视为服务已恢复：撤掉提示，不留下任何遮挡。 */
export function noteTransportSuccess(): void {
  consecutiveFailures = 0
  if (typeof window === 'undefined') return
  clearPendingNotice()
  dismissStabilityNotice()
}

/**
 * 桌面壳的后端恢复通知：就绪后撤掉提示并广播事件，页面自行重取数据。
 * 不做整页刷新，用户已输入的内容与滚动位置都保留。
 */
export function installBackendHealthBridge(): void {
  if (typeof window === 'undefined') return
  const subscribe = window.xcagiDesktop?.onBackendHealth
  if (typeof subscribe !== 'function') return
  subscribe((state) => {
    if (state !== 'ready') return
    noteTransportSuccess()
    window.dispatchEvent(new CustomEvent('xcagi:backend-ready'))
  })
}

export function publishStabilityNotice(message: string): void {
  if (typeof document === 'undefined') return
  const text = message.trim()
  if (!text) return
  let node = document.getElementById(STABILITY_NOTICE_ID)
  if (!node) {
    node = document.createElement('div')
    node.id = STABILITY_NOTICE_ID
    node.setAttribute('role', 'alert')
    node.style.cssText = 'position:fixed;z-index:100000;bottom:20px;left:50%;transform:translateX(-50%);max-width:min(560px,92vw);display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:10px;background:#fff7e6;border:1px solid #f0d9a8;color:#5c3d00;font-size:14px;line-height:1.45;box-shadow:0 6px 18px rgba(0,0,0,.12);'
    document.body.appendChild(node)
  }
  node.textContent = ''
  const label = document.createElement('span')
  label.textContent = text
  const retry = document.createElement('button')
  retry.type = 'button'
  retry.textContent = '重试'
  retry.style.cssText = 'flex:0 0 auto;border:0;border-radius:6px;padding:4px 12px;background:#3b6fd9;color:#fff;font-size:13px;cursor:pointer;'
  retry.addEventListener('click', () => {
    dismissStabilityNotice()
    consecutiveFailures = 0
    window.dispatchEvent(new CustomEvent('xcagi:stability-retry'))
  })
  node.append(label, retry)
}
