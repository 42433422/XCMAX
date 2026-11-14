import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  OPERATION_TIMEOUT_MS,
  RefreshSingleFlight,
  SideEffectGate,
  SseConnectionRegistry,
  classifyRawError,
  classifyTransportFailure,
  createTraceId,
  isDuplicateUnsafeSubmit,
  installBackendHealthBridge,
  noteTransportFailure,
  noteTransportSuccess,
  publishStabilityNotice,
  resetUnsafeSubmitGuard,
} from './networkStability'

afterEach(() => {
  vi.restoreAllMocks(); vi.unstubAllGlobals()
  document.getElementById('stability-notice')?.remove()
})

describe('network stability notices', () => {
  it('separates offline, server, token, permission and timeout', () => {
    expect(classifyTransportFailure({ online: false, message: 'Failed to fetch' }).kind).toBe('offline')
    expect(classifyTransportFailure({ online: true, message: 'Failed to fetch' }).kind).toBe('server_down')
    expect(classifyTransportFailure({ message: 'ECONNREFUSED' }).message).toContain('服务暂时不可用')
    expect(classifyTransportFailure({ status: 401 }).action).toBe('relogin')
    expect(classifyTransportFailure({ status: 401 }).message).toContain('重新登录')
    expect(classifyTransportFailure({ status: 401 }).message).not.toContain('请检查网络')
    expect(classifyTransportFailure({ status: 403 }).action).toBe('admin')
    expect(classifyTransportFailure({ timeout: true }).success).toBe(false)
    expect(classifyTransportFailure({ timeout: true }).message).toContain('未成功')
    expect(classifyTransportFailure({ errorCode: 'insufficient_balance' }).message).toContain('余额')
    expect(classifyTransportFailure({ errorCode: 'model_provider' }).message).toContain('模型')
    expect(classifyTransportFailure({ errorCode: 'bad_tool_args' }).message).toContain('参数')
    expect(classifyTransportFailure({ errorCode: 'tool_failure' }).action).toBe('check_result')
    expect(classifyTransportFailure({ errorCode: 'db_down' }).action).toBe('admin')
    expect(classifyTransportFailure({ errorCode: 'upload_failed' }).kind).toBe('upload_failed')
    expect(classifyTransportFailure({ errorCode: 'download_failed' }).kind).toBe('download_failed')
    expect(classifyTransportFailure({ errorCode: 'backend_restart' }).message).toContain('重启')
    const kinds = ['offline', 'server_down', 'token_expired', 'permission', 'timeout', 'model_provider', 'db_down']
    const messages = new Set(kinds.map((kind) => classifyTransportFailure({ errorCode: kind, online: true, message: '' }).message))
    expect(messages.size).toBe(kinds.length)
  })

  it('maps connect timeouts away from the relay wording', () => {
    expect(classifyRawError('connect ETIMEDOUT')).toContain('请求超时')
    expect(classifyRawError('connect ETIMEDOUT')).not.toContain('中继')
    expect(classifyRawError('Failed to fetch')).toContain('网络已断开')
    expect(classifyRawError('请求超时（>30s）')).toContain('未成功')
  })

  it('publishes bounded operation timeouts', () => {
    expect(OPERATION_TIMEOUT_MS.health).toBe(3_000)
    expect(OPERATION_TIMEOUT_MS.erpRead).toBe(10_000)
    expect(OPERATION_TIMEOUT_MS.chat).toBe(30_000)
    expect(OPERATION_TIMEOUT_MS.upload).toBe(30_000)
    expect(OPERATION_TIMEOUT_MS.download).toBe(30_000)
  })

  it.each([
    ['余额不足', 'insufficient_balance'], ['模型连接失败', 'model_provider'],
    ['数据库不可用', 'db_down'], ['服务正在重启', 'backend_restart'],
  ])('retains the business failure meaning when only its message is available: %s', (message, kind) => {
    expect(classifyTransportFailure({ message }).kind).toBe(kind)
    expect(classifyTransportFailure({ message }).success).toBe(false)
  })

  it('leaves auth and relay errors to their existing handlers and sanitizes actionable failures', () => {
    for (const raw of [' ', 'HTTP 401', 'HTTP 403', 'failed to connect']) expect(classifyRawError(raw)).toBeNull()
    expect(classifyRawError('connect ECONNREFUSED')).toContain('服务正在重启')
    expect(classifyRawError('余额不足')).toContain('联系管理员')
    expect(classifyRawError('数据库不可用')).toContain('操作未成功')
  })

  it('creates distinct header-safe trace IDs when randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {})
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.125).mockReturnValueOnce(0.25)
    const first = createTraceId(), second = createTraceId()
    expect(first).toMatch(/^[a-z0-9]+$/)
    expect(second).toMatch(/^[a-z0-9]+$/)
    expect(first).not.toBe(second)
  })

  it('updates one accessible notice and does not erase it for an empty event', () => {
    publishStabilityNotice('  请核对提交结果  ')
    const alert = document.getElementById('stability-notice')
    expect(alert?.getAttribute('role')).toBe('alert')
    expect(alert?.textContent).toContain('请核对提交结果')
    expect(alert?.querySelector('button')?.textContent).toBe('重试')
    publishStabilityNotice(' ')
    expect(alert?.textContent).toContain('请核对提交结果')
    publishStabilityNotice('网络已恢复')
    expect(document.querySelectorAll('#stability-notice')).toHaveLength(1)
    expect(alert?.textContent).toContain('网络已恢复')
  })

  it('stays silent for a transient failure that recovers quickly', () => {
    vi.useFakeTimers()
    noteTransportFailure('服务暂时不可用')
    expect(document.getElementById('stability-notice')).toBeNull()
    noteTransportSuccess()
    vi.advanceTimersByTime(5_000)
    expect(document.getElementById('stability-notice')).toBeNull()
    vi.useRealTimers()
  })

  it('shows the lightweight notice when failures persist', () => {
    vi.useFakeTimers()
    noteTransportFailure('服务暂时不可用')
    vi.advanceTimersByTime(4_000)
    expect(document.getElementById('stability-notice')?.textContent).toContain('服务暂时不可用')
    noteTransportSuccess()
    expect(document.getElementById('stability-notice')).toBeNull()
    vi.useRealTimers()
  })

  it('clears the notice and broadcasts readiness when the shell reports the backend is back', () => {
    let handler: ((state: string) => void) | undefined
    vi.stubGlobal('xcagiDesktop', {
      onBackendHealth: (callback: (state: string) => void) => {
        handler = callback
        return () => undefined
      },
    })
    const ready = vi.fn()
    window.addEventListener('xcagi:backend-ready', ready)
    try {
      installBackendHealthBridge()
      noteTransportFailure('服务暂时不可用')
      noteTransportFailure('服务暂时不可用')
      expect(document.getElementById('stability-notice')).not.toBeNull()
      handler?.('restarting')
      expect(document.getElementById('stability-notice')).not.toBeNull()
      handler?.('ready')
      expect(document.getElementById('stability-notice')).toBeNull()
      expect(ready).toHaveBeenCalledOnce()
    } finally {
      window.removeEventListener('xcagi:backend-ready', ready)
    }
  })
})

