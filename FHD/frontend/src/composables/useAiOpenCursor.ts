/**
 * AIOPEN 虚拟光标（screen 端）。
 *
 * 开启「远程操控」后连接 `WS /api/aiopen/ws`，接收外部 AI Agent 经
 * MCP / REST 下发的 ui_* 指令（snapshot / navigate / click / type / scroll），
 * 以可视化虚拟光标在页面上真实执行，并按 `id` 回传回执。
 *
 * 模块级单例：VirtualCursorOverlay（App.vue 挂载）与 AIOpenPanel 共享状态。
 */
import { ref, watch } from 'vue'
import type { Router } from 'vue-router'
import { getApiBase } from '@/utils/apiBase'
import { captureAuthSession } from '@/utils/authSessionCache'
import { disableTrail, ensureTrail, moveTrail, pulseTrail } from './useAiOpenCursorTrail'

const STORAGE_KEY = 'xcagi_aiopen_remote_control'
const MAX_LOGS = 100
const SNAPSHOT_MAX_ELEMENTS = 120
// 扫描上限：避免超长页面里为上方的隐藏节点付出整页遍历成本
const SNAPSHOT_MAX_SCAN = 3000
const CURSOR_MOVE_MS = 480
const WAIT_POLL_MS = 100
const WAIT_MAX_MS = 15000
// Match the longest server action budget, and bound every incoming envelope locally.
const COMMAND_MAX_MS = 30000
const SCREENSHOT_MAX_WIDTH = 1280
// Agent 操作时不应触发虚拟光标动画的指令
const SILENT_ACTIONS = new Set(['snapshot', 'wait', 'verify', 'screenshot'])

export const aiopenCursorEnabled = ref(false)
export const aiopenCursorConnected = ref(false)
export const aiopenCursorSessionId = ref('')
export const aiopenCursorLogs = ref<string[]>([])
/** 是否有 Agent 正在操作：默认静默待命，收到指令才显示光标与徽标。 */
export const aiopenAgentActive = ref(false)

export const cursorX = ref(0)
export const cursorY = ref(0)
export const cursorVisible = ref(false)
export const cursorClicking = ref(false)
export const cursorActionLabel = ref('')
/** 移动时的轻微倾斜，增加方向感（拖尾由 cursor-effects 负责）。 */
export const cursorTilt = ref(0)

const AGENT_IDLE_MS = 8000

let ws: WebSocket | null = null
let routerRef: Router | null = null
let reconnectTimer: number | null = null
let agentIdleTimer: number | null = null
let stopSessionWatch: (() => void) | null = null
let abortConnectionCommands: (() => void) | null = null

/** Agent 活动窗口：收到指令即点亮，静默一段时间后自动收起。 */
function markAgentActive() {
  aiopenAgentActive.value = true
  if (agentIdleTimer != null) window.clearTimeout(agentIdleTimer)
  agentIdleTimer = window.setTimeout(() => {
    agentIdleTimer = null
    aiopenAgentActive.value = false
  }, AGENT_IDLE_MS)
}

function clearAgentActive() {
  if (agentIdleTimer != null) {
    window.clearTimeout(agentIdleTimer)
    agentIdleTimer = null
  }
  aiopenAgentActive.value = false
}

function pushLog(text: string) {
  const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  aiopenCursorLogs.value.push(`[${ts}] ${text}`)
  const overflow = aiopenCursorLogs.value.length - MAX_LOGS
  if (overflow > 0) aiopenCursorLogs.value.splice(0, overflow)
}

function wsUrl(): string {
  // dev 下 dev server 与后端不同端口；代理改写 Host 会让长连接被提前断开，
  // 因此优先直连后端（仅 dev 注入），生产仍走同源。
  const devBase = String(import.meta.env.VITE_XCMAX_DEV_WS_BASE || '').trim()
  const base = devBase || getApiBase()
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
  // 大页面里逐个 getComputedStyle 很慢；优先用原生 checkVisibility，缺失时再回退。
  const probe = el as Element & {
    checkVisibility?: (options?: { checkOpacity?: boolean; checkVisibilityCSS?: boolean }) => boolean
  }
  if (typeof probe.checkVisibility === 'function') {
    return probe.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
  }
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
  if (isSensitiveElement(el)) return '[REDACTED]'
  // 不用 innerText：它会强制布局，在超大页面上逐个读取会让快照卡到超时。
  const raw =
    (el as HTMLInputElement).value ||
    el.getAttribute('aria-label') ||
    el.getAttribute('placeholder') ||
    el.textContent ||
    ''
  return raw.replace(/\s+/g, ' ').trim().slice(0, 80)
}

