import { req, authHeaders } from './shared'
import type { WorkflowSandboxRequest, WorkflowSandboxResponse } from '../types/api'

export const scriptWorkflows = {
  listScriptWorkflows: (status: string = '') =>
    req(`/api/script-workflows${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  getScriptWorkflow: (id: number | string) => req(`/api/script-workflows/${id}`),
  updateScriptWorkflow: (id: number | string, body: Record<string, unknown>) =>
    req(`/api/script-workflows/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteScriptWorkflow: (id: number | string) => req(`/api/script-workflows/${id}`, { method: 'DELETE' }),
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
  activateScriptWorkflow: (id: number | string) => req(`/api/script-workflows/${id}/activate`, { method: 'POST' }),
  deactivateScriptWorkflow: (id: number | string) => req(`/api/script-workflows/${id}/deactivate`, { method: 'POST' }),
  listScriptWorkflowRuns: (id: number | string, mode: string = '') =>
    req(`/api/script-workflows/${id}/runs${mode ? `?mode=${encodeURIComponent(mode)}` : ''}`),
  downloadScriptWorkflowRunFile: async (id: number | string, runId: number | string, filename: string) => {
    const res = await fetch(
      `/api/script-workflows/${encodeURIComponent(String(id))}/runs/${encodeURIComponent(String(runId))}/files/${encodeURIComponent(filename)}`,
      { headers: authHeaders() },
    )
    if (!res.ok) throw new Error(res.statusText || '下载失败')
    return res.blob()
  },
  listScriptWorkflowVersions: (id: number | string) => req(`/api/script-workflows/${id}/versions`),
  commitScriptWorkflowSession: (sid: string, body: { name: string; schema_in?: Record<string, unknown> }) =>
    req(`/api/script-workflows/sessions/${encodeURIComponent(sid)}/commit`, { method: 'POST', body: JSON.stringify(body) }),
  getScriptWorkflowSession: (sid: string) => req(`/api/script-workflows/sessions/${encodeURIComponent(sid)}`),
}

export const workflow = {
  listWorkflows: () => req('/api/workflow/'),
  listESkills: () => req('/api/eskills'),
  createESkill: (body: unknown) => req('/api/eskills', { method: 'POST', body: JSON.stringify(body || {}) }),
  runESkill: (id: string | number, body: unknown) => req(`/api/eskills/${id}/run`, { method: 'POST', body: JSON.stringify(body || {}) }),
  listEmployeeEligibleWorkflows: () => req('/api/workflow/employee-eligible'),
  listWorkflowsByEmployee: (employeeId: string) => req(`/api/workflow/by-employee?employee_id=${encodeURIComponent(employeeId)}`),
  getWorkflow: (id: string | number) => req(`/api/workflow/${id}`),
  createWorkflow: (name: string, description: string) => req('/api/workflow/', { method: 'POST', body: JSON.stringify({ name, description }) }),
  updateWorkflow: (id: string | number, name: string | null, description: string | null, isActive: boolean) => req(`/api/workflow/${id}`, { method: 'PUT', body: JSON.stringify({ name, description, is_active: isActive }) }),
  deleteWorkflow: (id: string | number) => req(`/api/workflow/${id}`, { method: 'DELETE' }),
  addWorkflowNode: (workflowId: string | number, nodeType: string, name: string, config: unknown, positionX: number, positionY: number) =>
    req(`/api/workflow/${workflowId}/nodes`, { method: 'POST', body: JSON.stringify({ node_type: nodeType, name, config, position_x: positionX, position_y: positionY }) }),
  updateWorkflowNode: (nodeId: string | number, name: string, config: unknown, positionX: number, positionY: number) =>
    req(`/api/workflow/nodes/${nodeId}`, { method: 'PUT', body: JSON.stringify({ name, config, position_x: positionX, position_y: positionY }) }),
  deleteWorkflowNode: (nodeId: string | number) => req(`/api/workflow/nodes/${nodeId}`, { method: 'DELETE' }),
  addWorkflowEdge: (workflowId: string | number, sourceNodeId: unknown, targetNodeId: unknown, condition = '') =>
    req(`/api/workflow/${workflowId}/edges`, { method: 'POST', body: JSON.stringify({ source_node_id: sourceNodeId, target_node_id: targetNodeId, condition }) }),
  deleteWorkflowEdge: (edgeId: string | number) => req(`/api/workflow/edges/${edgeId}`, { method: 'DELETE' }),
  executeWorkflow: (workflowId: string | number, inputData = {}) => req(`/api/workflow/${workflowId}/execute`, { method: 'POST', body: JSON.stringify({ input_data: inputData }) }),
  workflowValidate: (workflowId: string | number) => req(`/api/workflow/${workflowId}/validate`),
  workflowSandboxRun: (workflowId: string | number, payload: WorkflowSandboxRequest): Promise<WorkflowSandboxResponse> => req(`/api/workflow/${workflowId}/sandbox-run`, { method: 'POST', body: JSON.stringify(payload || {}) }),
  listWorkflowExecutions: (workflowId: string | number, limit = 50, offset = 0) => req(`/api/workflow/${workflowId}/executions?limit=${limit}&offset=${offset}`),
  listWorkflowTriggers: (workflowId: string | number) => req(`/api/workflow/${workflowId}/triggers`),
  createWorkflowTrigger: (workflowId: string | number, payload: unknown) => req(`/api/workflow/${workflowId}/triggers`, { method: 'POST', body: JSON.stringify(payload || {}) }),
  deleteWorkflowTrigger: (workflowId: string | number, triggerId: string | number) => req(`/api/workflow/${workflowId}/triggers/${triggerId}`, { method: 'DELETE' }),
  workflowWebhookRun: (workflowId: string | number, payload = {}) => req(`/api/workflow/${workflowId}/webhook-run`, { method: 'POST', body: JSON.stringify(payload) }),
  publishWorkflowVersion: (workflowId: string | number, note = '') =>
    req(`/api/workflow/${workflowId}/versions/publish`, { method: 'POST', body: JSON.stringify({ note }) }),
  listWorkflowVersions: (workflowId: string | number, limit = 50, offset = 0) =>
    req(`/api/workflow/${workflowId}/versions?limit=${limit}&offset=${offset}`),
  getWorkflowVersion: (workflowId: string | number, versionId: string | number) =>
    req(`/api/workflow/${workflowId}/versions/${versionId}`),
  rollbackWorkflowVersion: (workflowId: string | number, versionId: string | number) =>
    req(`/api/workflow/${workflowId}/versions/${versionId}/rollback`, { method: 'POST' }),
  getExecution: (executionId: string | number) => req(`/api/workflow/executions/${executionId}`),
}
