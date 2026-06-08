import { describe, expect, it, vi } from 'vitest'
import { workbenchEmployee } from './workbench-employee'

vi.mock('./shared', () => ({
  req: vi.fn(() => Promise.resolve({})),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
}))

import { req } from './shared'

const m = vi.mocked(req)

describe('workbenchEmployee API', () => {
  beforeEach(() => { m.mockClear() })

  it('employeeBenchTest', async () => {
    await workbenchEmployee.employeeBenchTest('emp-1')
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-bench-test', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeBenchTest with provider and model', async () => {
    await workbenchEmployee.employeeBenchTest('emp-1', 'openai', 'gpt-4')
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-bench-test', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"provider":"openai"'),
    }))
  })

  it('employeePublish', async () => {
    await workbenchEmployee.employeePublish('emp-1', { price: 99 })
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-publish', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeSaveManifest', async () => {
    await workbenchEmployee.employeeSaveManifest({ name: 'test' }, 'emp-1')
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-save', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeSaveManifest with opts', async () => {
    await workbenchEmployee.employeeSaveManifest({ name: 'test' }, 'emp-1', { provider: 'openai', model: 'gpt-4', registerSkills: false })
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-save', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"register_skills":false'),
    }))
  })

  it('employeeExportZip', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      blob: () => Promise.resolve(new Blob(['zip'])),
    })))
    const result = await workbenchEmployee.employeeExportZip({ name: 'test' }, 'emp-1')
    expect(result).toBeInstanceOf(Blob)
  })

  it('employeeExportZip throws on error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: 'fail' }),
    })))
    await expect(workbenchEmployee.employeeExportZip({ name: 'test' })).rejects.toThrow('fail')
  })

  it('employeeSyncTest', async () => {
    await workbenchEmployee.employeeSyncTest('emp-1')
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-sync-test', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeSyncTest with fhdBaseUrl', async () => {
    await workbenchEmployee.employeeSyncTest('emp-1', 'http://fhd.local', 'openai', 'gpt-4')
    expect(m).toHaveBeenCalledWith('/api/workbench/employee-sync-test', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"fhd_base_url":"http://fhd.local"'),
    }))
  })
})