describe('unsafe submit and side effects', () => {
  it('drops a double click inside the guard window', () => {
    resetUnsafeSubmitGuard()
    expect(isDuplicateUnsafeSubmit('s\nhello', 1_000)).toBe(false)
    expect(isDuplicateUnsafeSubmit('s\nhello', 1_500)).toBe(true)
    expect(isDuplicateUnsafeSubmit('s\nhello', 2_400)).toBe(false)
    expect(isDuplicateUnsafeSubmit('s\nother', 1_500)).toBe(false)
  })

  it('joins in-flight work and refuses an unknown retry until confirmed', async () => {
    const gate = new SideEffectGate()
    let calls = 0
    let release!: (value: string) => void
    const first = gate.submit('erp-1', () => new Promise<string>((resolve) => {
      calls += 1
      release = resolve
    }))
    const second = gate.submit('erp-1', () => {
      calls += 1
      return Promise.resolve('nope')
    })
    release('applied')
    await expect(first).resolves.toBe('applied')
    await expect(second).resolves.toBe('applied')
    expect(calls).toBe(1)
    await expect(gate.submit('erp-1', async () => 'again')).resolves.toBe('applied')
    expect(calls).toBe(1)

    const unknown = new SideEffectGate()
    await expect(unknown.submit('tool-1', async () => {
      throw Object.assign(new Error('请求超时'), { status: 0, data: { stability: { kind: 'timeout' } } })
    })).rejects.toThrow('请求超时')
    await expect(unknown.submit('tool-1', async () => 'retried')).rejects.toThrow('结果未知')
    await expect(unknown.submit('tool-1', async () => 'checked', true)).resolves.toBe('checked')
  })

  it('keeps recent submissions guarded after a burst of expired operations', () => {
    resetUnsafeSubmitGuard()
    for (let i = 0; i < 200; i++) expect(isDuplicateUnsafeSubmit(`expired-${i}`, 0)).toBe(false)
    expect(isDuplicateUnsafeSubmit('recent', 1000)).toBe(false)
    expect(isDuplicateUnsafeSubmit('expired-0', 1100)).toBe(false)
    expect(isDuplicateUnsafeSubmit('recent', 1100)).toBe(true)
  })

  it('permits an explicit retry after a known rejection but guards a transport result without a kind', async () => {
    const gate = new SideEffectGate()
    await expect(gate.submit('rejected', async () => { throw Object.assign(new Error('invalid input'), { status: 400 }) })).rejects.toThrow('invalid input')
    await expect(gate.submit('rejected', async () => 'corrected')).resolves.toBe('corrected')
    await expect(gate.submit('unknown', async () => { throw Object.assign(new Error('connection lost'), { status: 0 }) })).rejects.toThrow('connection lost')
    const retry = vi.fn(async () => 'must not run')
    await expect(gate.submit('unknown', retry)).rejects.toThrow('结果未知')
    expect(retry).not.toHaveBeenCalled()
  })
})

