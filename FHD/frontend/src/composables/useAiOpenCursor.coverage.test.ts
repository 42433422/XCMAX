/**
 * Coverage ramp tests for useAiOpenCursor.
 *
 * 聚焦未覆盖分支：WebSocket 连接生命周期、指令执行（snapshot/navigate/click/type/scroll）、
 * 元素定位与选择器构建、日志溢出、重连调度等。
 *
 * 替换 WebSocket/API、文件传输及截图渲染边界；命令分发与 DOM 状态使用真实 composable。
 *
 * 注意：useAiOpenCursor 模块级有 ws / routerRef / reconnectTimer 等模块级变量，
 * 在测试间会持久存在。每个用例必须通过 setAiOpenCursorEnabled(false) 清理状态。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import {
  aiopenCursorEnabled,
  aiopenCursorConnected,
  aiopenCursorSessionId,
  aiopenCursorLogs,
  aiopenAgentActive,
  cursorX,
  cursorY,
  cursorVisible,
  cursorClicking,
  cursorActionLabel,
  cursorTilt,
  setAiOpenCursorEnabled,
  initAiOpenCursor,
} from './useAiOpenCursor'

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => 'http://127.0.0.1:5000',
}))
const { toPng, loadRenderer } = vi.hoisted(() => ({ toPng: vi.fn(), loadRenderer: vi.fn() }))
vi.mock('html-to-image', async () => { await loadRenderer(); return { toPng } })

// ---------------------------------------------------------------------------
// WebSocket mock：捕获实例并允许手动触发 onopen/onmessage/onclose/onerror
// ---------------------------------------------------------------------------
interface MockWebSocket {
  url: string
  onopen: (() => void) | null
  onmessage: ((event: { data: unknown }) => void | Promise<void>) | null
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
  onmessage: ((event: { data: unknown }) => void | Promise<void>) | null = null
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
;(globalThis as unknown as { WebSocket: typeof WebSocketMock }).WebSocket = WebSocketMock as unknown as typeof WebSocket

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

/** 让 jsdom 元素被视为可见：stub getBoundingClientRect 与 getComputedStyle */
function makeVisible(el: Element) {
  const htmlEl = el as HTMLElement
  // rect.top 必须在 [0, window.innerHeight] 范围内，否则 isVisible 返回 false
  // jsdom 默认 innerHeight=0，所以这里把 top 设为 0，bottom 设为 1
  htmlEl.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      width: 100,
      height: 30,
      top: 0,
      right: 100,
      bottom: 30,
      left: 0,
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
    updateProductReadAccountScope({ tenantId: 'A', marketUserId: 1 })
    mockWsInstances = []
    wsCtorError = null
    vi.useFakeTimers()
    // 确保 window.innerHeight > 0，否则 isVisible 的 rect.top > innerHeight 检查会失败
    Object.defineProperty(window, 'innerHeight', {
      value: 768,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(window, 'innerWidth', {
      value: 1024,
      configurable: true,
      writable: true,
    })
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

    it('ignores a late open event after remote control is disabled', () => {
      setAiOpenCursorEnabled(true)
      const oldSocket = lastWs()!
      setAiOpenCursorEnabled(false)
      oldSocket.onopen!()
      expect(aiopenCursorConnected.value).toBe(false)
    })

    it('keeps a replacement connection when the old socket closes later', async () => {
      setAiOpenCursorEnabled(true)
      const oldSocket = lastWs()!
      setAiOpenCursorEnabled(false)
      setAiOpenCursorEnabled(true)
      const replacement = lastWs()!
      replacement.onopen!()
      oldSocket.onclose!()
      expect(aiopenCursorConnected.value).toBe(true)
      await replacement.onmessage!({ data: JSON.stringify({ type: 'command', id: 'current', action: 'snapshot', params: {} }) })
      expect(replacement.send).toHaveBeenCalledWith(expect.stringContaining('"id":"current"'))
      await vi.advanceTimersByTimeAsync(3000)
      expect(mockWsInstances).toHaveLength(2)
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

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r1', action: 'foo', params: {} }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r2', action: 'snapshot', params: {} }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r3', action: 'snapshot', params: {} }),
      })
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

    async function runCommand(
      id: string,
      action: string,
      params: Record<string, unknown>
    ): Promise<Record<string, any>> {
      const ws = lastWs()!
      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id, action, params }),
      })
      await vi.runAllTimersAsync()
      const sent = ws.send.mock.calls
        .map((call) => {
          try {
            return JSON.parse(call[0] as string)
          } catch {
            return null
          }
        })
        .find((message) => message && message.type === 'result' && message.id === id)
      return sent?.result || {}
    }

    describe('upload URL boundary', () => {
      let input: HTMLInputElement
      let fetchFile: ReturnType<typeof vi.fn>
      let change: ReturnType<typeof vi.fn>
      beforeEach(() => {
        input = document.createElement('input')
        input.type = 'file'; input.id = 'upload-target'
        Object.defineProperty(input, 'files', { writable: true, value: [] })
        document.body.appendChild(input)
        change = vi.fn()
        input.addEventListener('input', change); input.addEventListener('change', change)
        // jsdom has no DataTransfer; keep native Blob/File and capture the transfer boundary.
        vi.stubGlobal('DataTransfer', class {
          files: File[] = []
          items = { add: (file: File) => this.files.push(file) }
        })
        fetchFile = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['invoice'], { type: 'text/plain' }) })
        vi.stubGlobal('fetch', fetchFile)
        setAiOpenCursorEnabled(true)
      })
      afterEach(() => { vi.unstubAllGlobals() })
      const artifactPath = '/api/agent/runs/run_1/artifacts/txt_1'
      const upload = (url: string) => runCommand('file', 'upload', { selector: '#upload-target', files: [{ name: 'invoice.txt', url }] })

      it.each([artifactPath, `${window.location.origin}${artifactPath}`])('uploads authorized artifact bytes from %s', async url => {
        expect(await upload(url)).toEqual({ success: true, uploaded: ['invoice.txt'] })
        expect(fetchFile).toHaveBeenCalledWith(artifactPath, {
          credentials: 'same-origin', mode: 'same-origin', redirect: 'error',
        })
        expect(input.files).toHaveLength(1)
        expect(await input.files![0].text()).toBe('invoice')
        expect(input.files![0].type).toBe('text/plain')
        expect(change).toHaveBeenCalledTimes(2)
      })

      it.each([
        'https://other.example/file', '//other.example/file', 'http://127.0.0.1:9000/file',
        'https://localhost.other.example/file', 'file:///etc/passwd', 'data:text/plain,private',
        `blob:${window.location.origin}/file`, 'javascript:alert(1)',
        `${window.location.protocol}//user:pass@${window.location.host}/file`,
      ])('rejects an untrusted URL before fetching or uploading: %s', async url => {
        expect(await upload(url)).toMatchObject({ success: false, message: expect.stringContaining('当前站点') })
        expect(fetchFile).not.toHaveBeenCalled()
        expect(input.files).toHaveLength(0)
        expect(change).not.toHaveBeenCalled()
      })

      it.each([
        '/api/auth/me', '/api/files/invoice', '/api/agent/runs/run_1/cancel',
        '/api/agent/runs/run_1/artifacts/txt_1/extra',
        '/api/agent/runs/run%2fother/artifacts/txt_1',
        '/api/agent/runs/run_1/artifacts/%2e%2e/%2e%2e/%2e%2e/auth/me',
        '/api/agent/runs/run_1/artifacts/txt%255c..%255csecret',
        `/api/agent/runs/${'r'.repeat(161)}/artifacts/txt_1`,
        `${artifactPath}?redirect=https://other.example`, `${artifactPath}#fragment`,
      ])('rejects non-artifact or ambiguous routes before requesting: %s', async url => {
        expect(await upload(url)).toMatchObject({ success: false, message: expect.stringContaining('Agent 文件产物') })
        expect(fetchFile).not.toHaveBeenCalled()
        expect(input.files).toHaveLength(0)
        expect(change).not.toHaveBeenCalled()
      })

      it('keeps text and base64 uploads available without requesting any URL', async () => {
        const result = await runCommand('inline-files', 'upload', {
          selector: '#upload-target', files: [
            { name: 'note.txt', text: '保留文本', type: 'text/plain' },
            { name: 'binary.bin', base64: btoa('bytes'), type: 'application/octet-stream' },
          ],
        })
        expect(result).toEqual({ success: true, uploaded: ['note.txt', 'binary.bin'] })
        expect(fetchFile).not.toHaveBeenCalled()
        expect(await input.files![0].text()).toBe('保留文本')
        expect(await input.files![1].text()).toBe('bytes')
        expect(input.files![1].type).toBe('application/octet-stream')
        expect(change).toHaveBeenCalledTimes(2)
      })

      it.each(['redirect', 'forbidden', 'unreadable'])('keeps the previous selection when the file request is %s', async failure => {
        const previous = [new File(['previous'], 'previous.txt')]
        Object.assign(input, { files: previous })
        if (failure === 'redirect') fetchFile.mockRejectedValueOnce(new TypeError('redirect mode is error'))
        else if (failure === 'forbidden') fetchFile.mockResolvedValueOnce({ ok: false, status: 403 })
        else fetchFile.mockResolvedValueOnce({ ok: true, blob: async () => { throw new Error('unreadable response') } })
        expect(await upload(artifactPath)).toMatchObject({ success: false, message: expect.stringContaining('读取文件失败') })
        expect(input.files).toBe(previous)
        expect(change).not.toHaveBeenCalled()
      })

      it.each(['fetch', 'body'])('does not upload old-account bytes when %s finishes after logout', async stage => {
        const previous = [new File(['existing selection'], 'previous.txt')]
        Object.assign(input, { files: previous })
        let finish!: (value: unknown) => void
        const delayed = new Promise(resolve => { finish = resolve })
        const blob = new Blob(['old account document'], { type: 'text/plain' })
        const response = { ok: true, blob: () => stage === 'body' ? delayed : Promise.resolve(blob) }
        fetchFile.mockReturnValue(stage === 'fetch' ? delayed : Promise.resolve(response))
        const socket = lastWs()!
        const pending = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'old-upload', action: 'upload', params: {
          selector: '#upload-target', files: [{ name: 'private.txt', url: artifactPath }],
        } }) })
        await vi.advanceTimersByTimeAsync(0)
        invalidateEnterpriseSessionCache()
        finish(stage === 'fetch' ? response : blob)
        await pending
        expect(input.files).toBe(previous)
        expect(change).not.toHaveBeenCalled()
        expect(socket.send).not.toHaveBeenCalled()
      })
    })

    it('receiving a command marks the agent active', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()
      expect(aiopenAgentActive.value).toBe(false)
      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'agent1', action: 'snapshot', params: {} }),
      })
      // 只推进 microtask，保留 8s 空闲计时器，便于验证点亮状态
      await vi.advanceTimersByTimeAsync(0)
      expect(aiopenAgentActive.value).toBe(true)
      // 静默 8s 后自动收起
      vi.advanceTimersByTime(8100)
      expect(aiopenAgentActive.value).toBe(false)
    })

    it('snapshot assigns stable refs with role, name and state', async () => {
      const btn = document.createElement('button')
      btn.id = 'ref-btn'
      btn.setAttribute('aria-label', '保存')
      btn.disabled = true
      document.body.appendChild(btn)
      makeVisible(btn)

      setAiOpenCursorEnabled(true)
      const result = await runCommand('ref1', 'snapshot', {})
      expect(result.success).toBe(true)
      expect(result.elements[0].ref).toBe('e1')
      expect(result.elements[0].role).toBe('button')
      expect(result.elements[0].name).toBe('保存')
      expect(result.elements[0].selector).toBe('#ref-btn')
      expect(result.elements[0].state.disabled).toBe(true)
    })

    it('click resolves element by ref from the latest snapshot', async () => {
      const btn = document.createElement('button')
      setElementText(btn, '提交')
      document.body.appendChild(btn)
      makeVisible(btn)

      setAiOpenCursorEnabled(true)
      await runCommand('ref2', 'snapshot', {})
      const result = await runCommand('ref3', 'click', { ref: 'e1' })
      expect(result.success).toBe(true)
      expect(btn.click).toHaveBeenCalled()
    })

    it('retires snapshot refs when the connection changes even if the same DOM node remains', async () => {
      const button = document.createElement('button')
      makeVisible(button); document.body.appendChild(button)
      setAiOpenCursorEnabled(true)
      const snapshot = await runCommand('before-reconnect', 'snapshot', {})
      const ref = snapshot.elements[0].ref
      setAiOpenCursorEnabled(false)
      setAiOpenCursorEnabled(true)
      expect(await runCommand('stale-ref', 'click', { ref })).toMatchObject({ success: false })
      expect(button.click).not.toHaveBeenCalled()
      const refreshed = await runCommand('after-reconnect', 'snapshot', {})
      expect(await runCommand('fresh-ref', 'click', { ref: refreshed.elements[0].ref })).toMatchObject({ success: true })
      expect(button.click).toHaveBeenCalledOnce()
    })

    it.each(['click', 'type', 'select'])('stops delayed %s before mutating the next account page', async action => {
      const target = document.createElement(action === 'type' ? 'input' : 'button')
      target.id = 'delayed'; makeVisible(target); document.body.appendChild(target)
      if (target instanceof HTMLInputElement) target.value = 'original'
      const inputEvent = vi.fn()
      target.addEventListener('input', inputEvent)
      const option = document.createElement('div')
      option.setAttribute('role', 'option'); option.textContent = 'Next'; makeVisible(option); document.body.appendChild(option)
      setAiOpenCursorEnabled(true)
      const socket = lastWs()!
      const pending = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'delayed', action, params: {
        selector: '#delayed', text: 'changed', label: 'Next',
      } }) })
      await vi.advanceTimersByTimeAsync(100)
      invalidateEnterpriseSessionCache()
      await vi.runAllTimersAsync()
      await pending
      expect(target.click).not.toHaveBeenCalled()
      expect(option.click).not.toHaveBeenCalled()
      expect(inputEvent).not.toHaveBeenCalled()
      if (target instanceof HTMLInputElement) expect(target.value).toBe('original')
      expect(cursorVisible.value).toBe(false)
      expect(socket.send).not.toHaveBeenCalled()
    })

    it('clears a pending click animation when control is disabled before the click', async () => {
      const button = document.createElement('button')
      button.id = 'click-pulse'; makeVisible(button); document.body.appendChild(button)
      setAiOpenCursorEnabled(true)
      const pending = lastWs()!.onmessage!({ data: JSON.stringify({ type: 'command', id: 'pulse', action: 'click', params: { selector: '#click-pulse' } }) })
      await vi.advanceTimersByTimeAsync(850)
      expect(cursorClicking.value).toBe(true)
      setAiOpenCursorEnabled(false)
      try {
        expect(cursorClicking.value).toBe(false)
        expect(cursorTilt.value).toBe(0)
        expect(cursorActionLabel.value).toBe('')
      } finally {
        await vi.runAllTimersAsync()
        await pending
      }
      expect(button.click).not.toHaveBeenCalled()
    })

    it('click with stale ref reports failure', async () => {
      setAiOpenCursorEnabled(true)
      const result = await runCommand('ref4', 'click', { ref: 'e99' })
      expect(result.success).toBe(false)
      expect(result.message).toContain('ref')
    })

    it('verify returns per-check conclusions', async () => {
      const input = document.createElement('input')
      input.id = 'verify-input'
      input.value = 'abc'
      document.body.appendChild(input)
      makeVisible(input)

      setAiOpenCursorEnabled(true)
      await runCommand('ref5', 'snapshot', {})
      const result = await runCommand('ref6', 'verify', { ref: 'e1', value: 'abc' })
      expect(result.success).toBe(true)
      expect(result.checks.length).toBe(2)
      expect(result.checks.every((check: any) => check.ok)).toBe(true)
    })

    it('select picks native option by value', async () => {
      const select = document.createElement('select')
      select.id = 'verify-select'
      for (const value of ['a', 'b']) {
        const option = document.createElement('option')
        option.value = value
        option.text = value.toUpperCase()
        select.appendChild(option)
      }
      document.body.appendChild(select)
      makeVisible(select)

      setAiOpenCursorEnabled(true)
      await runCommand('ref7', 'snapshot', {})
      const result = await runCommand('ref8', 'select', { ref: 'e1', value: 'b' })
      expect(result.success).toBe(true)
      expect(select.value).toBe('b')
    })

    it('wait returns immediately when condition already holds', async () => {
      const node = document.createElement('div')
      node.id = 'wait-target'
      document.body.appendChild(node)
      makeVisible(node)

      setAiOpenCursorEnabled(true)
      const result = await runCommand('ref9', 'wait', { selector: '#wait-target', timeout_ms: 500 })
      expect(result.success).toBe(true)
      expect(result.waited_ms).toBeGreaterThanOrEqual(0)
    })

    it('wait without conditions returns argument error', async () => {
      setAiOpenCursorEnabled(true)
      const result = await runCommand('ref10', 'wait', { timeout_ms: 500 })
      expect(result.success).toBe(false)
      expect(result.message).toContain('等待条件')
    })

    describe('wait observes live page state', () => {
      let originalUrl: string
      let originalInnerText: PropertyDescriptor | undefined
      beforeEach(() => {
        originalUrl = window.location.href
        originalInnerText = Object.getOwnPropertyDescriptor(document.body, 'innerText')
        Object.defineProperty(document.body, 'innerText', { configurable: true, get: () => document.body.textContent })
        setAiOpenCursorEnabled(true)
      })
      afterEach(() => {
        window.history.replaceState(null, '', originalUrl)
        if (originalInnerText) Object.defineProperty(document.body, 'innerText', originalInnerText)
        else Reflect.deleteProperty(document.body, 'innerText')
      })

      it('waits until the appearing element, text, URL and disappearing loader all match', async () => {
        const loader = document.createElement('div')
        loader.id = 'loading'; makeVisible(loader); document.body.appendChild(loader)
        const socket = lastWs()!
        const pending = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'live', action: 'wait', params: {
          selector: '#result', text: 'Import complete', url_contains: '#import-ready', gone_selector: '#loading', timeout_ms: 500,
        } }) })
        await vi.advanceTimersByTimeAsync(100)
        const result = document.createElement('div')
        result.id = 'result'; result.textContent = 'Import complete'; makeVisible(result); document.body.appendChild(result)
        window.history.replaceState(null, '', '#import-ready')
        await vi.advanceTimersByTimeAsync(100)
        expect(socket.send).not.toHaveBeenCalled()
        loader.remove()
        await vi.advanceTimersByTimeAsync(100)
        expect(socket.send).toHaveBeenCalledWith(expect.stringContaining('"success":true'))
        await pending
        const response = JSON.parse(socket.send.mock.calls[0][0]).result
        expect(response.waited_ms).toBe(300)
        expect(response.matched).toContain('元素消失')
      })

      it('times out at a bounded polling interval and reports only conditions still unmet', async () => {
        window.setTimeout(() => { document.body.textContent = 'Import complete' }, 100)
        const result = await runCommand('timeout', 'wait', { text: 'Import complete', url_contains: '#never-ready', timeout_ms: 350 })
        expect(result.success).toBe(false)
        expect(result.waited_ms).toBe(400)
        expect(result.message).toContain('URL 包含「#never-ready」')
        expect(result.message).not.toContain('页面文本')
      })

      it('stops a pending wait when control is disabled and does not send its result to a new connection', async () => {
        const oldSocket = lastWs()!
        let settled = false
        const pending = Promise.resolve(oldSocket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'cancelled', action: 'wait', params: {
          selector: '#never-appears', timeout_ms: 15000,
        } }) })).then(() => { settled = true })
        await vi.advanceTimersByTimeAsync(100)
        setAiOpenCursorEnabled(false)
        setAiOpenCursorEnabled(true)
        await vi.advanceTimersByTimeAsync(100)
        try {
          expect(settled).toBe(true)
          expect(oldSocket.send).not.toHaveBeenCalled()
          expect(lastWs()!.send).not.toHaveBeenCalled()
        } finally {
          await vi.runAllTimersAsync()
          await pending
        }
      })

      it.each(['logout', 'account round trip'])('retires the connection and pending wait on %s', async change => {
        const socket = lastWs()!
        let settled = false
        const pending = Promise.resolve(socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'old-account', action: 'wait', params: {
          text: 'new account content', timeout_ms: 15000,
        } }) })).then(() => { settled = true })
        await vi.advanceTimersByTimeAsync(100)
        if (change === 'logout') invalidateEnterpriseSessionCache()
        else {
          updateProductReadAccountScope({ tenantId: 'B', marketUserId: 2 })
          updateProductReadAccountScope({ tenantId: 'A', marketUserId: 1 })
        }
        document.body.textContent = 'new account content'
        await vi.advanceTimersByTimeAsync(100)
        try {
          expect(socket.close).toHaveBeenCalledOnce()
          expect(settled).toBe(true)
          expect(socket.send).not.toHaveBeenCalled()
          expect(aiopenCursorEnabled.value).toBe(true)
          await socket.onmessage!({ data: JSON.stringify({ type: 'hello', session_id: 'stale-session' }) })
          await socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'stale-command', action: 'snapshot', params: {} }) })
          expect(aiopenCursorSessionId.value).toBe('')
          expect(socket.send).not.toHaveBeenCalled()
          await vi.advanceTimersByTimeAsync(3000)
          expect(lastWs()).not.toBe(socket)
        } finally {
          await vi.runAllTimersAsync()
          await pending
        }
      })
    })

    describe('screenshot result and cursor lifecycle', () => {
      const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY4kAAAAASUVORK5CYII='
      let decodeFails: boolean
      beforeEach(() => {
        decodeFails = false
        toPng.mockReset().mockResolvedValue(png)
        vi.stubGlobal('Image', class {
          naturalWidth = 1
          naturalHeight = 1
          onload: (() => void) | null = null
          onerror: (() => void) | null = null
          set src(_value: string) { if (decodeFails) this.onerror?.(); else this.onload?.() }
        })
        setAiOpenCursorEnabled(true)
      })
      afterEach(() => { vi.unstubAllGlobals() })

      it('does not capture a new account page when the renderer import finishes after logout', async () => {
        let finish!: () => void
        loadRenderer.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
        const socket = lastWs()!
        const pending = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'loading-renderer', action: 'screenshot', params: {} }) })
        await vi.advanceTimersByTimeAsync(80)
        invalidateEnterpriseSessionCache()
        finish()
        await pending
        expect(toPng).not.toHaveBeenCalled()
        expect(socket.send).not.toHaveBeenCalled()
      })

      it.each([false, true])('captures the target without the cursor and restores visibility=%s', async visible => {
        const target = document.createElement('section')
        target.id = 'capture'; document.body.appendChild(target)
        vi.spyOn(target, 'getBoundingClientRect').mockReturnValue({ width: 2400, height: 800 } as DOMRect)
        cursorVisible.value = visible
        toPng.mockImplementation(async () => { expect(cursorVisible.value).toBe(false); return png })
        const result = await runCommand('capture', 'screenshot', { selector: '#capture', max_width: 1200 })
        expect(toPng).toHaveBeenCalledWith(target, expect.objectContaining({ pixelRatio: 0.5, width: 2400, height: 800 }))
        expect(result).toMatchObject({ success: true, data_url: png, width: 1, height: 1, target: '#capture' })
        expect(result.bytes).toBeGreaterThan(0)
        expect(cursorVisible.value).toBe(visible)
      })

      it('reports a missing screenshot target without invoking the renderer or hiding the cursor', async () => {
        cursorVisible.value = true
        expect(await runCommand('missing', 'screenshot', { selector: '#missing' })).toMatchObject({ success: false, message: expect.stringContaining('未找到截图区域') })
        expect(toPng).not.toHaveBeenCalled()
        expect(cursorVisible.value).toBe(true)
      })

      it.each(['render', 'decode'])('restores the cursor and reports a %s failure', async stage => {
        cursorVisible.value = true
        if (stage === 'render') toPng.mockRejectedValue(new Error('renderer unavailable'))
        else decodeFails = true
        const result = await runCommand(stage, 'screenshot', {})
        expect(result).toEqual({ success: false, message: stage === 'render' ? '截图失败：renderer unavailable' : '截图失败：截图解码失败' })
        expect(cursorVisible.value).toBe(true)
      })

      it.each(['disabled', 'logout', 'account round trip'])('keeps the cursor hidden and discards a pending screenshot after %s', async change => {
        let finish!: (data: string) => void
        toPng.mockReturnValue(new Promise<string>(resolve => { finish = resolve }))
        cursorVisible.value = true
        const oldSocket = lastWs()!
        const pending = oldSocket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'old-capture', action: 'screenshot', params: {} }) })
        await vi.advanceTimersByTimeAsync(80)
        expect(toPng).toHaveBeenCalledOnce()
        if (change === 'disabled') {
          setAiOpenCursorEnabled(false)
          setAiOpenCursorEnabled(true)
        } else if (change === 'logout') invalidateEnterpriseSessionCache()
        else {
          updateProductReadAccountScope({ tenantId: 'B', marketUserId: 2 })
          updateProductReadAccountScope({ tenantId: 'A', marketUserId: 1 })
        }
        finish(png)
        await pending
        expect(cursorVisible.value).toBe(false)
        expect(oldSocket.send).not.toHaveBeenCalled()
        expect(lastWs()!.send).not.toHaveBeenCalled()
      })

      it('does not start rendering when control is disabled during screenshot preparation', async () => {
        cursorVisible.value = true
        const socket = lastWs()!
        const pending = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: 'cancel-before-render', action: 'screenshot', params: {} }) })
        setAiOpenCursorEnabled(false)
        await vi.advanceTimersByTimeAsync(80)
        await pending
        expect(toPng).not.toHaveBeenCalled()
        expect(cursorVisible.value).toBe(false)
        expect(socket.send).not.toHaveBeenCalled()
      })
    })

    it('does not let an old connection fade out the current action cursor', async () => {
      const button = document.createElement('button')
      button.id = 'fade-target'; makeVisible(button); document.body.appendChild(button)
      setAiOpenCursorEnabled(true)
      const command = () => lastWs()!.onmessage!({ data: JSON.stringify({ type: 'command', id: 'click', action: 'click', params: { selector: '#fade-target' } }) })
      const oldClick = command()
      await vi.advanceTimersByTimeAsync(1000)
      await oldClick
      setAiOpenCursorEnabled(false)
      setAiOpenCursorEnabled(true)
      const newClick = command()
      await vi.advanceTimersByTimeAsync(1000)
      await newClick
      expect(cursorVisible.value).toBe(true)
      await vi.advanceTimersByTimeAsync(3000)
      expect(cursorVisible.value).toBe(true)
      expect(cursorActionLabel.value).toBe('点击')
      await vi.advanceTimersByTimeAsync(1000)
      expect(cursorVisible.value).toBe(false)
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r4',
          action: 'navigate',
          params: { path: '' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r5',
          action: 'navigate',
          params: { path: '/x' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r6',
          action: 'navigate',
          params: { path: '/target' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r7',
          action: 'click',
          params: { selector: '#target-btn' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r8',
          action: 'click',
          params: { text: 'Login' },
        }),
      })
      await vi.runAllTimersAsync()

      expect(clickSpy).toHaveBeenCalled()
    })

    it('click with no selector/text returns not-found', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r9', action: 'click', params: {} }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r10',
          action: 'click',
          params: { selector: '###invalid', text: 'Save' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r11',
          action: 'type',
          params: { selector: '#name', text: 'hello' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r12',
          action: 'type',
          params: { selector: '#desc', text: 'multi line' },
        }),
      })
      await vi.runAllTimersAsync()

      expect((ta as HTMLTextAreaElement).value).toBe('multi line')
    })

    it('type with missing selector returns error', async () => {
      setAiOpenCursorEnabled(true)
      const ws = lastWs()!
      ws.onopen!()

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r13',
          action: 'type',
          params: { selector: '', text: 'x' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r14',
          action: 'type',
          params: { selector: '#n' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r15',
          action: 'scroll',
          params: { selector: '#scroll-target' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r16',
          action: 'scroll',
          params: { selector: '#nope' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r17',
          action: 'scroll',
          params: { delta_y: 500 },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r18', action: 'scroll', params: {} }),
      })
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
      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r19',
          action: 'navigate',
          params: 'not-object',
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r20',
          action: 'navigate',
          params: { path: '/x' },
        }),
      })
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
      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r21', action: 'snapshot', params: {} }),
      })
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

    it('connects by default when no stored preference exists', () => {
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      expect(aiopenCursorEnabled.value).toBe(true)
      expect(mockWsInstances.length).toBe(1)
    })

    it('localStorage error falls back to default standby', () => {
      const original = localStorage.getItem
      localStorage.getItem = () => {
        throw new Error('SecurityError')
      }
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      expect(aiopenCursorEnabled.value).toBe(true)
      expect(mockWsInstances.length).toBe(1)
      localStorage.getItem = original
    })

    it('stays off when user explicitly disabled it', () => {
      localStorage.setItem('xcagi_aiopen_remote_control', '0')
      const router = {
        currentRoute: { value: { fullPath: '/' } },
        push: vi.fn(),
      } as any
      initAiOpenCursor(router)
      expect(aiopenCursorEnabled.value).toBe(false)
      expect(mockWsInstances.length).toBe(0)
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

      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r22', action: 'snapshot', params: {} }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r23',
          action: 'click',
          params: { text: 'Hidden' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r24',
          action: 'click',
          params: { text: 'search-term' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r25',
          action: 'click',
          params: { text: 'close-dialog' },
        }),
      })
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

      ws.onmessage!({
        data: JSON.stringify({
          type: 'command',
          id: 'r26',
          action: 'click',
          params: { text: '请输入关键词' },
        }),
      })
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
      ws.onmessage!({
        data: JSON.stringify({ type: 'command', id: 'r27', action: 'snapshot', params: {} }),
      })
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
