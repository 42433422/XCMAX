import { afterEach, describe, expect, it, vi } from 'vitest'
import { localWorkspaceApi } from './localWorkspace'

const desktopShell = vi.hoisted(() => vi.fn(() => true))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: desktopShell }))

afterEach(() => { vi.unstubAllGlobals(); desktopShell.mockReturnValue(true) })

describe('localWorkspaceApi', () => {
  it('uses the desktop guard header on a direct same-origin path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ accepted: ['op'], conflicts: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await localWorkspaceApi.write('desk', {
      op_id: 'op', id: 'customer', kind: 'customer', data: { name: '客户' }, deleted: false, base_version: null,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/local-workspace/records', expect.objectContaining({
      method: 'POST',
      redirect: 'error',
      mode: 'same-origin',
      headers: expect.objectContaining({ 'X-XCAGI-Desktop-Local': '1' }),
    }))
  })

  it('rejects before making any request outside the desktop shell', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    desktopShell.mockReturnValue(false)
    await expect(localWorkspaceApi.status()).rejects.toThrow('本机桌面应用')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
