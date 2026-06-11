/**
 * AIOPEN 虚拟光标（screen 端）。
 *
 * 开启「远程操控」后连接 `WS /api/aiopen/ws`，接收外部 AI Agent 经
 * MCP / REST 下发的 ui_* 指令（snapshot / navigate / click / type / scroll），
 * 以可视化虚拟光标在页面上真实执行，并按 `id` 回传回执。
 *
 * 模块级单例：VirtualCursorOverlay（App.vue 挂载）与 AIOpenPanel 共享状态。
 */
import { ref } from 'vue'
import type { Router } from 'vue-router'
import { getApiBase } from '@/utils/apiBase'

const STORAGE_KEY = 'xcagi_aiopen_remote_control'
const MAX_LOGS = 100
const SNAPSHOT_MAX_ELEMENTS = 120
const CURSOR_MOVE_MS = 480

export const aiopenCursorEnabled = ref(false)
export const aiopenCursorConnected = ref(false)
export const aiopenCursorSessionId = ref('')
export const aiopenCursorLogs = ref<string[]>([])

export const cursorX = ref(0)
export const cursorY = ref(0)
export const cursorVisible = ref(false)
export const cursorClicking = ref(false)
export const cursorActionLabel = ref('')

let ws: WebSocket | null = null
let routerRef: Router | null = null
let reconnectTimer: number | null = null

function pushLog(text: string) {
  const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  aiopenCursorLogs.value.push(`[${ts}] ${text}`)
  const overflow = aiopenCursorLogs.value.length - MAX_LOGS
  if (overflow > 0) aiopenCursorLogs.value.splice(0, overflow)
}

function wsUrl(): string {
  const base = getApiBase()
  const origin = base || (typeof window !== 'undefined' ? window.location.origin : '')
  const httpOrigin = origin || 'http://127.0.0.1:5000'
  return httpOrigin.replace(/^http/i, 'ws') + '/api/aiopen/ws'
}

// ---------------------------------------------------------------------------
// 元素定位与选择器
// ---------------------------------------------------------------------------

function isVisible(el: Element): boolean {
  const rect = (el as HTMLElement).getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return false
  if (rect.bottom < 0 || rect.top > window.innerHeight) return false
  const style = window.getComputedStyle(el as HTMLElement)
  return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05
}

function buildSelector(el: Element): string {
  if (el.id) return `#${CSS.escape(el.id)}`
  const parts: string[] = []
  let node: Element | null = el
  let depth = 0
  while (node && node !== document.body && depth < 6) {
    let part = node.tagName.toLowerCase()
    if (node.id) {
      parts.unshift(`#${CSS.escape(node.id)}`)
      break
    }
    const parent: Element | null = node.parentElement
    if (parent) {
      const sameTag = Array.from(parent.children).filter((c) => c.tagName === node!.tagName)
      if (sameTag.length > 1) {
        part += `:nth-of-type(${sameTag.indexOf(node) + 1})`
      }
    }
    parts.unshift(part)
    node = parent
    depth += 1
  }
  return parts.join(' > ')
}

function elementText(el: Element): string {
  const raw = (el as HTMLElement).innerText || (el as HTMLInputElement).value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || ''
  return raw.replace(/\s+/g, ' ').trim().slice(0, 80)
}

