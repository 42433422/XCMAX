import { req, requestBlob } from './shared'

export const employees = {
  listEmployees: () => req('/api/employees/'),
  getEmployeeStatus: (employeeId: string) => req(`/api/employees/${encodeURIComponent(employeeId)}/status`),
  getEmployeeManifest: async (employeeId: string) => {
    try {
      return await req(`/api/employees/${encodeURIComponent(employeeId)}/manifest`)
    } catch (e: any) {
      const msg = String(e?.message || '')
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
