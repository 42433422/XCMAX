import { webcrypto } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { adminEmployeeState, executeAdminEmployee, readPendingAdminEmployeeReceipts } from './adminEmployeeRequest'
import { setRuntimeTenantStorageScopeInput } from './tenantStorageScopeRuntime'
import { productReadAccountEpoch } from './productReadAccountScope'

const config = vi.hoisted(() => ({ base: 'http://original.test' }))
vi.mock('@/utils/apiBase', () => ({ getApiBase: () => config.base }))
const body = { task: 'write once', input_data: { value: 1 } }
const completed = (key: string) => ({ success: true, execution_state: 'completed', idempotency_key: key, run_id: 'original-run', data: { summary: 'confirmed' } })

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('crypto', webcrypto)
  config.base = 'http://original.test'
  setRuntimeTenantStorageScopeInput({ tenantId: 7, localUserId: 17 })
  productReadAccountEpoch.value = 0
})

describe('admin employee request ownership', () => {
  it('concurrent calls share one stable POST and one original receipt', async () => {
    const post = vi.fn(async (_path, payload) => completed(payload.idempotency_key))
    const get = vi.fn()
    const results = await Promise.all([executeAdminEmployee('clerk', body, { post, get }), executeAdminEmployee('clerk', body, { post, get })])
    expect(post).toHaveBeenCalledTimes(1)
    expect(results[0]).toEqual(results[1])
    expect(post.mock.calls[0][1].turn_id).toBe(post.mock.calls[0][1].idempotency_key)
    expect(results[0].run_id).toBe('original-run')
    expect(get).not.toHaveBeenCalled()
  })

  it('lost POST response and repeated invocation only read the original key', async () => {
    const post = vi.fn().mockRejectedValue(new Error('disconnected'))
    const get = vi.fn().mockRejectedValue(new Error('not yet available'))
    const first = await executeAdminEmployee('clerk', body, { post, get })
    const key = String(first.idempotency_key)
    expect(first.execution_state).toBe('unknown')
    get.mockResolvedValue(completed(key))
    const read = await executeAdminEmployee('clerk', body, { post, get })
    expect(read.execution_state).toBe('completed')
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenLastCalledWith(`/api/xcmax/local/employees/clerk/runs?idempotency_key=${key}`)
    expect(localStorage.length).toBe(0)
  })

  it('persists only digests and identity, and refuses automatic rerouting after a server change', async () => {
    const post = vi.fn().mockRejectedValue(new Error('lost'))
    const get = vi.fn().mockRejectedValue(new Error('offline'))
    const first = await executeAdminEmployee('clerk', body, { post, get })
    expect(JSON.stringify(localStorage)).not.toContain('write once')
    config.base = 'http://new.test'
    const result = await executeAdminEmployee('clerk', body, { post, get })
    expect(result.idempotency_key).toBe(first.idempotency_key)
    expect(result.execution_state).toBe('unknown')
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('never accepts a different run or missing status for an acknowledged original request', async () => {
    const post = vi.fn(async (_path, payload) => ({ ...completed(payload.idempotency_key), success: false, execution_state: 'queued' }))
    const get = vi.fn()
    const original = await executeAdminEmployee('clerk', body, { post, get })
    get.mockResolvedValue({ ...completed(String(original.idempotency_key)), run_id: 'unrelated-run' })
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    get.mockResolvedValue({ ...completed(String(original.idempotency_key)), execution_state: '' })
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    expect(post).toHaveBeenCalledTimes(1)
  })

  it.each(['queued', 'running', 'retrying', 'waiting_approval', 'waiting_input', 'waiting_auth', 'paused', 'blocked', 'unknown'])('keeps %s pending without a second POST', async (state) => {
    const post = vi.fn(async (_path, payload) => ({ ...completed(payload.idempotency_key), success: false, execution_state: state }))
    const get = vi.fn()
    const original = await executeAdminEmployee('clerk', body, { post, get })
    expect(original.execution_state).toBe(state)
    expect(original.success).toBe(false)
    get.mockResolvedValue(original)
    await executeAdminEmployee('clerk', body, { post, get })
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('does not mask an explicit idempotency conflict by reading an unrelated old result', async () => {
    const post = vi.fn().mockRejectedValue({ status: 409 })
    const get = vi.fn()
    await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toMatchObject({ status: 409 })
    await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toMatchObject({ status: 409 })
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).not.toHaveBeenCalled()
  })

  it.each(['account', 'server', 'epoch'])('does not dispatch after %s changes while the request digest is awaiting', async mode => {
    let release!: (value: ArrayBuffer) => void
    const digest = new Promise<ArrayBuffer>(resolve => { release = resolve })
    vi.stubGlobal('crypto', { randomUUID: () => webcrypto.randomUUID(), subtle: { digest: () => digest } })
    const post = vi.fn(), get = vi.fn()
    const pending = executeAdminEmployee('clerk', body, { post, get })
    if (mode === 'account') setRuntimeTenantStorageScopeInput({ tenantId: 8, localUserId: 18 })
    else if (mode === 'server') config.base = 'http://other.test'
    else productReadAccountEpoch.value++
    release(new ArrayBuffer(32))
    await expect(pending).rejects.toThrow('账号或服务器已切换')
    expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
  })

  it.each(['account', 'server'])('does not read across a %s change after a lost POST', async mode => {
    const post = vi.fn(async () => {
      if (mode === 'account') setRuntimeTenantStorageScopeInput({ tenantId: 8, localUserId: 18 })
      else config.base = 'http://other.test'
      throw new Error('lost response')
    }), get = vi.fn()
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    expect(post).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled()
  })

  it('restores original pending keys without the original body and never reads another owner', async () => {
    const post = vi.fn(async (_path, payload) => ({ ...completed(payload.idempotency_key), success: false, execution_state: 'queued' }))
    const get = vi.fn()
    const original = await executeAdminEmployee('clerk', body, { post, get })
    setRuntimeTenantStorageScopeInput({ tenantId: 7, localUserId: 18 })
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
    expect(get).not.toHaveBeenCalled()
    setRuntimeTenantStorageScopeInput({ tenantId: 7, localUserId: 17 })
    get.mockResolvedValue(completed(String(original.idempotency_key)))
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([expect.objectContaining({ execution_state: 'completed', run_id: 'original-run' })])
    expect(post).toHaveBeenCalledTimes(1)
  })

  it.each(['account', 'server'])('checks %s again between original receipt reads', async mode => {
    const post = vi.fn(async (_path, payload) => ({ ...completed(payload.idempotency_key), success: false, execution_state: 'queued' }))
    const get = vi.fn()
    await executeAdminEmployee('clerk', body, { post, get })
    await executeAdminEmployee('clerk', { ...body, task: 'another original' }, { post, get })
    get.mockImplementation(async path => {
      if (mode === 'account') setRuntimeTenantStorageScopeInput({ tenantId: 8, localUserId: 18 })
      else config.base = 'http://other.test'
      return completed(new URL(path, 'http://original.test').searchParams.get('idempotency_key') || '')
    })
    const receipts = await readPendingAdminEmployeeReceipts('clerk', { post, get })
    expect(get).toHaveBeenCalledTimes(1)
    expect(receipts.every(receipt => receipt.execution_state === 'unknown')).toBe(true)
    expect(post).toHaveBeenCalledTimes(2)
  })

  it('does not dispatch without durable identity storage', async () => {
    const post = vi.fn(), get = vi.fn()
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') })
    await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toThrow('storage denied')
    expect(post).not.toHaveBeenCalled()
    storage.mockRestore()
  })

  it('completion remains unknown with an unresolved result signal', () => {
    expect(adminEmployeeState({ ...completed('key'), requires_reconciliation: true })).toBe('unknown')
  })
})
