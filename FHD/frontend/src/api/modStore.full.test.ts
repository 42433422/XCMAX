import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 30000,
}))
vi.mock('@/utils/platformShellApi', () => ({
  clearDeliverableStatusCache: vi.fn(),
}))
vi.mock('@/constants/officeEmployeePack', () => ({
  OFFICE_EMPLOYEE_PKG_IDS: ['office-1', 'office-2'],
}))

import { apiFetch } from '@/utils/apiBase'
import * as modStore from './modStore'

const mockFetch = vi.mocked(apiFetch)

function okJson(data: unknown, extra: Record<string, unknown> = {}) {
  return { ok: true, json: async () => ({ success: true, data, ...extra }) } as Response
}
function failJson(error = 'boom') {
  return { ok: true, json: async () => ({ success: false, error }) } as Response
}
function notOk(body: Record<string, unknown> = {}) {
  return { ok: false, statusText: 'Server Error', json: async () => body } as Response
}

describe('modStore api full surface', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('getModCatalog success and failure', async () => {
    mockFetch.mockResolvedValueOnce(okJson({ installed: [], available: [], indexed_count: 0 }))
    expect(await modStore.getModCatalog()).toEqual({ installed: [], available: [], indexed_count: 0 })
    mockFetch.mockResolvedValueOnce(failJson('cat fail'))
    await expect(modStore.getModCatalog()).rejects.toThrow('cat fail')
  })

  it('searchMods builds query and parses', async () => {
    mockFetch.mockResolvedValueOnce(okJson({ data: [], count: 0 }))
    await modStore.searchMods('q', 'auth', true, 20)
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('q=q')
    expect(url).toContain('author=auth')
    expect(url).toContain('installed=true')
    mockFetch.mockResolvedValueOnce(failJson())
    await expect(modStore.searchMods()).rejects.toThrow()
  })

  it('getPopularMods / getRecentMods / getModDetails', async () => {
    mockFetch.mockResolvedValueOnce(okJson([{ id: 'a' }]))
    expect(await modStore.getPopularMods(5)).toHaveLength(1)
    mockFetch.mockResolvedValueOnce(okJson([{ id: 'b' }]))
    expect(await modStore.getRecentMods()).toHaveLength(1)
    mockFetch.mockResolvedValueOnce(okJson({ id: 'm', name: 'M' }))
    expect((await modStore.getModDetails('m')).id).toBe('m')
  })

  it('uploadModPackage success and failure', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { id: 'x' } }) } as Response)
    const f = new File(['x'], 'mod.zip')
    expect((await modStore.uploadModPackage(f, true)).success).toBe(true)
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: false, detail: 'bad' }) } as Response)
    await expect(modStore.uploadModPackage(f)).rejects.toThrow('bad')
  })

  it('installMod string and object variants', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok', data: {} }) } as Response)
    await modStore.installMod('pkg.zip')
    let body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.package_file).toBe('pkg.zip')
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok', data: {} }) } as Response)
    await modStore.installMod({ id: 'i', pkg_id: 'p', version: '1', package_file: 'f' })
    body = JSON.parse((mockFetch.mock.calls[1][1] as RequestInit).body as string)
    expect(body.pkg_id).toBe('p')
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: false, error: 'fail' }) } as Response)
    await expect(modStore.installMod('z')).rejects.toThrow('fail')
  })

  it('uninstallMod / updateMod / rateMod', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok' }) } as Response)
    expect((await modStore.uninstallMod('m1')).success).toBe(true)
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok', data: {} }) } as Response)
    await modStore.updateMod('m1', 'f.zip')
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: false, detail: 'rate fail' }) } as Response)
    await expect(modStore.rateMod('m1', 5)).rejects.toThrow('rate fail')
  })

  it('validateModPackage returns raw data', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok', data: 1 }) } as Response)
    expect((await modStore.validateModPackage('f')).success).toBe(true)
  })

  it('checkUpdates / resolveDependencies success and failure', async () => {
    mockFetch.mockResolvedValueOnce(okJson({ updates_available: [], count: 0 }))
    expect((await modStore.checkUpdates()).count).toBe(0)
    mockFetch.mockResolvedValueOnce(failJson())
    await expect(modStore.checkUpdates()).rejects.toThrow()
    mockFetch.mockResolvedValueOnce(okJson({ mod_id: 'm', dependencies: [], satisfied: [], missing: [], can_install: true }))
    expect((await modStore.resolveDependencies('f')).can_install).toBe(true)
  })

  it('downloadModPackage ok and not ok', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['x']) } as unknown as Response)
    expect(await modStore.downloadModPackage('f')).toBeInstanceOf(Blob)
    mockFetch.mockResolvedValueOnce({ ok: false } as Response)
    await expect(modStore.downloadModPackage('f')).rejects.toThrow('下载失败')
  })

  it('deleteModPackage / rebuildIndex', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok' }) } as Response)
    expect((await modStore.deleteModPackage('f')).success).toBe(true)
    mockFetch.mockResolvedValueOnce(okJson({ indexed: 1, failed: 0 }, { message: 'ok' }))
    expect((await modStore.rebuildIndex()).success).toBe(true)
  })

  it('syncModstoreLibraryFromRemote ok and not ok', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { installed: [], errors: [] } }) } as Response)
    expect((await modStore.syncModstoreLibraryFromRemote({ token: 't' })).success).toBe(true)
    mockFetch.mockResolvedValueOnce(notOk({ detail: 'remote bad' }))
    await expect(modStore.syncModstoreLibraryFromRemote({ token: 't' })).rejects.toThrow('remote bad')
  })

  it('installHostFoundation ok, not-ok, non-json', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'done' }) } as Response)
    expect((await modStore.installHostFoundation('full')).success).toBe(true)
    mockFetch.mockResolvedValueOnce(notOk({ message: 'hf bad' }))
    await expect(modStore.installHostFoundation()).rejects.toThrow('hf bad')
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => { throw new Error('not json') } } as unknown as Response)
    expect((await modStore.installHostFoundation()).message).toBe('安装完成')
  })

  it('installIndustrySeed ok and not ok', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { x: 1 } }) } as Response)
    expect((await modStore.installIndustrySeed('ind')).success).toBe(true)
    mockFetch.mockResolvedValueOnce(notOk({ error: 'seed bad' }))
    await expect(modStore.installIndustrySeed('ind')).rejects.toThrow('seed bad')
  })

  it('bootstrapEditionPack / reloadEmployeePacks', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) } as Response)
    expect((await modStore.bootstrapEditionPack('minimal')).success).toBe(true)
    mockFetch.mockResolvedValueOnce(notOk({ detail: 'boot bad' }))
    await expect(modStore.bootstrapEditionPack()).rejects.toThrow('boot bad')
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'reloaded' }) } as Response)
    expect((await modStore.reloadEmployeePacks('p')).message).toBe('reloaded')
  })

  it('installOfficeEmployeePack installs available targets', async () => {
    const onProgress = vi.fn()
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: { available: [{ pkg_id: 'office-1', name: 'O1', is_installed: false }] } }),
    } as Response)
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'ok', data: {} }) } as Response)
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, message: 'reloaded' }) } as Response)
    const r = await modStore.installOfficeEmployeePack({ onProgress })
    expect(r.success).toBe(true)
    expect(onProgress).toHaveBeenCalled()
  })
})
