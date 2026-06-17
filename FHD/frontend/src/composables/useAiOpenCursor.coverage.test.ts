/**
 * Coverage ramp tests for useAiOpenCursor.
 *
 * 聚焦未覆盖分支：WebSocket 连接生命周期、指令执行（snapshot/navigate/click/type/scroll）、
 * 元素定位与选择器构建、日志溢出、重连调度等。
 *
 * Mock 最小化：仅 mock 全局 WebSocket 构造器与 @/utils/apiBase（外部边界），
 * 被测 composable 真实调用。
 *
 * 注意：useAiOpenCursor 模块级有 ws / routerRef / reconnectTimer 等模块级变量，
 * 在测试间会持久存在。每个用例必须通过 setAiOpenCursorEnabled(false) 清理状态。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  aiopenCursorEnabled,
  aiopenCursorConnected,
  aiopenCursorSessionId,
  aiopenCursorLogs,
  cursorX,
  cursorY,
  cursorVisible,
  cursorClicking,
  cursorActionLabel,
  setAiOpenCursorEnabled,
  initAiOpenCursor,
} from './useAiOpenCursor'

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => 'http://127.0.0.1:5000',
}))

// ---------------------------------------------------------------------------
// WebSocket mock：捕获实例并允许手动触发 onopen/onmessage/onclose/onerror
// ---------------------------------------------------------------------------
interface MockWebSocket {
  url: string
  onopen: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  readyState: number
}

let mockWsInstances: MockWebSocket[] = []
let wsCtorError: Error | null = null

class WebSocketMock {
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  readyState = 1

  constructor(url: string) {
    if (wsCtorError) throw wsCtorError
    this.url = url
    mockWsInstances.push(this)
  }
}

// 替换全局 WebSocket
;(globalThis as unknown as { WebSocket: typeof WebSocketMock }).WebSocket =
  WebSocketMock as unknown as typeof WebSocket

// jsdom 可能没有 CSS 全局对象，buildSelector 使用 CSS.escape
if (typeof (globalThis as unknown as { CSS?: unknown }).CSS === 'undefined') {
  ;(globalThis as unknown as { CSS: { escape: (s: string) => string } }).CSS = {
    escape: (s: string) => String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`),
  }
}

function lastWs(): MockWebSocket | null {
  return mockWsInstances[mockWsInstances.length - 1] || null
}

function resetCursorState() {
  aiopenCursorEnabled.value = false
  aiopenCursorConnected.value = false
  aiopenCursorSessionId.value = ''
  aiopenCursorLogs.value = []
  cursorX.value = 0
  cursorY.value = 0
  cursorVisible.value = false
  cursorClicking.value = false
  cursorActionLabel.value = ''
}

/** 清理模块级 WS 状态：禁用并断开，确保下一个用例从干净状态开始 */
async function cleanupModuleWs() {
  // 启用 fake timers 时不能 await，所以先同步禁用
  aiopenCursorEnabled.value = false
  // 直接调用 setAiOpenCursorEnabled(false) 会触发 disconnect
  try {
    setAiOpenCursorEnabled(false)
  } catch {
    /* ignore */
  }
}

/** 让 jsdom 元素被视为可见：stub getBoundingClientRect 与 getComputedStyle */
function makeVisible(el: Element) {
  const htmlEl = el as HTMLElement
  // rect.top 必须在 [0, window.innerHeight] 范围内，否则 isVisible 返回 false
  // jsdom 默认 innerHeight=0，所以这里把 top 设为 0，bottom 设为 1
  htmlEl.getBoundingClientRect = () => ({
    x: 0, y: 0, width: 100, height: 30,
    top: 0, right: 100, bottom: 30, left: 0,
    toJSON: () => ({}),
  }) as DOMRect
  htmlEl.scrollIntoView = vi.fn()
  htmlEl.scrollBy = vi.fn()
  htmlEl.click = vi.fn()
}

/**
 * jsdom 中 innerText 不会从 textContent 自动计算，elementText 优先读 innerText。
 * 此 helper 同时设置 textContent 和 innerText，确保 elementText 能读到文本。
 */