function isSensitiveElement(el: Element): boolean {
  return Boolean(el.closest('[data-aiopen-private]')) ||
    (el instanceof HTMLInputElement && (el.type === 'password' ||
      /(?:^|\s)(?:current-password|new-password|one-time-code)(?:\s|$)/.test(el.autocomplete)))
}

// ---------------------------------------------------------------------------
// 可访问性快照：ref 注册表
// ---------------------------------------------------------------------------

/** 最近一次快照分配的 ref → 元素；下一次快照重建。 */
let refRegistry = new Map<string, HTMLElement>()
let refSeq = 0

function resetRefs() {
  refRegistry = new Map()
  // Never recycle a ref: a delayed command must not select another snapshot's e1.
}

function assignRef(el: HTMLElement): string {
  const ref = `e${++refSeq}`
  refRegistry.set(ref, el)
  return ref
}

const ROLE_BY_TAG: Record<string, string> = {
  a: 'link',
  button: 'button',
  select: 'combobox',
  textarea: 'textbox',
  h1: 'heading',
  h2: 'heading',
  h3: 'heading',
  h4: 'heading',
  h5: 'heading',
  h6: 'heading',
  img: 'image',
  nav: 'navigation',
  main: 'main',
  header: 'banner',
  footer: 'contentinfo',
  ul: 'list',
  ol: 'list',
  li: 'listitem',
  table: 'table',
  tr: 'row',
  td: 'cell',
  th: 'columnheader',
  dialog: 'dialog',
  form: 'form',
  input: 'textbox',
}

const INPUT_ROLES: Record<string, string> = {
  button: 'button',
  submit: 'button',
  reset: 'button',
  checkbox: 'checkbox',
  radio: 'radio',
  range: 'slider',
  number: 'spinbutton',
  search: 'searchbox',
  email: 'textbox',
  password: 'textbox', // credential-guard: allow —— ARIA 角色映射，不是凭据
  tel: 'textbox',
  url: 'textbox',
  file: 'button',
  color: 'button',
  date: 'textbox',
  time: 'textbox',
  datetime: 'textbox',
}

function implicitRole(el: Element): string {
  const explicit = el.getAttribute('role')
  if (explicit) return explicit.trim()
  const tag = el.tagName.toLowerCase()
  if (tag === 'input') {
    const type = (el.getAttribute('type') || 'text').toLowerCase()
    return INPUT_ROLES[type] || 'textbox'
  }
  if (tag === 'a' && !el.hasAttribute('href')) return ''
  return ROLE_BY_TAG[tag] || tag
}

function accessibleName(el: Element): string {
  const aria = el.getAttribute('aria-label')
  if (aria && aria.trim()) return aria.replace(/\s+/g, ' ').trim().slice(0, 80)
  const labelledBy = el.getAttribute('aria-labelledby')
  if (labelledBy) {
    const target = document.getElementById(labelledBy)
    if (target) return elementText(target)
  }
  const nativeLabels = (el as HTMLInputElement).labels
  if (nativeLabels && nativeLabels.length > 0) {
    const text = elementText(nativeLabels[0])
    if (text) return text
  }
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
    if (label) return elementText(label)
  }
  const wrapping = el.closest('label')
  if (wrapping) {
    const text = elementText(wrapping)
    if (text) return text
  }
  return elementText(el)
}

