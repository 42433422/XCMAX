/**
 * useChatVoiceInput coverage ramp 测试
 *
 * 目标：覆盖 useChatVoiceInput.ts 的核心路径，包括录音启动、停止、取消、
 * 转录成功/失败、浏览器 API 不可用、权限拒绝、录音太短、空音频等场景。
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useChatVoiceInput } from './useChatVoiceInput'

// ── BlobEvent polyfill（jsdom 不提供） ────────────────────────────────
if (typeof globalThis.BlobEvent === 'undefined') {
  class BlobEventPolyfill extends Event {
    data: Blob
    constructor(type: string, init: { data: Blob }) {
      super(type)
      this.data = init.data
    }
  }
  ;(globalThis as unknown as { BlobEvent: typeof BlobEventPolyfill }).BlobEvent =
    BlobEventPolyfill
}

// ── helpers ──────────────────────────────────────────────────────────

/** 创建一个 mock MediaStream，带可控的 track */
function makeMockStream() {
  const stopFn = vi.fn()
  const track = { stop: stopFn }
  return {
    getTracks: () => [track],
    _stopFn: stopFn,
  }
}

/** 创建一个 mock MediaRecorder，可手动触发 dataavailable / stop / error 事件 */
function createMockMediaRecorder(stream: unknown, options?: { mimeType?: string }) {
  const listeners: Record<string, Array<(e: Event) => void>> = {}
  const stateRef = { value: 'inactive' as string }
  const recorder = {
    get state() { return stateRef.value },
    set state(v: string) { stateRef.value = v },
    stream,
    mimeType: options?.mimeType || '',
    start: vi.fn(() => {
      stateRef.value = 'recording'
    }),
    stop: vi.fn(() => {
      stateRef.value = 'inactive'
      // 触发 stop 事件
      const handlers = listeners['stop'] || []
      handlers.forEach((h) => h(new Event('stop')))
    }),
    addEventListener: vi.fn((event: string, handler: (e: Event) => void) => {
      if (!listeners[event]) listeners[event] = []
      listeners[event].push(handler)
    }),
    removeEventListener: vi.fn(),
    dispatchDataAvailable: (blob: Blob) => {
      const handlers = listeners['dataavailable'] || []
      const evt = new (globalThis as any).BlobEvent('dataavailable', { data: blob })
      handlers.forEach((h) => h(evt))
    },
    dispatchError: (message: string) => {
      const handlers = listeners['error'] || []
      handlers.forEach((h) =>
        h(Object.assign(new Event('error'), { error: { message } })),
      )
    },
  }
  return recorder
}

/** 创建一个 MediaRecorder mock 类，state 通过 getter/setter 共享 */
function makeMediaRecorderClass(mockRecorder: ReturnType<typeof createMockMediaRecorder>) {
  return class {
    static isTypeSupported() { return true }
    get state() { return mockRecorder.state }
    set state(v: string) { mockRecorder.state = v }
    start = mockRecorder.start
    stop = mockRecorder.stop
    addEventListener = mockRecorder.addEventListener
    removeEventListener = mockRecorder.removeEventListener
  }
}

