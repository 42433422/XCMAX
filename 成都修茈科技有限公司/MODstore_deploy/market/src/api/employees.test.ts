import { describe, expect, it, vi, beforeEach } from 'vitest'
import { employees } from './employees'
import { req, requestBlob } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  requestBlob: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('employees api', () => {
  it('listEmployees calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await employees.listEmployees()
    expect(req).toHaveBeenCalledWith('/api/employees/')
  })

  it('getEmployeeStatus encodes employeeId', async () => {
    vi.mocked(req).mockResolvedValue({})
    await employees.getEmployeeStatus('emp/1')
    expect(req).toHaveBeenCalledWith('/api/employees/emp%2F1/status')
  })

  it('getEmployeeManifest returns manifest on success', async () => {
    vi.mocked(req).mockResolvedValue({ pack_id: 'emp1', name: 'emp1', version: '1.0.0', manifest: {} })
    const res = await employees.getEmployeeManifest('emp1')
    expect(res.pack_id).toBe('emp1')
  })

  it('getEmployeeManifest returns fallback on 404', async () => {
    vi.mocked(req).mockRejectedValue(new Error('404 Not Found'))
    const res = await employees.getEmployeeManifest('missing')
    expect(res.pack_id).toBe('missing')
    expect(res.version).toBe('0.0.0')
  })

  it('getEmployeeManifest returns fallback on 不存在', async () => {
    vi.mocked(req).mockRejectedValue(new Error('员工不存在'))
    const res = await employees.getEmployeeManifest('missing')
    expect(res.pack_id).toBe('missing')
  })

  it('getEmployeeManifest rethrows non-404 errors', async () => {
    vi.mocked(req).mockRejectedValue(new Error('Server Error'))
    await expect(employees.getEmployeeManifest('emp1')).rejects.toThrow('Server Error')
  })

  it('employeeCatalogManifestDiagnostics calls req without query', async () => {
    vi.mocked(req).mockResolvedValue({})
    await employees.employeeCatalogManifestDiagnostics()
    expect(req).toHaveBeenCalledWith('/api/employees/catalog-manifest-diagnostics')
  })

  it('employeeCatalogManifestDiagnostics passes pack_id query', async () => {
    vi.mocked(req).mockResolvedValue({})
    await employees.employeeCatalogManifestDiagnostics('emp1')
    expect(req).toHaveBeenCalledWith('/api/employees/catalog-manifest-diagnostics?pack_id=emp1')
  })

  it('executeEmployeeTask calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await employees.executeEmployeeTask('emp1', 'task1', { key: 'val' })
    expect(req).toHaveBeenCalledWith('/api/employees/emp1/execute', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeExecuteFile calls req with FormData', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.txt')
    await employees.employeeExecuteFile('emp1', file, { task: 'analyze', inputData: { key: 'val' } })
    expect(req).toHaveBeenCalledWith('/api/employees/emp1/execute-file', expect.objectContaining({ method: 'POST' }))
  })

  it('employeeOutputDownload calls requestBlob', async () => {
    vi.mocked(requestBlob).mockResolvedValue(new Blob())
    await employees.employeeOutputDownload('job1', 'output.csv')
    expect(requestBlob).toHaveBeenCalledWith('/api/employees/downloads/job1/output.csv', expect.objectContaining({ method: 'GET' }))
  })
})