function nodeState(el: Element): Record<string, unknown> {
  const state: Record<string, unknown> = {}
  const input = el as HTMLInputElement
  if (input.disabled || el.getAttribute('aria-disabled') === 'true') state.disabled = true
  if (input.readOnly) state.readonly = true
  if (input.required || el.getAttribute('aria-required') === 'true') state.required = true
  const ariaChecked = el.getAttribute('aria-checked')
  if (ariaChecked) state.checked = ariaChecked === 'true'
  else if (input.type === 'checkbox' || input.type === 'radio') state.checked = Boolean(input.checked)
  const ariaExpanded = el.getAttribute('aria-expanded')
  if (ariaExpanded !== null) state.expanded = ariaExpanded === 'true'
  const ariaSelected = el.getAttribute('aria-selected')
  if (ariaSelected !== null) state.selected = ariaSelected === 'true'
  if (!isSensitiveElement(el) && typeof input.value === 'string' && input.value && el.tagName === 'INPUT' && input.type !== 'file') {
    state.value = input.value.slice(0, 80)
  }
  return state
}

function findElement(ref?: string, selector?: string, text?: string): HTMLElement | null {
  if (ref) {
    const el = refRegistry.get(ref.trim())
    // 页面重渲染后节点会脱离文档，直接视为失效，提示重新快照
    return el?.isConnected ? el : null
  }
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

function describeTarget(params: Record<string, unknown>): string {
  const ref = String(params.ref || '').trim()
  const selector = String(params.selector || '').trim()
  const text = String(params.text || '').trim()
  return [ref && `ref=${ref}`, selector && `selector=${selector}`, text && 'text=[已提供]']
    .filter(Boolean)
    .join(' ') || '(空)'
}

// ---------------------------------------------------------------------------
// 指令执行
// ---------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function assertCommandCurrent(isCurrent: () => boolean): void {
  if (!isCurrent()) throw new Error('指令已取消')
}

function dispatchInputChange(el: HTMLElement, isCurrent: () => boolean): void {
  for (const type of ['input', 'change']) {
    assertCommandCurrent(isCurrent)
    el.dispatchEvent(new Event(type, { bubbles: true }))
  }
  assertCommandCurrent(isCurrent)
}

async function animateCursorTo(x: number, y: number, label: string, isCurrent: () => boolean): Promise<void> {
  const dx = x - cursorX.value
  cursorVisible.value = true
  cursorActionLabel.value = label
  // 方向倾斜：位移越大倾斜越明显，限制在 ±12° 避免夸张
  cursorTilt.value = Math.max(-12, Math.min(12, dx / 6))
  cursorX.value = x
  cursorY.value = y
  await ensureTrail()
  assertCommandCurrent(isCurrent)
  moveTrail(x, y)
  await sleep(CURSOR_MOVE_MS + 60)
  assertCommandCurrent(isCurrent)
  cursorTilt.value = 0
}

async function execSnapshot(): Promise<Record<string, unknown>> {
  const selectorList =
    'button, a[href], input, textarea, select, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="option"], [role="switch"], [role="checkbox"], [contenteditable="true"]'
  resetRefs()
  const elements: Array<Record<string, unknown>> = []
  let truncated = false
  let scanned = 0
  // 超长页面里快照必须在回执超时前返回：限定总耗时并让出事件循环。
  const deadline = performance.now() + 6000
  const candidates = document.querySelectorAll(selectorList)
  for (let index = 0; index < candidates.length; index += 1) {
    const el = candidates[index]
    if (++scanned > SNAPSHOT_MAX_SCAN || performance.now() > deadline) {
      truncated = true
      break
    }
    // 不做 setTimeout 让出：后台标签页的定时器会被浏览器节流到秒级甚至分钟级，
    // 反而把快照拖过回执超时；同步执行由 deadline 兜底。
    if (!isVisible(el) || el.closest('[data-aiopen-private]')) continue
    if (elements.length >= SNAPSHOT_MAX_ELEMENTS) {
      truncated = true
      break
    }
    const rect = (el as HTMLElement).getBoundingClientRect()
    elements.push({
      ref: assignRef(el as HTMLElement),
      role: implicitRole(el),
      name: accessibleName(el),
      // selector 保留为兼容回退；ref 在同一次快照内稳定
      selector: buildSelector(el),
      tag: el.tagName.toLowerCase(),
      text: elementText(el),
      state: nodeState(el),
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
    })
  }
  return {
    success: true,
    url: window.location.href,
    route: routerRef?.currentRoute.value.fullPath || '',
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    truncated,
    elements,
  }
}

