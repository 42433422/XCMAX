import { describe, it, expect, vi } from 'vitest'

vi.mock('./core', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { xcmaxDeployApi } from './xcmaxDeploy'
import api from './core'

describe('xcmaxDeployApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('checkEnterpriseUpdates calls api.get', async () => {
    await xcmaxDeployApi.checkEnterpriseUpdates()
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/deploy/check')
  })

  it('applyEnterpriseUpdate calls api.post with default body', async () => {
    await xcmaxDeployApi.applyEnterpriseUpdate()
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/deploy/apply', {})
  })

  it('applyEnterpriseUpdate calls api.post with custom body', async () => {
    await xcmaxDeployApi.applyEnterpriseUpdate({
      include_backend: true,
      include_frontend: true,
      force: true,
    })
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/deploy/apply', {
      include_backend: true,
      include_frontend: true,
      force: true,
    })
  })

  it('getEnterpriseJob calls api.get with encoded jobId', async () => {
    await xcmaxDeployApi.getEnterpriseJob('job-123')
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/deploy/jobs/job-123')
  })

  it('getEnterpriseJob encodes special characters in jobId', async () => {
    await xcmaxDeployApi.getEnterpriseJob('job/with/slashes')
    expect(api.get).toHaveBeenCalledWith('/api/xcmax/deploy/jobs/job%2Fwith%2Fslashes')
  })
})
