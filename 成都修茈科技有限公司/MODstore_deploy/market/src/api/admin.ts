import { req } from './shared'

export const admin = {
  adminStatus: () => req('/api/admin/status'),
  adminResearchSettings: () => req('/api/admin/research-settings'),
  adminSaveResearchSettings: (data: Record<string, unknown>) =>
    req('/api/admin/research-settings', { method: 'PUT', body: JSON.stringify(data || {}) }),
  adminVectorSettings: () => req('/api/admin/vector-settings'),
  adminSaveVectorSettings: (data: Record<string, unknown>) =>
    req('/api/admin/vector-settings', { method: 'PUT', body: JSON.stringify(data || {}) }),
  adminUpload: (formData: FormData) => req('/api/admin/catalog', { method: 'POST', body: formData }),
  adminListCatalog: (limit = 200, offset = 0) => req(`/api/admin/catalog?limit=${limit}&offset=${offset}`),
  adminDeleteCatalog: (id: string | number) => req(`/api/admin/catalog/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  adminDeleteEmployeePack: (pkgId: string) =>
    req(`/api/admin/employee-packs/${encodeURIComponent(pkgId)}`, { method: 'DELETE' }),
  adminPurgeAllEmployeePacks: () =>
    req('/api/admin/employee-packs/purge-all', { method: 'POST' }),
  adminAlignEmployeeLlmFromDeepseek: (dryRun = false) =>
    req(`/api/admin/employee-packs/align-llm-from-deepseek?dry_run=${dryRun ? 'true' : 'false'}`, { method: 'POST' }),
  adminAlignEmployeeLlmToAuto: (dryRun = false) =>
    req(`/api/admin/employee-packs/align-llm-to-auto?dry_run=${dryRun ? 'true' : 'false'}`, { method: 'POST' }),
  adminAlignSingleEmployeeLlmToAuto: (pkgId: string, dryRun = false) =>
    req(`/api/admin/employee-packs/${encodeURIComponent(pkgId)}/align-llm-to-auto-single?dry_run=${dryRun ? 'true' : 'false'}`, { method: 'POST' }),
  adminListNoKeyEmployees: () => req('/api/admin/duty-graph/no-key-employees'),
  verifyAdminDigestCode: (code: string) =>
    req('/api/auth/verify-admin-digest-code', { method: 'POST', body: JSON.stringify({ code }) }),
  adminOpsSshHint: () => req('/api/admin/ops-ssh-hint'),
  adminOpsAuditLogs: (params?: { employee_id?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.employee_id) p.set('employee_id', params.employee_id)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/ops/audit${q ? `?${q}` : ''}`)
  },
  adminOpsStagedChanges: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/ops/staged-changes${q ? `?${q}` : ''}`)
  },
  adminOpsApprovalTokens: (params?: { limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/ops/approval-tokens${q ? `?${q}` : ''}`)
  },
  adminEmployeeExecutionMetrics: (employeeId: string, params?: { limit?: number; offset?: number; user_id?: number }) => {
    const p = new URLSearchParams()
    if (params?.limit != null) p.set('limit', String(params.limit))
    if (params?.offset != null) p.set('offset', String(params.offset))
    if (params?.user_id != null) p.set('user_id', String(params.user_id))
    const q = p.toString()
    return req(`/api/admin/employees/${encodeURIComponent(employeeId)}/execution-metrics${q ? `?${q}` : ''}`)
  },
  adminEmployeeExecutionCapability: (employeeId: string) =>
    req(`/api/admin/employees/${encodeURIComponent(employeeId)}/execution-capability`),
  adminEmployeeExecutionCapabilities: (employeeIds?: string[]) =>
    req('/api/admin/employees/execution-capabilities', { method: 'POST', body: JSON.stringify({ employee_ids: Array.isArray(employeeIds) ? employeeIds : [] }) }),
  adminDutyGraphRunStart: (payload: {
    target_employee_id: string; task: string; input_data?: Record<string, unknown>
    include_dependencies?: boolean; max_concurrency?: number; allow_high_risk_real_run?: boolean
  }) => req('/api/admin/duty-graph/runs', { method: 'POST', body: JSON.stringify(payload || {}) }),
  adminDutyGraphRunDetail: (runId: number | string) =>
    req(`/api/admin/duty-graph/runs/${encodeURIComponent(String(runId))}`),
  adminDutyGraphHealth: () => req('/api/admin/duty-graph/health'),
  adminEmployeeAutonomyDashboard: (limitRecent = 30) =>
    req(`/api/admin/employee-autonomy/dashboard?limit_recent=${encodeURIComponent(String(limitRecent))}`),
  adminEmployeeSuggestions: (params?: { status?: string; risk_level?: string; limit?: number; offset?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.risk_level) p.set('risk_level', params.risk_level)
    if (params?.limit != null) p.set('limit', String(params.limit))
    if (params?.offset != null) p.set('offset', String(params.offset))
    const q = p.toString()
    return req(`/api/admin/employee-autonomy/suggestions${q ? `?${q}` : ''}`)
  },
  adminEmployeeSuggestionApprove: (id: number | string, dispatchNow = true) =>
    req(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(id))}/approve`, { method: 'POST', body: JSON.stringify({ dispatch_now: dispatchNow }) }),
  adminEmployeeSuggestionReject: (id: number | string, reason = '') =>
    req(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(id))}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  adminEmployeeSuggestionBatchReview: (payload: { ids: Array<number | string>; action: 'approve' | 'reject'; reason?: string; dispatch_now?: boolean }) =>
    req('/api/admin/employee-autonomy/suggestions/batch-review', { method: 'POST', body: JSON.stringify(payload || {}) }),
  adminEmployeeBriefTasks: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/employee-autonomy/brief-tasks${q ? `?${q}` : ''}`)
  },
  adminEmployeeDispatchBriefTasks: (limit = 20) =>
    req('/api/admin/employee-autonomy/dispatch/brief-tasks', { method: 'POST', body: JSON.stringify({ limit }) }),
  adminEmployeeDispatchSuggestions: (limit = 20) =>
    req('/api/admin/employee-autonomy/dispatch/suggestions', { method: 'POST', body: JSON.stringify({ limit }) }),
  adminEmployeeEvolutionScan: (payload?: { lookback_hours?: number; min_failures?: number; limit?: number }) =>
    req('/api/admin/employee-autonomy/evolution/scan', { method: 'POST', body: JSON.stringify(payload || {}) }),
  adminEmployeeCollabThreads: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/employee-autonomy/collab/threads${q ? `?${q}` : ''}`)
  },
  adminEmployeeCreateCollabThread: (payload: { title: string; participants: string[]; created_by_employee_id?: string; context?: Record<string, unknown> }) =>
    req('/api/admin/employee-autonomy/collab/threads', { method: 'POST', body: JSON.stringify(payload || {}) }),
  adminEmployeeCollabMessages: (threadId: number | string, limit = 100) =>
    req(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(threadId))}/messages?limit=${encodeURIComponent(String(limit))}`),
  adminEmployeePostCollabMessage: (threadId: number | string, payload: { sender_employee_id?: string; content: string; mentions?: string[]; payload?: Record<string, unknown> }) =>
    req(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(threadId))}/messages`, { method: 'POST', body: JSON.stringify(payload || {}) }),
  opsOrchestrateAsync: (payload: { task_description: string; use_task_router?: boolean; target_employee_id?: string; max_concurrency?: number; allow_high_risk_real_run?: boolean }) =>
    req('/api/ops/orchestrate/async', { method: 'POST', body: JSON.stringify({ use_task_router: true, max_concurrency: 2, allow_high_risk_real_run: false, ...payload }) }),
  opsOrchestrateJob: (jobId: string) => req(`/api/ops/orchestrate/jobs/${encodeURIComponent(jobId)}`),
  opsOrchestrateJobs: (limit = 20) => req(`/api/ops/orchestrate/jobs?limit=${encodeURIComponent(String(limit))}`),
  adminChangeRequestsList: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/change-requests${q ? `?${q}` : ''}`)
  },
  adminChangeRequestDetail: (id: number | string) => req(`/api/admin/change-requests/${encodeURIComponent(String(id))}`),
  adminChangeRequestApprove: (id: number | string) => req(`/api/admin/change-requests/${encodeURIComponent(String(id))}/approve`, { method: 'POST' }),
  adminChangeRequestReject: (id: number | string, body: { reason?: string }) =>
    req(`/api/admin/change-requests/${encodeURIComponent(String(id))}/reject`, { method: 'POST', body: JSON.stringify(body || {}) }),
  adminListAiAccounts: (params: { platform?: string; employee_id?: string; status?: string; limit?: number; offset?: number } = {}) => {
    const p = new URLSearchParams()
    if (params.platform) p.set('platform', params.platform)
    if (params.employee_id) p.set('employee_id', params.employee_id)
    if (params.status) p.set('status', params.status)
    if (params.limit != null) p.set('limit', String(params.limit))
    if (params.offset != null) p.set('offset', String(params.offset))
    const qs = p.toString()
    return req(`/api/admin/ai-accounts${qs ? `?${qs}` : ''}`)
  },
  adminCreateAiAccount: (body: { platform: string; external_id: string; employee_id: string; display_name?: string; sandbox?: boolean; notes?: string; secret: Record<string, unknown> }) =>
    req('/api/admin/ai-accounts', { method: 'POST', body: JSON.stringify(body) }),
  adminUpdateAiAccount: (id: number | string, body: { employee_id?: string; display_name?: string; status?: string; sandbox?: boolean; notes?: string }) =>
    req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify(body) }),
  adminRotateAiAccountSecret: (id: number | string, secret: Record<string, unknown>) =>
    req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}/rotate`, { method: 'POST', body: JSON.stringify({ secret }) }),
  adminDeleteAiAccount: (id: number | string) => req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  butlerQqStatus: () => req('/api/agent/butler/qq/status'),
  adminYuangonOnboardStatus: () => req('/api/admin/yuangon-onboard/status'),
  adminYuangonOnboardRun: (body: { dry_run?: boolean; force?: boolean; pkg_ids?: string }) =>
    req('/api/admin/yuangon-onboard/run', { method: 'POST', body: JSON.stringify(body || {}) }),
  adminPurgeAllMods: () => req('/api/admin/mods/purge-all', { method: 'POST' }),
  adminListCatalogComplaints: (status = '', limit = 50, offset = 0) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) p.set('status', status)
    return req(`/api/admin/catalog/complaints?${p}`)
  },
  adminReviewCatalogComplaint: (id: string | number, action: string, adminNote = '', extra: Record<string, unknown> = {}) =>
    req(`/api/admin/catalog/complaints/${encodeURIComponent(String(id))}/review`, { method: 'POST', body: JSON.stringify({ action, admin_note: adminNote, ...extra }) }),
  adminListUsers: (limit = 200, offset = 0, isEnterprise?: boolean) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (isEnterprise === true) p.set('is_enterprise', 'true')
    else if (isEnterprise === false) p.set('is_enterprise', 'false')
    return req(`/api/admin/users?${p}`)
  },
  adminSetUserAdmin: (userId: string | number, isAdmin: boolean) => req(`/api/admin/users/${userId}/admin?is_admin=${isAdmin}`, { method: 'PUT' }),
  adminSetUserEnterprise: (userId: string | number, isEnterprise: boolean) =>
    req(`/api/admin/users/${userId}/enterprise?is_enterprise=${isEnterprise}`, { method: 'PUT' }),
  adminEnterpriseAssignableMods: () => req('/api/admin/enterprise/assignable-mods'),
  adminListUserMods: (userId: string | number) =>
    req(`/api/admin/users/${encodeURIComponent(String(userId))}/mods`),
  adminBindUserMod: (userId: string | number, modId: string) =>
    req(`/api/admin/users/${encodeURIComponent(String(userId))}/mods/${encodeURIComponent(modId)}`, {
      method: 'POST',
    }),
  adminUnbindUserMod: (userId: string | number, modId: string) =>
    req(`/api/admin/users/${encodeURIComponent(String(userId))}/mods/${encodeURIComponent(modId)}`, {
      method: 'DELETE',
    }),
  adminListWallets: (limit = 200, offset = 0) => req(`/api/admin/wallets?limit=${limit}&offset=${offset}`),
  adminListTransactions: (limit = 200, offset = 0) => req(`/api/admin/transactions?limit=${limit}&offset=${offset}`),
}