async function execNavigate(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const path = String(params.path || '').trim()
  if (!path) return { success: false, message: 'path 不能为空' }
  if (!routerRef) return { success: false, message: 'router 未就绪' }
  assertCommandCurrent(isCurrent)
  await routerRef.push(path)
  await sleep(400)
  assertCommandCurrent(isCurrent)
  return { success: true, route: routerRef.currentRoute.value.fullPath }
}

async function execClick(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const ref = params.ref ? String(params.ref) : undefined
  const selector = params.selector ? String(params.selector) : undefined
  const text = params.text ? String(params.text) : undefined
  const el = findElement(ref, selector, text)
  if (!el) {
    return {
      success: false,
      message: `未找到元素：${describeTarget(params)}${ref ? '（ref 可能已失效，请重新 ui_snapshot）' : ''}`,
    }
  }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await sleep(260)
  assertCommandCurrent(isCurrent)
  const rect = el.getBoundingClientRect()
  await animateCursorTo(rect.x + rect.width / 2, rect.y + rect.height / 2, '点击', isCurrent)
  assertCommandCurrent(isCurrent)
  cursorClicking.value = true
  pulseTrail(rect.x + rect.width / 2, rect.y + rect.height / 2)
  await sleep(180)
  assertCommandCurrent(isCurrent)
  el.click()
  assertCommandCurrent(isCurrent)
  cursorClicking.value = false
  const label = accessibleName(el) || selector || text || ref || ''
  pushLog(`click → ${label}`)
  return { success: true, clicked: label }
}

async function execType(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const ref = params.ref ? String(params.ref) : undefined
  const selector = params.selector ? String(params.selector) : undefined
  const text = String(params.text ?? '')
  const el = findElement(ref, selector)
  if (!el) return { success: false, message: `未找到输入框：${describeTarget(params)}` }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await sleep(260)
  assertCommandCurrent(isCurrent)
  const rect = el.getBoundingClientRect()
  await animateCursorTo(rect.x + rect.width / 2, rect.y + rect.height / 2, '输入', isCurrent)
  assertCommandCurrent(isCurrent)
  el.focus()
  assertCommandCurrent(isCurrent)
  const input = el as HTMLInputElement | HTMLTextAreaElement
  // 经原型 setter 写值，确保 Vue v-model 等响应式绑定能收到 input 事件
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (setter) {
    setter.call(input, text)
  } else {
    input.value = text
  }
  dispatchInputChange(input, isCurrent)
  const target = ref || selector || ''
  pushLog(`type → ${target}`)
  return { success: true, ref: ref || undefined, selector, typed: isSensitiveElement(el) ? '[REDACTED]' : text }
}

async function execScroll(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  assertCommandCurrent(isCurrent)
  const ref = params.ref ? String(params.ref) : ''
  const selector = params.selector ? String(params.selector) : ''
  if (ref || selector) {
    const el = findElement(ref, selector)
    if (!el) return { success: false, message: `未找到元素：${describeTarget(params)}` }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    await sleep(320)
    assertCommandCurrent(isCurrent)
    return { success: true, scrolled_to: ref || selector }
  }
  const deltaY = Number(params.delta_y || 0) || 300
  const scroller = document.querySelector('.route-view-shell, .main-content, main') || document.scrollingElement
  if (scroller) scroller.scrollBy({ top: deltaY, behavior: 'smooth' })
  await sleep(320)
  assertCommandCurrent(isCurrent)
  return { success: true, delta_y: deltaY }
}