describe('session refresh and sse accounting', () => {
  it('runs one refresh for concurrent callers', async () => {
    const gate = new RefreshSingleFlight()
    let calls = 0
    let release!: (ok: boolean) => void
    gate.setRefresher(() => new Promise<boolean>((resolve) => {
      calls += 1
      release = resolve
    }))
    const pending = Promise.all([gate.run(), gate.run(), gate.run()])
    await vi.waitFor(() => expect(calls).toBe(1))
    release(true)
    await expect(pending).resolves.toEqual([true, true, true])
    gate.setRefresher(async () => false)
    await expect(gate.run()).resolves.toBe(false)
  })

  it('stays disabled without a refresher and releases a rejected refresh for the next attempt', async () => {
    const gate = new RefreshSingleFlight()
    expect(gate.enabled).toBe(false)
    await expect(gate.run()).resolves.toBe(false)
    const refresh = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(true)
    gate.setRefresher(refresh)
    await expect(Promise.all([gate.run(), gate.run()])).resolves.toEqual([false, false])
    expect(refresh).toHaveBeenCalledTimes(1)
    await expect(gate.run()).resolves.toBe(true)
    expect(refresh).toHaveBeenCalledTimes(2)
  })

  it('stops reconnecting at the cap and releases the connection', () => {
    const registry = new SseConnectionRegistry()
    registry.open('c1')
    expect(registry.live).toBe(1)
    for (let i = 0; i < registry.maxReconnects; i += 1) expect(registry.allowReconnect('c1')).toBe(true)
    expect(registry.allowReconnect('c1')).toBe(false)
    registry.noteConnected('c1')
    expect(registry.allowReconnect('c1')).toBe(true)
    registry.close('c1')
    expect(registry.live).toBe(0)
    registry.close('c1')
    expect(registry.closed).toBe(1)
  })
})
