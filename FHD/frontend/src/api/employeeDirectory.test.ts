import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { fetchEmployeeDirectory, invalidateEmployeeDirectoryCache } from './employeeDirectory'

const request = vi.hoisted(() => ({ fetch: vi.fn(), modId: '' }))
vi.mock('@/utils/apiBase', () => ({
  apiFetch: request.fetch,
  getActiveExtensionModHeaders: () => ({ 'X-XCAGI-Active-Mod-Id': request.modId }),
  getClientModsUiOffHeader: () => ({}),
}))

function response(id: string) {
  return new Response(JSON.stringify({ success: true, data: { employees: [{ pack_id: id, label: id }] } }))
}
function account(id: string) {
  setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: id })
  productReadAccountEpoch.value++
}

describe('employee directory ownership and recovery', () => {
  beforeEach(() => {
    request.fetch.mockReset()
    request.modId = ''
    invalidateEmployeeDirectoryCache()
    account('a')
  })
  afterEach(() => setRuntimeTenantStorageScopeInput(null))

  it('retains the current account cache after a failed refresh without presenting success', async () => {
    request.fetch.mockResolvedValueOnce(response('employee-a'))
    const rows = await fetchEmployeeDirectory()
    request.fetch.mockRejectedValueOnce(new Error('offline'))
    await expect(fetchEmployeeDirectory({ force: true })).rejects.toThrow('offline')
    expect(await fetchEmployeeDirectory()).toBe(rows)
    request.fetch.mockResolvedValueOnce(new Response(JSON.stringify({ success: false })))
    await expect(fetchEmployeeDirectory({ force: true })).rejects.toThrow('响应无效')
    expect(await fetchEmployeeDirectory()).toBe(rows)
  })

  it('does not reuse a directory for a different user in the same tenant', async () => {
    request.fetch.mockResolvedValueOnce(response('employee-a'))
    await fetchEmployeeDirectory()
    account('b')
    request.fetch.mockResolvedValueOnce(response('employee-b'))
    expect((await fetchEmployeeDirectory())[0].pack_id).toBe('employee-b')
    expect(request.fetch).toHaveBeenCalledTimes(2)
  })

  it('rejects an old A response even after switching A → B → A', async () => {
    let complete!: (value: Response) => void
    request.fetch.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
    const pending = fetchEmployeeDirectory()
    account('b')
    account('a')
    request.fetch.mockResolvedValueOnce(response('fresh-a'))
    const current = await fetchEmployeeDirectory()
    complete(response('stale-a'))
    await expect(pending).rejects.toThrow('上下文已变更')
    expect(await fetchEmployeeDirectory()).toBe(current)
  })

  it('shares simultaneous reads in one scope and retires them after a mod switch', async () => {
    let complete!: (value: Response) => void
    request.fetch.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
    const first = fetchEmployeeDirectory({ force: true })
    const second = fetchEmployeeDirectory({ force: true })
    expect(request.fetch).toHaveBeenCalledTimes(1)
    request.modId = 'another-authorized-mod'
    complete(response('old-mod'))
    await expect(first).rejects.toThrow('上下文已变更')
    await expect(second).rejects.toThrow('上下文已变更')
  })
})