async function execSelect(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const el = findElement(
    params.ref ? String(params.ref) : undefined,
    params.selector ? String(params.selector) : undefined,
  )
  if (!el) return { success: false, message: `未找到下拉控件：${describeTarget(params)}` }
  const values = Array.isArray(params.values)
    ? params.values.map((item) => String(item))
    : params.value !== undefined
      ? [String(params.value)]
      : []
  const label = params.label ? String(params.label) : ''

  if (el instanceof HTMLSelectElement) {
    const wanted = new Set(values)
    let matched = 0
    for (const option of Array.from(el.options)) {
      const hit = wanted.has(option.value) || wanted.has(option.text.trim()) || (!!label && option.text.trim() === label)
      option.selected = hit
      if (hit) matched += 1
    }
    if (!matched) {
      return { success: false, message: `下拉中没有匹配项：${[...values, label].filter(Boolean).join(', ')}` }
    }
    dispatchInputChange(el, isCurrent)
    return { success: true, selected: Array.from(el.selectedOptions).map((option) => option.text.trim()) }
  }

  // 自定义下拉：先点开，再按可见文本匹配选项
  const needle = (label || values[0] || '').trim()
  if (!needle) return { success: false, message: '自定义下拉需要 label 或 value 作为选项文本' }
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await sleep(200)
  assertCommandCurrent(isCurrent)
  const rect = el.getBoundingClientRect()
  await animateCursorTo(rect.x + rect.width / 2, rect.y + rect.height / 2, '选择', isCurrent)
  assertCommandCurrent(isCurrent)
  el.click()
  await sleep(320)
  assertCommandCurrent(isCurrent)
  const candidates = document.querySelectorAll(
    '[role="option"], [role="menuitem"], .el-select-dropdown__item, .ant-select-item-option, li'
  )
  for (const option of Array.from(candidates)) {
    if (!isVisible(option)) continue
    const text = elementText(option)
    if (text === needle || text.includes(needle)) {
      ;(option as HTMLElement).click()
      assertCommandCurrent(isCurrent)
      pushLog(`select → ${needle}`)
      return { success: true, selected: text }
    }
  }
  return { success: false, message: `展开后未找到选项：${needle}` }
}

function decodeBase64(source: string): ArrayBuffer {
  const binary = atob(source.includes(',') ? source.split(',', 2)[1] : source)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes.buffer as ArrayBuffer
}

async function execUpload(params: Record<string, unknown>, isCurrent: () => boolean, signal: AbortSignal): Promise<Record<string, unknown>> {
  let el = findElement(
    params.ref ? String(params.ref) : undefined,
    params.selector ? String(params.selector) : undefined,
  )
  if (!el) return { success: false, message: `未找到上传控件：${describeTarget(params)}` }
  if (!(el instanceof HTMLInputElement) || el.type !== 'file') {
    const nested = el.querySelector('input[type="file"]')
    if (nested instanceof HTMLInputElement) el = nested
  }
  if (!(el instanceof HTMLInputElement) || el.type !== 'file') {
    return { success: false, message: '目标不是 file input（可传容器 ref，内部含 input[type=file]）' }
  }
  const specs = Array.isArray(params.files) ? params.files : []
  const transfer = new DataTransfer()
  for (const raw of specs) {
    const spec = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    const name = String(spec.name || '').trim()
    if (!name) continue
    const type = String(spec.type || '')
    let blob: Blob | null = null
    if (spec.url) {
      try {
        const url = new URL(String(spec.url), window.location.href)
        if (!['http:', 'https:'].includes(url.protocol) || url.origin !== window.location.origin || url.username || url.password) {
          return { success: false, message: '文件 URL 必须为当前站点的 HTTP(S) 地址，且不能包含凭据' }
        }
        const artifact = /^\/api\/agent\/runs\/([A-Za-z0-9_-]{1,160})\/artifacts\/([A-Za-z0-9_-]{1,160})$/.exec(url.pathname)
        if (!artifact || url.search || url.hash) {
          return { success: false, message: '文件 URL 仅支持当前站点的 Agent 文件产物下载地址，不接受查询或片段；其他文件请传 base64 或 text' }
        }
        // The fixed download route checks run ownership and the stored file digest.
        // Keep remote input in encoded IDs; never use it as a request URL or route.
        const response = await fetch(`/api/agent/runs/${encodeURIComponent(artifact[1])}/artifacts/${encodeURIComponent(artifact[2])}`, { credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal })
        assertCommandCurrent(isCurrent)
        if (!response.ok) return { success: false, message: `读取文件失败：${spec.url} → HTTP ${response.status}` }
        blob = await response.blob()
        assertCommandCurrent(isCurrent)
      } catch (err) {
        return { success: false, message: `读取文件失败：${spec.url}（${String((err as Error)?.message || err)}）` }
      }
    } else if (spec.base64) {
      blob = new Blob([decodeBase64(String(spec.base64))], { type: type || 'application/octet-stream' })
    } else if (spec.text !== undefined) {
      blob = new Blob([String(spec.text)], { type: type || 'text/plain' })
    }
    if (!blob) continue
    transfer.items.add(new File([blob], name, { type: type || blob.type || 'application/octet-stream' }))
  }
  if (transfer.files.length === 0) {
    return { success: false, message: 'files 为空或缺少可用内容（url / base64 / text）' }
  }
  el.files = transfer.files
  dispatchInputChange(el, isCurrent)
  const names = Array.from(transfer.files).map((file) => file.name)
  pushLog(`upload → ${names.join(', ')}`)
  return { success: true, uploaded: names }
}

