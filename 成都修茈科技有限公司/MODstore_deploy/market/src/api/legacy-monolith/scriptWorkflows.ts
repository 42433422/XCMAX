// 脚本工作流域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { authHeaders, req } from './shared'

export const scriptWorkflowEndpoints = {
  // ----- 脚本即工作流（替代节点图）-----
  listScriptWorkflows: (status: string = '') =>
    req(`/api/script-workflows${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  getScriptWorkflow: (id: number | string) => req(`/api/script-workflows/${id}`),
  updateScriptWorkflow: (id: number | string, body: Record<string, unknown>) =>
    req(`/api/script-workflows/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteScriptWorkflow: (id: number | string) =>
    req(`/api/script-workflows/${id}`, { method: 'DELETE' }),
  sandboxRunScriptWorkflow: (id: number | string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return req(`/api/script-workflows/${id}/sandbox-run`, { method: 'POST', body: fd })
  },
  runScriptWorkflow: (id: number | string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return req(`/api/script-workflows/${id}/run`, { method: 'POST', body: fd })
  },
  activateScriptWorkflow: (id: number | string) =>
    req(`/api/script-workflows/${id}/activate`, { method: 'POST' }),
  deactivateScriptWorkflow: (id: number | string) =>
    req(`/api/script-workflows/${id}/deactivate`, { method: 'POST' }),
  listScriptWorkflowRuns: (id: number | string, mode: string = '') =>
    req(`/api/script-workflows/${id}/runs${mode ? `?mode=${encodeURIComponent(mode)}` : ''}`),
  downloadScriptWorkflowRunFile: async (id: number | string, runId: number | string, filename: string) => {
    const res = await fetch(
      `/api/script-workflows/${encodeURIComponent(String(id))}/runs/${encodeURIComponent(String(runId))}/files/${encodeURIComponent(filename)}`,
      { headers: authHeaders() },
    )
    if (!res.ok) {
      throw new Error(res.statusText || '下载失败')
    }
    return res.blob()
  },
  listScriptWorkflowVersions: (id: number | string) =>
    req(`/api/script-workflows/${id}/versions`),
  commitScriptWorkflowSession: (sid: string, body: { name: string; schema_in?: Record<string, unknown> }) =>
    req(`/api/script-workflows/sessions/${encodeURIComponent(sid)}/commit`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getScriptWorkflowSession: (sid: string) =>
    req(`/api/script-workflows/sessions/${encodeURIComponent(sid)}`),
}