async function flushVoiceAsyncWork() {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

/** 简单的 MediaRecorder mock 类（用于权限拒绝等不会真正录音的场景） */
function makeSimpleMediaRecorderClass(options: {
  isTypeSupported?: () => boolean
  startImpl?: () => void
} = {}) {
  return class {
    static isTypeSupported = options.isTypeSupported || (() => true)
    state = 'inactive'
    start = options.startImpl || function () { (this as any).state = 'recording' }
    stop() { (this as any).state = 'inactive' }
    addEventListener() {}
    removeEventListener() {}
  }
}

// ── 测试套件 ─────────────────────────────────────────────────────────

describe('useChatVoiceInput – coverage ramp', () => {
  let origMediaRecorder: unknown
  let origGetUserMedia: unknown
  let origMediaDevices: unknown

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    // 保存原始值
    origMediaRecorder = (window as unknown as Record<string, unknown>).MediaRecorder
    origMediaDevices = navigator.mediaDevices
    origGetUserMedia = navigator.mediaDevices?.getUserMedia
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    // 恢复浏览器 API
    if (origMediaRecorder !== undefined) {
      Object.defineProperty(window, 'MediaRecorder', {
        configurable: true,
        value: origMediaRecorder,
      })
    }
    if (origMediaDevices !== undefined) {
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: origMediaDevices,
      })
    }
  })

  // ── computed 属性：idle 状态 ─────────────────────────────────────

  it('idle 状态下所有 computed 返回预期值', () => {
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    expect(api.voiceButtonDisabled.value).toBe(false)
    expect(api.voiceButtonClass.value).toEqual({
      'voice-input-btn-idle': true,
      'voice-input-btn-recording': false,
      'voice-input-btn-transcribing': false,
      'voice-input-btn-error': false,
    })
    expect(api.voiceButtonIcon.value).toBe('fa-microphone')
    expect(api.voiceButtonText.value).toBe('按住说话')
    expect(api.voiceButtonTitle.value).toContain('按住这里说话')
  })

  it('isLoading=true 时按钮禁用', () => {
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(true) })
    expect(api.voiceButtonDisabled.value).toBe(true)
  })

  // ── startVoiceRecording：浏览器 API 不可用 ───────────────────────

  it('getUserMedia 不存在时设置错误状态', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {},
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')
    expect(api.voiceButtonText.value).toContain('不支持麦克风采集')
  })

  it('MediaRecorder 未定义时设置错误状态', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(makeMockStream()) },
    })
    // @ts-expect-error test
    delete window.MediaRecorder
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')
    expect(api.voiceButtonText.value).toContain('不支持 MediaRecorder')
  })

  // ── startVoiceRecording：权限拒绝 ────────────────────────────────

  it('NotAllowedError 权限被拒绝', async () => {
    const stream = makeMockStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ name: 'NotAllowedError' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')
    expect(api.voiceButtonText.value).toContain('权限被拒绝')
  })

  it('SecurityError 权限被拒绝', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ name: 'SecurityError' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('权限被拒绝')
  })

  it('NotFoundError 未检测到麦克风', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ name: 'NotFoundError' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('未检测到可用麦克风')
  })

  it('OverconstrainedError 未检测到麦克风', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ name: 'OverconstrainedError' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('未检测到可用麦克风')
  })

  it('其他未知 getUserMedia 错误', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ name: 'SomeError', message: 'boom' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('获取麦克风失败')
  })

  // ── startVoiceRecording：MediaRecorder 创建失败 ──────────────────

  it('MediaRecorder 构造函数抛异常时设置错误', async () => {
    const stream = makeMockStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: class {
        static isTypeSupported() { return true }
        constructor() { throw new Error('构造失败') }
      },
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('无法创建录音器')
  })

  // ── startVoiceRecording：MediaRecorder.start() 失败 ──────────────

  it('MediaRecorder.start() 抛异常时设置错误', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)
    mockRecorder.start.mockImplementation(() => {
      throw new Error('启动失败')
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass({ startImpl: () => { throw new Error('启动失败') } }),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('启动录音失败')
  })

  // ── 正常录音流程：录音 → 停止 → 转录成功 ────────────────────────

  it('完整录音流程：录音 → 停止 → 转录成功 → 文字填入输入框', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    // mock fetch 转录 API
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true, data: { text: '你好世界' } }),
    } as unknown as Response)

    const messageInput = ref('')
    const api = useChatVoiceInput({ messageInput, isLoading: ref(false) })

    // 启动录音
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')
    expect(api.voiceButtonText.value).toContain('松开发送')

    // 模拟时间经过（确保录音时长 > MIN_RECORD_MS）
    vi.advanceTimersByTime(500)

    // 先触发 dataavailable 事件（填充 voiceChunks），再停止录音
    mockRecorder.dispatchDataAvailable(new Blob(['audio-data'], { type: 'audio/webm' }))

    // 停止录音（非取消）→ 触发 stop 事件 → 读取 voiceChunks → submitVoiceBlob
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    // 验证 fetch 被调用
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/voice/transcribe',
      expect.objectContaining({ method: 'POST' }),
    )

    // 验证转录文字填入
    expect(messageInput.value).toBe('你好世界')
  })

  // ── 转录成功：追加到已有文字 ─────────────────────────────────────

  it('转录成功时追加到已有文字', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true, data: { text: '追加文字' } }),
    } as unknown as Response)

    const messageInput = ref('已有文字')
    const api = useChatVoiceInput({ messageInput, isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(messageInput.value).toBe('已有文字 追加文字')
  })

  // ── 转录失败：API 返回错误 ───────────────────────────────────────

  it('转录 API 返回 HTTP 错误时设置错误状态', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ success: false, message: '服务器错误' }),
    } as unknown as Response)

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')
    expect(api.voiceButtonText.value).toContain('服务器错误')
  })

  // ── 转录失败：success=false ──────────────────────────────────────

  it('转录 API 返回 success=false 时设置错误状态', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: false, error: '模型不可用' }),
    } as unknown as Response)

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('模型不可用')
  })

  // ── 转录失败：fetch 抛异常 ───────────────────────────────────────

  it('fetch 抛网络异常时设置错误状态', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'))

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await flushVoiceAsyncWork()

    expect(api.voiceButtonText.value).toContain('Network error')
  })

  // ── 转录失败：空识别结果 ─────────────────────────────────────────

  it('转录返回空文字时设置"未识别到内容"错误', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true, data: { text: '' } }),
    } as unknown as Response)

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('未识别到内容')
  })

  // ── 转录失败：响应体非 JSON ──────────────────────────────────────

  it('转录返回非 JSON 响应时设置错误状态', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 502,
      text: async () => 'Bad Gateway',
    } as unknown as Response)

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('Bad Gateway')
  })

  // ── 取消录音 ─────────────────────────────────────────────────────

  it('取消录音后不提交转录，状态回到 idle', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)

    // 取消录音
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(true)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    // fetch 不应被调用
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(api.voiceButtonIcon.value).toBe('fa-microphone')
  })

  // ── 录音太短 ─────────────────────────────────────────────────────

  it('录音时长 < 300ms 时提示"录音太短"', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    // 先填充 voiceChunks，再立即停止（录音时长 ≈ 0ms）
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('录音太短')
  })

  // ── 空音频数据 ───────────────────────────────────────────────────

  it('录音数据为空 Blob 时提示"未采到音频数据"', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    api.stopVoiceRecording(false)
    // 不触发 dataavailable → voiceChunks 为空 → Blob size = 0

    // 只推进少量定时器，避免 tick 定时器导致的无限循环
    await nextTick()
    vi.advanceTimersByTime(10)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('未采到音频数据')
  })

  // ── MediaRecorder error 事件 ─────────────────────────────────────

  it('MediaRecorder 触发 error 事件时设置错误状态', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(100)

    // 触发 error 事件
    mockRecorder.dispatchError('录音设备异常')

    await nextTick()

    expect(api.voiceButtonText.value).toContain('录音设备异常')
  })

  // ── 错误状态自动清除 ─────────────────────────────────────────────

  it('错误状态在 4 秒后自动清除回到 idle', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {},
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    // 触发一个错误
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')

    // 推进 4 秒
    vi.advanceTimersByTime(4000)
    await nextTick()

    expect(api.voiceButtonIcon.value).toBe('fa-microphone')
    expect(api.voiceButtonText.value).toBe('按住说话')
  })

  // ── stopVoiceRecording 在非录音状态下无操作 ──────────────────────

  it('stopVoiceRecording 在 idle 状态下不抛异常', () => {
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    expect(() => api.stopVoiceRecording(false)).not.toThrow()
    expect(() => api.stopVoiceRecording(true)).not.toThrow()
  })

  // ── cleanupVoiceInput ────────────────────────────────────────────

  it('cleanupVoiceInput 在 idle 状态下不抛异常', () => {
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    expect(() => api.cleanupVoiceInput()).not.toThrow()
  })

  it('cleanupVoiceInput 在录音中调用时停止录音并释放流', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')

    api.cleanupVoiceInput()
    expect(stream._stopFn).toHaveBeenCalled()
  })

  // ── pickSupportedMimeType ────────────────────────────────────────

  it('MediaRecorder.isTypeSupported 支持 webm 时返回对应 MIME', async () => {
    const stream = makeMockStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass({
        isTypeSupported: (mime: string) => mime === 'audio/webm;codecs=opus',
      }),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    // 录音启动成功说明 MIME 选择正确
    expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')
  })

  it('MediaRecorder.isTypeSupported 不支持任何 MIME 时仍可录音', async () => {
    const stream = makeMockStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass({ isTypeSupported: () => false }),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')
  })

  // ── 最大录音时长自动停止 ─────────────────────────────────────────

  it('录音超过 60 秒自动停止', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true, data: { text: '超时录音' } }),
    } as unknown as Response)

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    // 推进 61 秒（触发 maxTimer → stopVoiceRecording(false) → stop 事件）
    // 先填充 voiceChunks，再推进时间触发自动停止
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    vi.advanceTimersByTime(61_000)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(mockRecorder.stop).toHaveBeenCalled()
  })

  // ── 录音计时器 tick ─────────────────────────────────────────────

  it('录音中 elapsed 时间随 tick 更新', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    // 推进 200ms（触发 2 次 tick）
    vi.advanceTimersByTime(200)
    await nextTick()

    expect(api.voiceButtonText.value).toContain('松开发送')
    expect(api.voiceButtonText.value).toContain('s')
  })

  // ── 错误消息截断 ────────────────────────────────────────────────

  it('超长错误消息截断到 48 字符', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const longMsg = 'A'.repeat(100)
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error(longMsg))

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    // 错误消息应被截断
    const text = api.voiceButtonText.value
    expect(text.length).toBeLessThan(longMsg.length)
    expect(text).toContain('...')
  })

  // ── 非 Error 类型的异常 ─────────────────────────────────────────

  it('fetch reject 非 Error 类型时使用默认错误消息', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockRejectedValue('string error')

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await flushVoiceAsyncWork()

    expect(api.voiceButtonText.value).toContain('语音识别失败')
  })

  // ── 转录成功后聚焦输入框 ─────────────────────────────────────────

  it('转录成功后尝试聚焦 messageInput 元素', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true, data: { text: '测试' } }),
    } as unknown as Response)

    // 创建一个 mock DOM 元素
    const mockInput = {
      focus: vi.fn(),
      value: '',
      setSelectionRange: vi.fn(),
    }
    const getElementSpy = vi.spyOn(document, 'getElementById').mockReturnValue(mockInput as unknown as HTMLTextAreaElement)

    const messageInput = ref('')
    const api = useChatVoiceInput({ messageInput, isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    await vi.advanceTimersByTimeAsync(10)
    await nextTick()

    expect(getElementSpy).toHaveBeenCalledWith('messageInput')
    expect(mockInput.focus).toHaveBeenCalled()
    expect(mockInput.setSelectionRange).toHaveBeenCalled()

    getElementSpy.mockRestore()
  })

  // ── getUserMedia 无 name 属性的错误 ──────────────────────────────

  it('getUserMedia reject 无 name 属性时使用 message', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue({ message: '设备忙' }),
      },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass(),
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    expect(api.voiceButtonText.value).toContain('设备忙')
  })

  // ── isTypeSupported 抛异常（旧浏览器） ──────────────────────────

  it('isTypeSupported 抛异常时回退到无 MIME 模式', async () => {
    const stream = makeMockStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeSimpleMediaRecorderClass({
        isTypeSupported: () => { throw new Error('not supported') },
      }),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()
    // 应该仍然能启动录音（无 MIME 参数）
    expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')
  })

  // ── 录音中再次 startVoiceRecording 应被忽略 ──────────────────────

  it('录音中再次调用 startVoiceRecording 被忽略', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    expect(mockRecorder.start).toHaveBeenCalledTimes(1)

    // 再次调用
    await api.startVoiceRecording()
    // start 不应再次被调用
    expect(mockRecorder.start).toHaveBeenCalledTimes(1)
  })

  // ── voiceButtonDisabled 在 transcribing 状态下为 true ────────────

  it('transcribing 状态下按钮禁用', async () => {
    const stream = makeMockStream()
    const mockRecorder = createMockMediaRecorder(stream)

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: makeMediaRecorderClass(mockRecorder),
    })

    // fetch 永不 resolve，保持 transcribing 状态
    vi.spyOn(globalThis, 'fetch').mockReturnValue(new Promise(() => {}))

    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })

    await api.startVoiceRecording()
    vi.advanceTimersByTime(500)
    mockRecorder.dispatchDataAvailable(new Blob(['audio'], { type: 'audio/webm' }))
    api.stopVoiceRecording(false)

    await nextTick()
    // 不推进定时器太多，保持 transcribing 状态（fetch 未 resolve）
    await nextTick()

    // 此时应该处于 transcribing 状态
    expect(api.voiceButtonDisabled.value).toBe(true)
    expect(api.voiceButtonIcon.value).toBe('fa-spinner fa-pulse')
    expect(api.voiceButtonText.value).toBe('识别中...')
    expect(api.voiceButtonTitle.value).toContain('正在把语音转成文字')
  })

  // ── error 状态下 computed 属性 ───────────────────────────────────

  it('error 状态下 computed 返回正确的类名和图标', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {},
    })
    const api = useChatVoiceInput({ messageInput: ref(''), isLoading: ref(false) })
    await api.startVoiceRecording()

    expect(api.voiceButtonClass.value['voice-input-btn-error']).toBe(true)
    expect(api.voiceButtonIcon.value).toBe('fa-exclamation-circle')
    expect(api.voiceButtonTitle.value).toContain('不支持麦克风采集')
  })
})
