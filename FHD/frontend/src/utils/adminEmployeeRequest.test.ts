import { webcrypto } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { adminEmployeeState, executeAdminEmployee, readPendingAdminEmployeeReceipts } from './adminEmployeeRequest'
import { setRuntimeTenantStorageScopeInput } from './tenantStorageScopeRuntime'
import { productReadAccountEpoch } from './productReadAccountScope'

const config = vi.hoisted(() => ({ base: 'http://original.test' }))
vi.mock('@/utils/apiBase', () => ({ getApiBase: () => config.base }))
const body = { task: 'write once', input_data: { value: 1 } }
const completed = (key: string) => ({ success: true, execution_state: 'completed', idempotency_key: key, run_id: 'original-run', data: { summary: 'confirmed' } })
// Recorded key from the pre-v2 canonical identity for this owner, employee and body.
const legacyStorageKey = 'xcagi_admin_employee_request:f4c3cdf89e6f0480328d0ccff8901ab894b9faf835ff2990d82744247f7a7401'
const legacyRequest = { key: 'original-request', server: 'http://original.test',
  ownerScope: '{"localUserId":17,"tenantId":7}', employeeId: 'clerk', runId: 'original-run' }
const v2Request = { version: 2, key: legacyRequest.key, runId: legacyRequest.runId,
  ownerDigest: 'e08a1c7970bd0d18e7441f91304825a59c80f99c2499629f134a3db29b7c1dc1',
  employeeDigest: 'c40dc72b0228e5850d8b173ff861a48acfb4a15b37b2849cbb6584bbadbc7907',
  serverDigest: 'bcb2f1cd035e68bf02169b5794f2a144ebf1c2f22551bc091f053573adaadb24' }

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

  it('persists only a joint binding and request identity, and refuses rerouting after a server change', async () => {
    const post = vi.fn().mockRejectedValue(new Error('lost'))
    const get = vi.fn().mockRejectedValue(new Error('offline'))
    const first = await executeAdminEmployee('clerk', body, { post, get })
    const persisted = JSON.stringify(localStorage)
    for (const plain of ['write once', 'clerk', 'localUserId', 'tenantId', 'http://original.test']) expect(persisted).not.toContain(plain)
    expect(JSON.parse(localStorage.getItem(localStorage.key(0)!)!)).toEqual({ version: 3,
      key: first.idempotency_key, bindingDigest: expect.stringMatching(/^[a-f0-9]{64}$/) })
    for (const digest of [v2Request.ownerDigest, v2Request.employeeDigest, v2Request.serverDigest]) expect(persisted).not.toContain(digest)
    config.base = 'http://new.test'
    const result = await executeAdminEmployee('clerk', body, { post, get })
    expect(result.idempotency_key).toBe(first.idempotency_key)
    expect(result.execution_state).toBe('unknown')
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('binds the same employee independently to each account and normalized server', async () => {
    const post = vi.fn().mockRejectedValue(new Error('lost')), get = vi.fn().mockRejectedValue(new Error('offline'))
    const capture = async () => {
      localStorage.clear()
      await executeAdminEmployee('clerk', body, { post, get })
      return JSON.parse(localStorage.getItem(localStorage.key(0)!)!).bindingDigest
    }
    const original = await capture()
    config.base = 'http://ORIGINAL.test:80/'
    expect(await capture()).toBe(original)
    config.base = 'http://other.test'
    const otherServer = await capture()
    config.base = legacyRequest.server
    setRuntimeTenantStorageScopeInput({ tenantId: 7, localUserId: 18 })
    const otherOwner = await capture()
    setRuntimeTenantStorageScopeInput({ tenantId: 8, localUserId: 17 })
    const otherTenant = await capture()
    expect(new Set([original, otherServer, otherOwner, otherTenant]).size).toBe(4)
  })

  it('never accepts a different run or missing status for an acknowledged original request', async () => {
    const post = vi.fn(async (_path, payload) => ({ ...completed(payload.idempotency_key), success: false, execution_state: 'queued' }))
    const get = vi.fn()
    const original = await executeAdminEmployee('clerk', body, { post, get })
    get.mockResolvedValue({ ...completed(String(original.idempotency_key)), run_id: 'unrelated-run' })
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    get.mockResolvedValue({ ...completed(String(original.idempotency_key)), execution_state: '' })
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    get.mockResolvedValue(completed(String(original.idempotency_key)))
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('completed')
    expect(localStorage.length).toBe(0)
    expect(post).toHaveBeenCalledTimes(1)
  })

  it.each([
    { format: 'plaintext', record: legacyRequest, mode: 'invoke' }, { format: 'plaintext', record: legacyRequest, mode: 'reload' },
    { format: 'v2', record: v2Request, mode: 'invoke' }, { format: 'v2', record: v2Request, mode: 'reload' },
  ])('migrates the original $format record on $mode without another POST', async ({ record, mode }) => {
    localStorage.setItem(legacyStorageKey, JSON.stringify(record))
    const post = vi.fn(), get = vi.fn().mockResolvedValue({ ...completed(legacyRequest.key), execution_state: 'queued' })
    const result = mode === 'invoke'
      ? await executeAdminEmployee('clerk', body, { post, get })
      : (await readPendingAdminEmployeeReceipts('clerk', { post, get }))[0]
    expect(result).toMatchObject({ execution_state: 'queued', idempotency_key: legacyRequest.key, run_id: legacyRequest.runId })
    const migrated = localStorage.getItem(legacyStorageKey)!
    expect(JSON.parse(migrated)).toEqual({ version: 3, key: legacyRequest.key, runId: legacyRequest.runId,
      bindingDigest: expect.stringMatching(/^[a-f0-9]{64}$/) })
    for (const digest of [v2Request.ownerDigest, v2Request.employeeDigest, v2Request.serverDigest]) expect(migrated).not.toContain(digest)
    expect(migrated).not.toContain('clerk'); expect(migrated).not.toContain('localUserId')
    expect(migrated).not.toContain('http://original.test')
    expect(get).toHaveBeenCalledWith('/api/xcmax/local/employees/clerk/runs?idempotency_key=original-request')
    expect(await readPendingAdminEmployeeReceipts('another-employee', { post, get })).toEqual([])
    get.mockResolvedValue(completed(legacyRequest.key))
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('completed')
    expect(post).not.toHaveBeenCalled()
    expect(localStorage.getItem(legacyStorageKey)).toBeNull()
  })

  it.each([legacyRequest, v2Request])('preserves an existing conflict without dispatching or reading a different request: %j', async record => {
    localStorage.setItem(legacyStorageKey, JSON.stringify({ ...record, conflicted: true }))
    const post = vi.fn(), get = vi.fn()
    await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toMatchObject({ status: 409 })
    expect(JSON.parse(localStorage.getItem(legacyStorageKey)!)).toMatchObject({ version: 3, conflicted: true })
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
    expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
  })

  it.each([legacyRequest, v2Request])('migrates only on the original server and never reroutes an old request: %j', async record => {
    const encoded = JSON.stringify(record)
    localStorage.setItem(legacyStorageKey, encoded)
    config.base = 'http://other.test'
    const post = vi.fn(), get = vi.fn().mockResolvedValue(completed(legacyRequest.key))
    expect((await executeAdminEmployee('clerk', body, { post, get })).execution_state).toBe('unknown')
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
    expect(localStorage.getItem(legacyStorageKey)).toBe(encoded)
    expect(get).not.toHaveBeenCalled(); expect(post).not.toHaveBeenCalled()
    config.base = legacyRequest.server
    expect((await readPendingAdminEmployeeReceipts('clerk', { post, get }))[0].execution_state).toBe('completed')
    expect(post).not.toHaveBeenCalled()
  })

  it.each([
    { ownerDigest: undefined }, { ownerDigest: '0'.repeat(64) }, { employeeDigest: undefined },
    { employeeDigest: '0'.repeat(64) }, { serverDigest: undefined }, { serverDigest: 'invalid' },
  ])('retains unbound v2 records and refuses migration or replay: %j', async changed => {
    const original = JSON.stringify({ ...v2Request, ...changed })
    localStorage.setItem(legacyStorageKey, original)
    const post = vi.fn(), get = vi.fn()
    await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toThrow('原员工请求身份缺失')
    expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
    expect(localStorage.getItem(legacyStorageKey)).toBe(original)
    expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
  })

  it.each([{ ownerScope: '' }, { ownerScope: '{"localUserId":18,"tenantId":7}' },
    { employeeId: 'different-employee' }, { server: '' }, { key: '' }, { runId: {} }, { version: 3 }])(
    'retains malformed or foreign legacy identity and refuses replay: %j', async changed => {
      const original = JSON.stringify({ ...legacyRequest, ...changed })
      localStorage.setItem(legacyStorageKey, original)
      const post = vi.fn(), get = vi.fn()
      await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toThrow('原员工请求身份缺失')
      expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
      expect(localStorage.getItem(legacyStorageKey)).toBe(original)
      expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
    },
  )

  it.each([legacyRequest, v2Request])('retains the old request if durable migration fails and never reposts it: %j', async record => {
    const original = JSON.stringify(record)
    localStorage.setItem(legacyStorageKey, original)
    const post = vi.fn(), get = vi.fn()
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') })
    try {
      await expect(executeAdminEmployee('clerk', body, { post, get })).rejects.toThrow('storage denied')
      expect(await readPendingAdminEmployeeReceipts('clerk', { post, get })).toEqual([])
      expect(localStorage.getItem(legacyStorageKey)).toBe(original)
      expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
    } finally { storage.mockRestore() }
  })

  it.each(['account', 'server', 'epoch', 'record'])('does not migrate or read when %s changes during v2 validation', async mode => {
    const original = JSON.stringify(v2Request)
    localStorage.setItem(legacyStorageKey, original)
    let entered!: () => void, release!: () => void
    const validating = new Promise<void>(resolve => { entered = resolve })
    const resume = new Promise<void>(resolve => { release = resolve })
    vi.stubGlobal('crypto', { randomUUID: () => webcrypto.randomUUID(), subtle: {
      digest: async (algorithm: string, data: Uint8Array<ArrayBuffer>) => {
        if (new TextDecoder().decode(data) === legacyRequest.ownerScope) { entered(); await resume }
        return webcrypto.subtle.digest(algorithm, data)
      },
    } })
    const post = vi.fn(), get = vi.fn(), pending = executeAdminEmployee('clerk', body, { post, get })
    await validating
    if (mode === 'account') setRuntimeTenantStorageScopeInput({ tenantId: 7, localUserId: 18 })
    else if (mode === 'server') config.base = 'http://other.test'
    else if (mode === 'epoch') productReadAccountEpoch.value++
    else localStorage.setItem(legacyStorageKey, JSON.stringify({ ...v2Request, conflicted: true }))
    const retained = localStorage.getItem(legacyStorageKey)
    release()
    await expect(pending).rejects.toThrow('原员工请求记录已变化')
    expect(localStorage.getItem(legacyStorageKey)).toBe(retained)
    expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled()
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