function waitConditions(params: Record<string, unknown>): Array<{ unmet: string | null; detail: string }> {
  const checks: Array<{ unmet: string | null; detail: string }> = []
  const ref = params.ref ? String(params.ref) : ''
  const selector = params.selector ? String(params.selector) : ''
  if (ref || selector) {
    const el = findElement(ref || undefined, selector || undefined)
    checks.push({
      unmet: el && isVisible(el) ? null : `元素出现（${describeTarget(params)}）`,
      detail: `元素出现（${describeTarget(params)}）`,
    })
  }
  const text = params.text ? String(params.text) : ''
  if (text) {
    const hit = (document.body.innerText || '').includes(text)
    checks.push({ unmet: hit ? null : `页面文本「${text}」`, detail: `页面文本「${text}」` })
  }
  const urlContains = params.url_contains ? String(params.url_contains) : ''
  if (urlContains) {
    const hit = window.location.href.includes(urlContains)
    checks.push({ unmet: hit ? null : `URL 包含「${urlContains}」`, detail: `URL 包含「${urlContains}」` })
  }
  const goneRef = params.gone_ref ? String(params.gone_ref) : ''
  const goneSelector = params.gone_selector ? String(params.gone_selector) : ''
  if (goneRef || goneSelector) {
    const el = findElement(goneRef || undefined, goneSelector || undefined)
    const gone = !el || !isVisible(el)
    const detail = `元素消失（${goneRef ? `ref=${goneRef}` : `selector=${goneSelector}`}）`
    checks.push({ unmet: gone ? null : detail, detail })
  }
  return checks
}

async function execWait(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const timeout = Math.min(Math.max(Number(params.timeout_ms) || 5000, 300), WAIT_MAX_MS)
  const startedAt = Date.now()
  for (;;) {
    if (!isCurrent()) return { success: false, message: '等待已取消' }
    const probes = waitConditions(params)
    if (probes.length === 0) {
      return { success: false, message: '至少提供一个等待条件（ref/selector/text/url_contains/gone_*）' }
    }
    const unmet = probes.map((probe) => probe.unmet).filter((item): item is string => Boolean(item))
    if (unmet.length === 0) {
      return {
        success: true,
        waited_ms: Date.now() - startedAt,
        matched: probes.map((probe) => probe.detail).join('；'),
      }
    }
    if (Date.now() - startedAt >= timeout) {
      return {
        success: false,
        waited_ms: Date.now() - startedAt,
        message: `等待超时（${timeout}ms），未满足：${unmet.join('；')}`,
      }
    }
    await sleep(WAIT_POLL_MS)
  }
}

async function execVerify(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  const checks: Array<Record<string, unknown>> = []
  const ref = params.ref ? String(params.ref) : ''
  const selector = params.selector ? String(params.selector) : ''
  const target = ref || selector
  let element: HTMLElement | null = null
  if (target) {
    element = findElement(ref || undefined, selector || undefined)
    checks.push({
      check: '元素存在',
      ok: Boolean(element) && isVisible(element as HTMLElement),
      detail: describeTarget(params),
    })
  }
  if (params.value !== undefined) {
    const expected = String(params.value)
    const actual = element
      ? String((element as HTMLInputElement).value ?? element.getAttribute('value') ?? elementText(element))
      : ''
    checks.push({
      check: '控件值',
      ok: Boolean(element) && actual === expected,
      detail: element && isSensitiveElement(element) ? '敏感控件值已隐藏' : `期望「${expected}」，实际「${actual}」`,
    })
  }
  if (params.text) {
    const needle = String(params.text)
    checks.push({
      check: '页面文本',
      ok: (document.body.innerText || '').includes(needle),
      detail: `应包含「${needle}」`,
    })
  }
  if (params.url_contains) {
    const needle = String(params.url_contains)
    checks.push({
      check: 'URL',
      ok: window.location.href.includes(needle),
      detail: `应包含「${needle}」，当前 ${window.location.href}`,
    })
  }
  if (checks.length === 0) {
    return { success: false, message: '至少提供一个校验条件（ref/selector/value/text/url_contains）' }
  }
  return { success: checks.every((check) => check.ok), checks }
}

