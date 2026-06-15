import { describe, it, expect, vi, beforeEach } from 'vitest'
import { xcmaxAdminApi } from './xcmaxAdmin'

vi.mock('./core', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
    put: vi.fn().mockResolvedValue({ success: true }),
    delete: vi.fn().mockResolvedValue({ success: true }),
  },
}))

describe('xcmaxAdminApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('listUsers calls GET /api/xcmax/admin/market/users', async () => {
    await xcmaxAdminApi.listUsers()
    const api = (await import('./core')).default
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/admin/market/users')
  })

  it('listAssignableMods calls GET /api/xcmax/admin/market/assignable-mods', async () => {
    await xcmaxAdminApi.listAssignableMods()
    const api = (await import('./core')).default
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/admin/market/assignable-mods')
  })

  it('listUserMods calls GET with userId', async () => {
    await xcmaxAdminApi.listUserMods(5)
    const api = (await import('./core')).default
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/mods')
  })

  it('bindUserMod calls POST with userId and modId', async () => {
    await xcmaxAdminApi.bindUserMod(5, 'mod-1')
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/mods/mod-1', {})
  })

  it('bindUserMod encodes modId', async () => {
    await xcmaxAdminApi.bindUserMod(5, 'mod/slash')
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/mods/mod%2Fslash', {})
  })

  it('unbindUserMod calls DELETE with userId and modId', async () => {
    await xcmaxAdminApi.unbindUserMod(5, 'mod-1')
    const api = (await import('./core')).default
    expect(api.delete).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/mods/mod-1')
  })

  it('setUserAdmin calls PUT with is_admin query', async () => {
    await xcmaxAdminApi.setUserAdmin(5, true)
    const api = (await import('./core')).default
    expect(api.put).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/admin?is_admin=true')
  })

  it('setUserEnterprise calls PUT with is_enterprise query', async () => {
    await xcmaxAdminApi.setUserEnterprise(5, false)
    const api = (await import('./core')).default
    expect(api.put).toHaveBeenCalledWith('/api/xcmax/admin/market/users/5/enterprise?is_enterprise=false')
  })

  it('startImpersonate calls POST with market_user_id and username', async () => {
    await xcmaxAdminApi.startImpersonate(10, 'testuser')
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/impersonate', {
      market_user_id: 10,
      username: 'testuser',
    })
  })

  it('activateEnterpriseImpersonation calls POST with bridge_token', async () => {
    await xcmaxAdminApi.activateEnterpriseImpersonation('token-123')
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/impersonate/activate-enterprise', {
      bridge_token: 'token-123',
    })
  })

  it('endImpersonate calls POST /api/xcmax/admin/impersonate/end', async () => {
    await xcmaxAdminApi.endImpersonate()
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/impersonate/end', {})
  })

  it('checkDeployUpdates calls GET /api/xcmax/admin/deploy/check', async () => {
    await xcmaxAdminApi.checkDeployUpdates()
    const api = (await import('./core')).default
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/admin/deploy/check')
  })

  it('startDeployPush calls POST /api/xcmax/admin/deploy/push', async () => {
    const body = { include_backend: true, channel: 'stable' }
    await xcmaxAdminApi.startDeployPush(body)
    const api = (await import('./core')).default
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/deploy/push', body)
  })

  it('getDeployJob calls GET with jobId', async () => {
    await xcmaxAdminApi.getDeployJob('job-123')
    const api = (await import('./core')).default
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/admin/deploy/jobs/job-123')
  })
})