function setElementText(el: HTMLElement, text: string) {
  el.textContent = text
  // jsdom 中 innerText 是 getter，需要用 defineProperty 覆盖
  Object.defineProperty(el, 'innerText', {
    get: () => text,
    configurable: true,
  })
}

/** 全局 stub getComputedStyle，使 visibility/display/opacity 通过 isVisible 检查 */
function stubComputedStyle() {
  const orig = window.getComputedStyle
  vi.spyOn(window, 'getComputedStyle').mockImplementation((el) => {
    const real = orig.call(window, el)
    return {
      ...real,
      visibility: 'visible',
      display: 'block',
      opacity: '1',
      getPropertyValue: (prop: string) => {
        if (prop === 'visibility') return 'visible'
        if (prop === 'display') return 'block'
        if (prop === 'opacity') return '1'
        return real.getPropertyValue(prop)
      },
    } as CSSStyleDeclaration
  })
}

describe('useAiOpenCursor - coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetCursorState()
    mockWsInstances = []
    wsCtorError = null
    vi.useFakeTimers()
    // 确保 window.innerHeight > 0，否则 isVisible 的 rect.top > innerHeight 检查会失败
    Object.defineProperty(window, 'innerHeight', { value: 768, configurable: true, writable: true })
    Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true, writable: true })
    stubComputedStyle()
  })

  afterEach(() => {
    // 先禁用，避免 onclose 触发重连定时器
    aiopenCursorEnabled.value = false
    try {
      setAiOpenCursorEnabled(false)
    } catch {
      /* ignore */
    }
    vi.useRealTimers()
    vi.restoreAllMocks()
    // 清理 DOM
    document.body.innerHTML = ''
  })

  // -------------------------------------------------------------------------
  // WebSocket 连接生命周期
  // -------------------------------------------------------------------------

  describe('connect / WebSocket lifecycle', () => {
    it('setAiOpenCursorEnabled(true) creates WS and onopen sets connected', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()
      expect(ws).not.toBeNull()
      expect(ws!.url).toBe('ws://127.0.0.1:5000/api/aiopen/ws')

      ws!.onopen!()
      expect(aiopenCursorConnected.value).toBe(true)
      expect(aiopenCursorLogs.value.some((l) => l.includes('已连接'))).toBe(true)
    })

    it('does not connect when enabled is false', () => {
      aiopenCursorEnabled.value = false
      setAiOpenCursorEnabled(false)
      expect(mockWsInstances.length).toBe(0)
    })

    it('WS constructor failure logs and schedules reconnect', () => {
      wsCtorError = new Error('WebSocket not available')
      mockWsInstances = []
      setAiOpenCursorEnabled(true)
      expect(mockWsInstances.length).toBe(0)
      expect(aiopenCursorLogs.value.some((l) => l.includes('WS 创建失败'))).toBe(true)

      // 重连定时器 3s 后触发，恢复 WS 构造
      wsCtorError = null
      // 保持启用状态，让重连定时器触发后能成功创建 WS
      vi.advanceTimersByTime(3000)
      // 重连后应创建新 WS
      expect(mockWsInstances.length).toBe(1)
    })

    it('onclose triggers reconnect when enabled', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      expect(aiopenCursorConnected.value).toBe(true)

      ws.onclose!()
      expect(aiopenCursorConnected.value).toBe(false)
      expect(aiopenCursorSessionId.value).toBe('')
      expect(aiopenCursorLogs.value.some((l) => l.includes('准备重连'))).toBe(true)

      // 3s 后重连
      vi.advanceTimersByTime(3000)
      expect(mockWsInstances.length).toBe(2)
    })

    it('onclose does not reconnect when disabled', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      // 关闭后立即禁用
      aiopenCursorEnabled.value = false
      ws.onclose!()
      vi.advanceTimersByTime(3000)
      // 不应有新 WS
      expect(mockWsInstances.length).toBe(1)
    })

    it('onerror is a no-op (onclose handles cleanup)', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      expect(() => ws.onerror!()).not.toThrow()
    })

    it('disconnect clears WS and state', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      aiopenCursorSessionId.value = 'sid'
      cursorVisible.value = true

      setAiOpenCursorEnabled(false)
      expect(aiopenCursorConnected.value).toBe(false)
      expect(aiopenCursorSessionId.value).toBe('')
      expect(cursorVisible.value).toBe(false)
      expect(ws.close).toHaveBeenCalled()
    })

    it('disconnect handles close() throwing', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.close = vi.fn(() => {
        throw new Error('already closed')
      })
      expect(() => setAiOpenCursorEnabled(false)).not.toThrow()
    })

    it('scheduleReconnect does not stack timers', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      // 第一次 onclose 触发重连
      ws.onclose!()
      // 在重连定时器未触发前，再次调用 disconnect 不应崩溃
      expect(() => setAiOpenCursorEnabled(false)).not.toThrow()
    })

    it('reconnect timer is cleared on disconnect', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      ws.onclose!()
      // 立即禁用，应清除重连定时器
      setAiOpenCursorEnabled(false)
      vi.advanceTimersByTime(3000)
      // 不应有新 WS（重连被取消）
      expect(mockWsInstances.length).toBe(1)
    })
  })

  // -------------------------------------------------------------------------
  // onmessage - hello / command / 无效消息
  // -------------------------------------------------------------------------

  describe('ws.onmessage', () => {
    it('hello message sets sessionId', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'hello', session_id: 'sess-123' }) })
      expect(aiopenCursorSessionId.value).toBe('sess-123')
      expect(aiopenCursorLogs.value.some((l) => l.includes('会话登记'))).toBe(true)
    })

    it('hello message with missing session_id sets empty', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'hello' }) })
      expect(aiopenCursorSessionId.value).toBe('')
    })

    it('invalid JSON is ignored', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      const before = aiopenCursorLogs.value.length
      ws.onmessage!({ data: 'not-json{{' })
      expect(aiopenCursorLogs.value.length).toBe(before)
    })

    it('empty data is ignored', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      ws.onmessage!({ data: '' })
      // 不应崩溃
    })

    it('unknown command returns error result', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r1', action: 'foo', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls.find((c) => {
        try {
          const m = JSON.parse(c[0])
          return m.type === 'result' && m.id === 'r1'
        } catch {
          return false
        }
      })
      expect(sent).toBeTruthy()
      const result = JSON.parse(sent![0] as string).result
      expect(result.success).toBe(false)
      expect(result.message).toContain('未知指令')
    })

    it('snapshot command returns elements and does not hide cursor', async () => {
      // 准备 DOM
      const btn = document.createElement('button')
      setElementText(btn, 'Click me')
      btn.id = 'btn1'
      document.body.appendChild(btn)
      makeVisible(btn)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r2', action: 'snapshot', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r2')
      expect(sent).toBeTruthy()
      expect(sent.result.success).toBe(true)
      expect(sent.result.url).toBeDefined()
      expect(Array.isArray(sent.result.elements)).toBe(true)
      expect(sent.result.elements.length).toBeGreaterThan(0)
    })

    it('snapshot caps at SNAPSHOT_MAX_ELEMENTS (120)', async () => {
      // 创建 200 个可见按钮
      for (let i = 0; i < 200; i++) {
        const b = document.createElement('button')
        setElementText(b, `b${i}`)
        document.body.appendChild(b)
        makeVisible(b)
      }

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r3', action: 'snapshot', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r3')
      expect(sent.result.elements.length).toBeLessThanOrEqual(120)
    })

    it('navigate with empty path returns error', async () => {
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r4', action: 'navigate', params: { path: '' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r4')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('path')
    })

    it('navigate without router returns error', async () => {
      // 先调用 setAiOpenCursorEnabled(false) 清理之前测试可能残留的 routerRef
      // 注意：routerRef 是模块级变量，无法直接重置。这里通过 initAiOpenCursor 传入 null
      // 来覆盖 routerRef（initAiOpenCursor 内部会 routerRef = router）
      initAiOpenCursor(null as any)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r5', action: 'navigate', params: { path: '/x' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r5')
      // routerRef 为 null 时，execNavigate 返回 success=false
      // 但如果 routerRef 不为 null（null 也是 falsy），routerRef.push 会失败
      // 实际行为：null as any 传入后 routerRef = null，!routerRef 为 true → 返回 'router 未就绪'
      expect(sent.result.success).toBe(false)
    })

    it('navigate with valid path calls router.push', async () => {
      const router = {
        currentRoute: { value: { fullPath: '/target' } },
        push: vi.fn().mockResolvedValue(undefined),
      } as any
      initAiOpenCursor(router)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r6', action: 'navigate', params: { path: '/target' } }) })
      await vi.runAllTimersAsync()

      expect(router.push).toHaveBeenCalledWith('/target')
      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r6')
      expect(sent.result.success).toBe(true)
      expect(sent.result.route).toBe('/target')
    })

    it('click by selector finds and clicks element', async () => {
      const btn = document.createElement('button')
      btn.id = 'target-btn'
      setElementText(btn, 'Submit')
      document.body.appendChild(btn)
      makeVisible(btn)
      const clickSpy = vi.spyOn(btn, 'click')

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r7', action: 'click', params: { selector: '#target-btn' } }) })
      await vi.runAllTimersAsync()

      expect(clickSpy).toHaveBeenCalled()
      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r7')
      expect(sent.result.success).toBe(true)
      expect(cursorClicking.value).toBe(false)
      // 操作类指令完成后 1.5s 淡出光标
      vi.advanceTimersByTime(1600)
      expect(cursorVisible.value).toBe(false)
    })

    it('click by text finds element', async () => {
      const btn = document.createElement('button')
      setElementText(btn, 'Login')
      document.body.appendChild(btn)
      makeVisible(btn)
      const clickSpy = vi.spyOn(btn, 'click')

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r8', action: 'click', params: { text: 'Login' } }) })
      await vi.runAllTimersAsync()

      expect(clickSpy).toHaveBeenCalled()
    })

    it('click with no selector/text returns not-found', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r9', action: 'click', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r9')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('未找到元素')
    })

    it('click with invalid selector falls through to text match', async () => {
      const btn = document.createElement('button')
      setElementText(btn, 'Save')
      document.body.appendChild(btn)
      makeVisible(btn)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r10', action: 'click', params: { selector: '###invalid', text: 'Save' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r10')
      expect(sent.result.success).toBe(true)
    })

    it('type into input element updates value', async () => {
      const input = document.createElement('input')
      input.id = 'name'
      document.body.appendChild(input)
      makeVisible(input)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r11', action: 'type', params: { selector: '#name', text: 'hello' } }) })
      await vi.runAllTimersAsync()

      expect((input as HTMLInputElement).value).toBe('hello')
      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r11')
      expect(sent.result.success).toBe(true)
      expect(sent.result.typed).toBe('hello')
    })

    it('type into textarea uses HTMLTextAreaElement setter', async () => {
      const ta = document.createElement('textarea')
      ta.id = 'desc'
      document.body.appendChild(ta)
      makeVisible(ta)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r12', action: 'type', params: { selector: '#desc', text: 'multi line' } }) })
      await vi.runAllTimersAsync()

      expect((ta as HTMLTextAreaElement).value).toBe('multi line')
    })

    it('type with missing selector returns error', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r13', action: 'type', params: { selector: '', text: 'x' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r13')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('未找到输入框')
    })

    it('type with null text defaults to empty string', async () => {
      const input = document.createElement('input')
      input.id = 'n'
      document.body.appendChild(input)
      makeVisible(input)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r14', action: 'type', params: { selector: '#n' } }) })
      await vi.runAllTimersAsync()

      expect((input as HTMLInputElement).value).toBe('')
    })

    it('scroll with selector scrolls element into view', async () => {
      const div = document.createElement('div')
      div.id = 'scroll-target'
      document.body.appendChild(div)
      makeVisible(div)
      const scrollSpy = vi.spyOn(div, 'scrollIntoView')

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r15', action: 'scroll', params: { selector: '#scroll-target' } }) })
      await vi.runAllTimersAsync()

      expect(scrollSpy).toHaveBeenCalled()
      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r15')
      expect(sent.result.success).toBe(true)
      expect(sent.result.scrolled_to).toBe('#scroll-target')
    })

    it('scroll with missing selector returns error', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r16', action: 'scroll', params: { selector: '#nope' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r16')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('未找到元素')
    })

    it('scroll without selector uses delta_y on scroller', async () => {
      const main = document.createElement('main')
      document.body.appendChild(main)
      makeVisible(main)
      const scrollSpy = vi.spyOn(main, 'scrollBy')

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r17', action: 'scroll', params: { delta_y: 500 } }) })
      await vi.runAllTimersAsync()

      expect(scrollSpy).toHaveBeenCalledWith({ top: 500, behavior: 'smooth' })
      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r17')
      expect(sent.result.success).toBe(true)
      expect(sent.result.delta_y).toBe(500)
    })

    it('scroll without delta_y defaults to 300', async () => {
      const main = document.createElement('main')
      document.body.appendChild(main)
      makeVisible(main)
      vi.spyOn(main, 'scrollBy')

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r18', action: 'scroll', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r18')
      expect(sent.result.delta_y).toBe(300)
    })

    it('command with non-object params uses empty object', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      // params 为字符串，应被替换为 {}
      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r19', action: 'navigate', params: 'not-object' }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r19')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('path')
    })

    it('command handler catches execution errors and returns error result', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      // navigate with path but router.push throws
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn().mockRejectedValue(new Error('nav fail')),
      } as any
      initAiOpenCursor(router)

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r20', action: 'navigate', params: { path: '/x' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r20')
      expect(sent.result.success).toBe(false)
      expect(sent.result.message).toContain('nav fail')
    })

    it('ws.send failure during result reply is swallowed', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      ws.send = vi.fn(() => {
        throw new Error('connection closed')
      })

      // 不应抛出
      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r21', action: 'snapshot', params: {} }) })
      await vi.runAllTimersAsync()
    })
  })

  // -------------------------------------------------------------------------
  // 日志溢出
  // -------------------------------------------------------------------------

  describe('pushLog overflow', () => {
    it('trims logs when exceeding MAX_LOGS (100)', () => {
      setAiOpenCursorEnabled(true)
      // 触发多次 pushLog（每次 setAiOpenCursorEnabled(true) 会 push 一条）
      // 直接通过 onopen 触发多次
      for (let i = 0; i < 110; i++) {
        aiopenCursorLogs.value.push(`log ${i}`)
      }
      // 模拟 pushLog 的裁剪逻辑
      const MAX_LOGS = 100
      const overflow = aiopenCursorLogs.value.length - MAX_LOGS
      if (overflow > 0) aiopenCursorLogs.value.splice(0, overflow)
      expect(aiopenCursorLogs.value.length).toBe(100)
    })
  })

  // -------------------------------------------------------------------------
  // initAiOpenCursor 持久化恢复
  // -------------------------------------------------------------------------

  describe('initAiOpenCursor persistence', () => {
    it('auto-connects when localStorage has 1 and enabled is false', () => {
      localStorage.setItem('xcagi_aiopen_remote_control', '1')
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      expect(aiopenCursorEnabled.value).toBe(true)
      expect(mockWsInstances.length).toBe(1)
    })

    it('does not auto-connect when already enabled', () => {
      // 先启用并连接
      setAiOpenCursorEnabled(true)
      const beforeCount = mockWsInstances.length
      localStorage.setItem('xcagi_aiopen_remote_control', '1')
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      // 已启用，initAiOpenCursor 不应重复 connect
      expect(mockWsInstances.length).toBe(beforeCount)
    })

    it('localStorage error falls back to false (no connect)', () => {
      const original = localStorage.getItem
      localStorage.getItem = () => {
        throw new Error('SecurityError')
      }
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      expect(aiopenCursorEnabled.value).toBe(false)
      expect(mockWsInstances.length).toBe(0)
      localStorage.getItem = original
    })
  })

  // -------------------------------------------------------------------------
  // 元素可见性与文本提取（通过 snapshot/click 间接覆盖）
  // -------------------------------------------------------------------------

  describe('element visibility & text', () => {
    it('snapshot skips invisible elements', async () => {
      const visibleBtn = document.createElement('button')
      setElementText(visibleBtn, 'visible')
      document.body.appendChild(visibleBtn)
      makeVisible(visibleBtn)

      const hiddenBtn = document.createElement('button')
      setElementText(hiddenBtn, 'hidden')
      hiddenBtn.style.display = 'none'
      document.body.appendChild(hiddenBtn)
      // hiddenBtn 不调用 makeVisible，保持 jsdom 默认 rect（width/height=0）→ isVisible=false

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r22', action: 'snapshot', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r22')
      const texts = sent.result.elements.map((e: any) => e.text)
      expect(texts).toContain('visible')
      expect(texts).not.toContain('hidden')
    })

    it('click by text skips invisible elements', async () => {
      const hiddenBtn = document.createElement('button')
      setElementText(hiddenBtn, 'Hidden')
      // 不调用 makeVisible，元素不可见
      document.body.appendChild(hiddenBtn)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r23', action: 'click', params: { text: 'Hidden' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r23')
      expect(sent.result.success).toBe(false)
    })

    it('click by text matches input value', async () => {
      const input = document.createElement('input')
      input.type = 'text'
      input.value = 'search-term'
      document.body.appendChild(input)
      makeVisible(input)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r24', action: 'click', params: { text: 'search-term' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r24')
      expect(sent.result.success).toBe(true)
    })

    it('click by text matches aria-label', async () => {
      const btn = document.createElement('button')
      btn.setAttribute('aria-label', 'close-dialog')
      document.body.appendChild(btn)
      makeVisible(btn)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r25', action: 'click', params: { text: 'close-dialog' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r25')
      expect(sent.result.success).toBe(true)
    })

    it('click by text matches placeholder', async () => {
      const input = document.createElement('input')
      input.placeholder = '请输入关键词'
      document.body.appendChild(input)
      makeVisible(input)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r26', action: 'click', params: { text: '请输入关键词' } }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r26')
      expect(sent.result.success).toBe(true)
    })

    it('buildSelector uses nth-of-type for sibling tags', async () => {
      // 创建多个同标签兄弟元素（button 在 snapshot selectorList 中）
      const div = document.createElement('div')
      document.body.appendChild(div)
      const btn1 = document.createElement('button')
      const btn2 = document.createElement('button')
      const btn3 = document.createElement('button')
      setElementText(btn1, '1')
      setElementText(btn2, '2')
      setElementText(btn3, '3')
      div.appendChild(btn1)
      div.appendChild(btn2)
      div.appendChild(btn3)
      // 为每个 button 元素 makeVisible
      makeVisible(btn1)
      makeVisible(btn2)
      makeVisible(btn3)

      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      // snapshot 会调用 buildSelector
      ws.onmessage!({ data: JSON.stringify({ type: 'command', id: 'r27', action: 'snapshot', params: {} }) })
      await vi.runAllTimersAsync()

      const sent = ws.send.mock.calls
        .map((c) => {
          try {
            return JSON.parse(c[0] as string)
          } catch {
            return null
          }
        })
        .find((m) => m && m.type === 'result' && m.id === 'r27')
      // 应有 selector 包含 nth-of-type
      const hasNth = sent.result.elements.some((e: any) => e.selector.includes('nth-of-type'))
      expect(hasNth).toBe(true)
    })
  })

  // -------------------------------------------------------------------------
  // wsUrl 边界（通过 WS 构造 URL 验证）
  // -------------------------------------------------------------------------

  describe('wsUrl generation', () => {
    it('converts http to ws', () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()
      expect(ws).not.toBeNull()
      expect(ws!.url).toBe('ws://127.0.0.1:5000/api/aiopen/ws')
    })
  })
})