async function execScreenshot(params: Record<string, unknown>, isCurrent: () => boolean): Promise<Record<string, unknown>> {
  const ref = params.ref ? String(params.ref) : ''
  const selector = params.selector ? String(params.selector) : ''
  const targetEl = ref || selector ? findElement(ref || undefined, selector || undefined) : document.body
  if (!targetEl) return { success: false, message: `未找到截图区域：${describeTarget(params)}` }
  if (isSensitiveElement(targetEl)) return { success: false, code: 'SENSITIVE_TARGET', message: '敏感控件不允许截图' }
  const maxWidth = Math.min(Math.max(Number(params.max_width) || SCREENSHOT_MAX_WIDTH, 320), 4096)
  const rect = targetEl.getBoundingClientRect()
  const naturalWidth = Math.max(
    Math.round(rect.width || targetEl.scrollWidth || 0),
    document.documentElement.clientWidth
  )
  const pixelRatio = Math.min(1, maxWidth / Math.max(naturalWidth, 1))
  const cursorWasVisible = cursorVisible.value
  // 截图前隐藏虚拟光标，避免把操控光标画进画面
  cursorVisible.value = false
  await sleep(80)
  try {
    const { toPng } = await import('html-to-image')
    if (!isCurrent()) return { success: false, message: '截图已取消' }
    const dataUrl = await toPng(targetEl as HTMLElement, {
      filter: (node) => !(node instanceof Element) || !isSensitiveElement(node),
      pixelRatio,
      cacheBust: true,
      backgroundColor: window.getComputedStyle(document.body).backgroundColor || '#ffffff',
      width: Math.round(rect.width || targetEl.scrollWidth || document.documentElement.clientWidth),
      height: Math.round(rect.height || targetEl.scrollHeight || document.documentElement.clientHeight),
    })
    const size = await new Promise<{ width: number; height: number }>((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
      image.onerror = () => reject(new Error('截图解码失败'))
      image.src = dataUrl
    })
    if (!isCurrent()) return { success: false, message: '截图已取消' }
    const bytes = Math.round((dataUrl.length - dataUrl.indexOf(',') - 1) * 0.75)
    pushLog(`screenshot → ${size.width}×${size.height}`)
    return {
      success: true,
      data_url: dataUrl,
      width: size.width,
      height: size.height,
      bytes,
      target: ref || selector || 'viewport',
    }
  } catch (err) {
    return { success: false, message: `截图失败：${String((err as Error)?.message || err)}` }
  } finally {
    if (isCurrent()) cursorVisible.value = cursorWasVisible
  }
}

