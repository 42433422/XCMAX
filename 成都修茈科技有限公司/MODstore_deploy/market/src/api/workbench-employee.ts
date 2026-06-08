import { req, authHeaders } from './shared'

export const workbenchEmployee = {
  employeeBenchTest: (employeeId: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-bench-test', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, provider: provider || null, model: model || null }),
    }),
  employeePublish: (employeeId: string, opts?: { price?: number; industry?: string; release_channel?: string }) =>
    req('/api/workbench/employee-publish', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, ...(opts || {}) }),
    }),
  employeeSaveManifest: (manifest: unknown, employeeId?: string, opts?: { provider?: string; model?: string; registerSkills?: boolean }) =>
    req('/api/workbench/employee-save', {
      method: 'POST',
      body: JSON.stringify({
        manifest,
        employee_id: employeeId || null,
        provider: opts?.provider || null,
        model: opts?.model || null,
        register_skills: opts?.registerSkills !== false,
      }),
    }),
  employeeExportZip: async (manifest: unknown, employeeId?: string, opts?: { standalone?: boolean }): Promise<Blob> => {
    const headers = authHeaders() || {}
    headers['Content-Type'] = 'application/json'
    const res = await fetch('/api/workbench/employee-export', {
      method: 'POST',
      headers,
      body: JSON.stringify({ manifest, employee_id: employeeId || null, standalone: opts?.standalone === true }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err?.detail || err?.error || `HTTP ${res.status}`))
    }
    return res.blob()
  },
  employeeSyncTest: (employeeId: string, fhdBaseUrl?: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-sync-test', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, fhd_base_url: fhdBaseUrl || null, provider: provider || null, model: model || null }),
    }),
}
