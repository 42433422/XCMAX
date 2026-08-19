import { req, requestBlob } from './shared'

export interface EmployeeRow extends Record<string, unknown> {
  id?: string
  name?: string
}

export interface EmployeeManifestResponse extends Record<string, unknown> {
  pack_id: string
  name: string
  version: string
  manifest: Record<string, unknown>
}

export interface EmployeeStatusResponse extends Record<string, unknown> {
  status?: string
  execution_stats?: {
    total_executions?: number
    total_runs?: number
    success_rate?: number
  } | null
}

export const employees = {
  listEmployees: () => req<EmployeeRow[]>('/api/employees/'),
  getEmployeeStatus: (employeeId: string) =>
    req<EmployeeStatusResponse>(`/api/employees/${encodeURIComponent(employeeId)}/status`),
  getEmployeeManifest: async (employeeId: string): Promise<EmployeeManifestResponse> => {
    try {
      return await req<EmployeeManifestResponse>(`/api/employees/${encodeURIComponent(employeeId)}/manifest`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e || '')
      if (msg.includes('404') || msg.includes('不存在') || msg.includes('Not Found')) {
        return { pack_id: employeeId, name: employeeId, version: '0.0.0', manifest: {} }
      }
      throw e
    }
  },
  employeeCatalogManifestDiagnostics: (packId?: string) => {
    const q = packId ? `?pack_id=${encodeURIComponent(packId)}` : ''
    return req(`/api/employees/catalog-manifest-diagnostics${q}`)
  },
  executeEmployeeTask: (employeeId: string, task: string, inputData: unknown) =>
    req(`/api/employees/${employeeId}/execute`, { method: 'POST', body: JSON.stringify({ task, input_data: inputData }) }),
  employeeExecuteFile: (
    employeeId: string,
    file: File,
    opts?: {
      task?: string
      inputData?: Record<string, unknown>
      timeoutMs?: number
      template?: File
    },
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.template) form.append('template_file', opts.template)
    form.append('task', opts?.task ?? '')
    form.append('input_data_json', JSON.stringify(opts?.inputData ?? {}))
    return req(`/api/employees/${encodeURIComponent(employeeId)}/execute-file`, {
      method: 'POST',
      body: form,
      timeoutMs: opts?.timeoutMs,
    })
  },
  employeeOutputDownload: (jobId: string, filename: string) =>
    requestBlob(`/api/employees/downloads/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`, { method: 'GET' }),
}
