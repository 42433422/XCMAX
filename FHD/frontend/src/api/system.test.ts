import { describe, it, expect, vi, beforeEach } from 'vitest'
import { systemApi } from './system'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, data: {} }),
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

describe('systemApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getIndustries calls GET /api/system/industries', async () => {
    await systemApi.getIndustries()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/industries')
  })

  it('getCurrentIndustry calls GET /api/system/industry', async () => {
    await systemApi.getCurrentIndustry()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/industry')
  })

  it('setIndustry calls POST /api/system/industry', async () => {
    await systemApi.setIndustry(5)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/system/industry', { industry_id: 5 })
  })

  it('getIndustryDetail calls GET /api/system/industry/:id', async () => {
    await systemApi.getIndustryDetail(5)
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/industry/5')
  })

  it('getSystemConfig calls GET /api/system/config', async () => {
    await systemApi.getSystemConfig()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/config')
  })

  it('getHostProfile calls GET /api/system/host-profile', async () => {
    await systemApi.getHostProfile()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/host-profile')
  })

  it('getIndustryPresets calls GET /api/system/industry-presets', async () => {
    await systemApi.getIndustryPresets()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/industry-presets')
  })

  it('getWorkflowEmployeeCatalog calls GET /api/system/workflow-employee-catalog', async () => {
    await systemApi.getWorkflowEmployeeCatalog()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/workflow-employee-catalog')
  })

  it('getEmployeeRegistryRules calls GET /api/system/employee-registry-rules', async () => {
    await systemApi.getEmployeeRegistryRules()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/system/employee-registry-rules')
  })
})