async function executeCommand(action: string, params: Record<string, unknown>, isCurrent: () => boolean, signal: AbortSignal): Promise<Record<string, unknown>> {
  switch (action) {
    case 'snapshot':
      return execSnapshot()
    case 'navigate':
      return execNavigate(params, isCurrent)
    case 'click':
      return execClick(params, isCurrent)
    case 'type':
      return execType(params, isCurrent)
    case 'select':
      return execSelect(params, isCurrent)
    case 'upload':
      return execUpload(params, isCurrent, signal)
    case 'wait':
      return execWait(params, isCurrent)
    case 'verify':
      return execVerify(params)
    case 'screenshot':
      return execScreenshot(params, isCurrent)
    case 'scroll':
      return execScroll(params, isCurrent)
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
  const connection = ws
  const sessionCurrent = captureAuthSession()
  const isCurrent = () => aiopenCursorEnabled.value && ws === connection && sessionCurrent()
  let commandQueue = Promise.resolve()
  const commands = new Map<string, AbortController>()
  abortConnectionCommands = () => { for (const command of commands.values()) command.abort() }
  stopSessionWatch = watch(sessionCurrent, () => {
    disconnect()
    scheduleReconnect()
  }, { flush: 'sync' })
  ws.onopen = () => {
    if (!isCurrent()) return
    aiopenCursorConnected.value = true
    pushLog('已连接 AIOPEN 操控通道')
  }
  ws.onmessage = async (event) => {
    if (!isCurrent()) return
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
    if (msg.type === 'cancel') {
      commands.get(String(msg.id || ''))?.abort()
      return
    }
    if (msg.type === 'command') {
      const id = String(msg.id || '')
      if (!id || commands.has(id)) return
      const command = new AbortController()
      commands.set(id, command)
      const timeout = msg.timeout_ms === undefined ? COMMAND_MAX_MS : msg.timeout_ms
      let ttl = 0
      if (typeof timeout === 'number' && Number.isFinite(timeout) && timeout >= 0) {
        if (timeout > COMMAND_MAX_MS) ttl = COMMAND_MAX_MS
        else ttl = timeout
      }
      const deadline = performance.now() + ttl
      const deadlineTimer = window.setTimeout(() => command.abort(), ttl)
      const commandCurrent = () => isCurrent() && !command.signal.aborted && performance.now() < deadline
      const action = String(msg.action || '')
      const params = (msg.params && typeof msg.params === 'object' ? msg.params : {}) as Record<string, unknown>
      commandQueue = commandQueue.then(async () => {
        let result: Record<string, unknown>
        try {
          assertCommandCurrent(commandCurrent)
          markAgentActive()
          pushLog(`收到指令：${action}`)
          result = await executeCommand(action, params, commandCurrent, command.signal)
        } catch (err) {
          result = { success: false, message: String((err as Error)?.message || err) }
        } finally {
          commands.delete(id)
          window.clearTimeout(deadlineTimer)
        }
        if (!isCurrent()) return
        if (!commandCurrent()) {
          result = { success: false, code: 'COMMAND_CANCELLED', message: '指令已取消或超时，需读取页面确认结果' }
          cursorClicking.value = false
          cursorVisible.value = false
          cursorActionLabel.value = ''
        } else if (!SILENT_ACTIONS.has(action)) {
          // 快照/等待/校验/截图不收光标；操作类指令完成后短暂保留再淡出
          window.setTimeout(() => {
            if (!isCurrent()) return
            cursorVisible.value = false
            cursorActionLabel.value = ''
          }, 4000)
        }
        try {
          connection.send(JSON.stringify({ type: 'result', id, result }))
        } catch {
          /* 连接已断，无法回执 */
        }
      })
      await commandQueue
    }
  }
  ws.onclose = () => {
    if (ws !== connection) return
    disconnect()
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
  abortConnectionCommands?.()
  abortConnectionCommands = null
  stopSessionWatch?.()
  stopSessionWatch = null
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
  cursorClicking.value = false
  cursorTilt.value = 0
  cursorActionLabel.value = ''
  resetRefs()
  clearAgentActive()
  disableTrail()
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

/**
 * App.vue 内 VirtualCursorOverlay 调用：注入 router 并默认静默待命。
 *
 * 默认连接（无需用户点开关），只有用户明确关闭过（localStorage = '0'）才保持关闭；
 * 待命期间不展示光标与徽标，收到 Agent 指令才出现。
 */
export function initAiOpenCursor(router: Router) {
  routerRef = router
  let persisted: string | null = null
  try {
    persisted = localStorage.getItem(STORAGE_KEY)
  } catch {
    // 存储不可用（隐私模式）时按默认待命处理，用户仍可在面板关闭
    persisted = null
  }
  if (persisted === '0' || aiopenCursorEnabled.value) return
  aiopenCursorEnabled.value = true
  connect()
}

export function useAiOpenCursor() {
  return {
    enabled: aiopenCursorEnabled,
    connected: aiopenCursorConnected,
    sessionId: aiopenCursorSessionId,
    logs: aiopenCursorLogs,
    agentActive: aiopenAgentActive,
    setEnabled: setAiOpenCursorEnabled,
  }
}