function findElement(selector?: string, text?: string): HTMLElement | null {
  if (selector) {
    try {
      const el = document.querySelector(selector)
      if (el) return el as HTMLElement
    } catch {
      /* invalid selector → fall through to text match */
    }
  }
  if (text) {
    const needle = text.trim()
    const candidates = document.querySelectorAll('button, a, [role="button"], input, label, .app-launcher')
    for (const el of Array.from(candidates)) {
      if (isVisible(el) && elementText(el).includes(needle)) return el as HTMLElement
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// 指令执行
// ---------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function animateCursorTo(x: number, y: number, label: string): Promise<void> {
  cursorVisible.value = true
  cursorActionLabel.value = label
  cursorX.value = x
  cursorY.value = y
  await sleep(CURSOR_MOVE_MS + 60)
}

async function execSnapshot(): Promise<Record<string, unknown>> {
  const selectorList = 'button, a[href], input, textarea, select, [role="button"], [role="tab"], [role="menuitem"]'
  const elements: Array<Record<string, unknown>> = []
  for (const el of Array.from(document.querySelectorAll(selectorList))) {
    if (!isVisible(el)) continue
    const rect = (el as HTMLElement).getBoundingClientRect()
    elements.push({
      selector: buildSelector(el),
      tag: el.tagName.toLowerCase(),
      text: elementText(el),
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
    })
    if (elements.length >= SNAPSHOT_MAX_ELEMENTS) break
  }
  return {
    success: true,
    url: window.location.href,
    route: routerRef?.currentRoute.value.fullPath || '',
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    elements,
  }
}

async function execNavigate(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const path = String(params.path || '').trim()
  if (!path) return { success: false, message: 'path 不能为空' }
  if (!routerRef) return { success: false, message: 'router 未就绪' }
  await routerRef.push(path)
  await sleep(400)
  return { success: true, route: routerRef.currentRoute.value.fullPath }
}

async function execClick(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const selector = params.selector ? String(params.selector) : undefined
  const text = params.text ? String(params.text) : undefined
  const el = findElement(selector, text)
  if (!el) return { success: false, message: `未找到元素：${selector || text || '(空)'}` }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await sleep(260)
  const rect = el.getBoundingClientRect()
  await animateCursorTo(rect.x + rect.width / 2, rect.y + rect.height / 2, '点击')
  cursorClicking.value = true
  await sleep(180)
  el.click()
  cursorClicking.value = false
  pushLog(`click → ${elementText(el) || selector || text}`)
  return { success: true, clicked: elementText(el) || selector || text }
}

async function execType(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const selector = String(params.selector || '')
  const text = String(params.text ?? '')
  const el = findElement(selector)
  if (!el) return { success: false, message: `未找到输入框：${selector}` }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await sleep(260)
  const rect = el.getBoundingClientRect()
  await animateCursorTo(rect.x + rect.width / 2, rect.y + rect.height / 2, '输入')
  el.focus()
  const input = el as HTMLInputElement | HTMLTextAreaElement
  // 经原型 setter 写值，确保 Vue v-model 等响应式绑定能收到 input 事件
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (setter) {
    setter.call(input, text)
  } else {
    input.value = text
  }
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
  pushLog(`type → ${selector}（${text.slice(0, 30)}）`)
  return { success: true, selector, typed: text }
}

async function execScroll(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const selector = params.selector ? String(params.selector) : ''
  if (selector) {
    const el = findElement(selector)
    if (!el) return { success: false, message: `未找到元素：${selector}` }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    await sleep(320)
    return { success: true, scrolled_to: selector }
  }
  const deltaY = Number(params.delta_y || 0) || 300
  const scroller = document.querySelector('.route-view-shell, .main-content, main') || document.scrollingElement
  if (scroller) scroller.scrollBy({ top: deltaY, behavior: 'smooth' })
  await sleep(320)
  return { success: true, delta_y: deltaY }
}

async function executeCommand(action: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
  switch (action) {
    case 'snapshot':
      return execSnapshot()
    case 'navigate':
      return execNavigate(params)
    case 'click':
      return execClick(params)
    case 'type':
      return execType(params)
    case 'scroll':
      return execScroll(params)
    default:
      return { success: false, message: `未知指令：${action}` }
  }
}

// ---------------------------------------------------------------------------
// WebSocket 连接
// ---------------------------------------------------------------------------

function connect() {
  if (ws || !aiopenCursorEnabled.value) return
  try {
    ws = new WebSocket(wsUrl())
  } catch {
    pushLog('WS 创建失败')
    scheduleReconnect()
    return
  }
  ws.onopen = () => {
    aiopenCursorConnected.value = true
    pushLog('已连接 AIOPEN 操控通道')
  }
  ws.onmessage = async (event) => {
    let msg: Record<string, unknown> | null = null
    try {
      msg = JSON.parse(String(event.data || ''))
    } catch {
      return
    }
    if (!msg) return
    if (msg.type === 'hello') {
      aiopenCursorSessionId.value = String(msg.session_id || '')
      pushLog(`会话登记：${aiopenCursorSessionId.value}`)
      return
    }
    if (msg.type === 'command') {
      const action = String(msg.action || '')
      const params = (msg.params && typeof msg.params === 'object' ? msg.params : {}) as Record<string, unknown>
      pushLog(`收到指令：${action}`)
      let result: Record<string, unknown>
      try {
        result = await executeCommand(action, params)
      } catch (err) {
        result = { success: false, message: String((err as Error)?.message || err) }
      }
      if (action !== 'snapshot') {
        // 快照不收光标；操作类指令完成后短暂保留再淡出
        window.setTimeout(() => {
          cursorVisible.value = false
          cursorActionLabel.value = ''
        }, 1500)
      }
      try {
        ws?.send(JSON.stringify({ type: 'result', id: msg.id, result }))
      } catch {
        /* 连接已断，无法回执 */
      }
    }
  }
  ws.onclose = () => {
    aiopenCursorConnected.value = false
    aiopenCursorSessionId.value = ''
    ws = null
    if (aiopenCursorEnabled.value) {
      pushLog('连接断开，准备重连…')
      scheduleReconnect()
    }
  }
  ws.onerror = () => {
    /* onclose 统一处理 */
  }
}

function scheduleReconnect() {
  if (reconnectTimer != null || !aiopenCursorEnabled.value) return
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connect()
  }, 3000)
}

function disconnect() {
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    try {
      ws.close()
    } catch {
      /* already closed */
    }
    ws = null
  }
  aiopenCursorConnected.value = false
  aiopenCursorSessionId.value = ''
  cursorVisible.value = false
}

// ---------------------------------------------------------------------------
// 对外 API
// ---------------------------------------------------------------------------

export function setAiOpenCursorEnabled(enabled: boolean) {
  aiopenCursorEnabled.value = enabled
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    /* localStorage 不可用时忽略 */
  }
  if (enabled) {
    pushLog('远程操控已开启')
    connect()
  } else {
    pushLog('远程操控已关闭')
    disconnect()
  }
}

/** App.vue 内 VirtualCursorOverlay 调用：注入 router 并按持久化状态自动连接。 */
export function initAiOpenCursor(router: Router) {
  routerRef = router
  let persisted = false
  try {
    persisted = localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    persisted = false
  }
  if (persisted && !aiopenCursorEnabled.value) {
    aiopenCursorEnabled.value = true
    connect()
  }
}

export function useAiOpenCursor() {
  return {
    enabled: aiopenCursorEnabled,
    connected: aiopenCursorConnected,
    sessionId: aiopenCursorSessionId,
    logs: aiopenCursorLogs,
    setEnabled: setAiOpenCursorEnabled,
  }
}
