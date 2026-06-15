import { describe, it, expect, vi, beforeEach } from 'vitest'
import { intentPackagesApi } from './intentPackages'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, data: [] }),
    post: vi.fn().mockResolvedValue({ success: true, data: [] }),
    put: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

describe('intentPackagesApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getPackages calls GET /api/intent-packages', async () => {
    await intentPackagesApi.getPackages()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/intent-packages')
  })

  it('updatePackages calls POST /api/intent-packages', async () => {
    const packages = [{ id: 1, name: 'test', enabled: true }]
    await intentPackagesApi.updatePackages(packages)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/intent-packages', packages)
  })

  it('updatePackage calls PUT /api/intent-packages/:id', async () => {
    await intentPackagesApi.updatePackage(5, true)
    const { api } = await import('./core')
    expect(api.put).toHaveBeenCalledWith('/api/intent-packages/5', { enabled: true })
  })

  it('updatePackage with enabled=false', async () => {
    await intentPackagesApi.updatePackage(5, false)
    const { api } = await import('./core')
    expect(api.put).toHaveBeenCalledWith('/api/intent-packages/5', { enabled: false })
  })
})
