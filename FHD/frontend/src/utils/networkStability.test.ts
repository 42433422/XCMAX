import { describe, expect, it, vi } from 'vitest'
import {
  OPERATION_TIMEOUT_MS,
  RefreshSingleFlight,
  SideEffectGate,
  SseConnectionRegistry,
  classifyRawError,
  classifyTransportFailure,
  isDuplicateUnsafeSubmit,
  resetUnsafeSubmitGuard,
} from './networkStability'

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

  it('keeps the desktop relay wording for connect timeouts', () => {
    expect(classifyRawError('connect ETIMEDOUT')).toBeNull()
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
