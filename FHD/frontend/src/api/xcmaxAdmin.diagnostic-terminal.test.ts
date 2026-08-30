import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockApi } = vi.hoisted(() => ({
  mockApi: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/api/core', () => ({ default: mockApi }))

import { xcmaxAdminApi } from '../../../admin-console/src/api/xcmaxAdmin'

describe('admin diagnostic terminal API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses only the authenticated read-only command contracts', async () => {
    mockApi.get.mockResolvedValue({ ok: true, read_only: true, items: [] })
    mockApi.post.mockResolvedValue({ ok: true, read_only: true, items: [] })

    await xcmaxAdminApi.listDiagnosticTerminalCommands()
    await xcmaxAdminApi.executeDiagnosticTerminalCommand('find 登录')

    expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/admin/market/diagnostic-terminal/commands')
    expect(mockApi.post).toHaveBeenCalledWith('/api/xcmax/admin/market/diagnostic-terminal/execute', { command: 'find 登录' })
  })
})
