// 管理后台域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const adminEndpoints = {
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
  /** 管理员一键清空：原子地把 packages.json + catalog_items 中所有 employee_pack 行清掉，
   * 替代前端循环逐条删；用于解决「员工仓库老是删不完」（两边数据源 pkg_id 不重合时单条对账会遗漏）。 */
  adminPurgeAllEmployeePacks: () =>
    req('/api/admin/employee-packs/purge-all', { method: 'POST' }),
  /** 将仍为 deepseek 的员工包批量改为当前环境首个可用 LLM；dryRun 只预览 */
  adminAlignEmployeeLlmFromDeepseek: (dryRun = false) =>
    req(
      `/api/admin/employee-packs/align-llm-from-deepseek?dry_run=${dryRun ? 'true' : 'false'}`,
      { method: 'POST' },
    ),
  /** 将仍为 deepseek 的员工包改为 manifest 内 auto（跟随账户可用密钥） */
  adminAlignEmployeeLlmToAuto: (dryRun = false) =>
    req(
      `/api/admin/employee-packs/align-llm-to-auto?dry_run=${dryRun ? 'true' : 'false'}`,
      { method: 'POST' },
    ),
  /** 单个员工包的 LLM 改为 auto（不限 provider），用于「无密钥」单点修复 */
  adminAlignSingleEmployeeLlmToAuto: (pkgId: string, dryRun = false) =>
    req(
      `/api/admin/employee-packs/${encodeURIComponent(pkgId)}/align-llm-to-auto-single?dry_run=${dryRun ? 'true' : 'false'}`,
      { method: 'POST' },
    ),
  /** 列出当前账户视角下的「无密钥」员工，附带 suggested_action */
  adminListNoKeyEmployees: () => req('/api/admin/duty-graph/no-key-employees'),
  /** 校验每日摘要邮件中的 6 位身份校验码，用于解锁前端管理端 UI Tab。 */
  verifyAdminDigestCode: (code: string) =>
    req('/api/auth/verify-admin-digest-code', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  /** 运维 shell_exec / ssh_exec 审计日志（只读） */
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
  /** 管理员：某员工包的任务执行明细（employee_execution_metrics） */
  adminEmployeeExecutionMetrics: (
    employeeId: string,
    params?: { limit?: number; offset?: number; user_id?: number },
  ) => {
    const p = new URLSearchParams()
    if (params?.limit != null) p.set('limit', String(params.limit))
    if (params?.offset != null) p.set('offset', String(params.offset))
    if (params?.user_id != null) p.set('user_id', String(params.user_id))
    const q = p.toString()
    return req(
      `/api/admin/employees/${encodeURIComponent(employeeId)}/execution-metrics${q ? `?${q}` : ''}`,
    )
  },
  /** 管理员：单员工执行能力/风险摘要（handlers、LLM、高风险动作） */
  adminEmployeeExecutionCapability: (employeeId: string) =>
    req(`/api/admin/employees/${encodeURIComponent(employeeId)}/execution-capability`),
  /** 管理员：批量执行能力/风险摘要；不传 employee_ids 则返回全部 */
  adminEmployeeExecutionCapabilities: (employeeIds?: string[]) =>
    req('/api/admin/employees/execution-capabilities', {
      method: 'POST',
      body: JSON.stringify({ employee_ids: Array.isArray(employeeIds) ? employeeIds : [] }),
    }),
  /** 管理员：创建依赖图运行（按 depends_on 拓扑执行） */
  adminDutyGraphRunStart: (payload: {
    target_employee_id: string
    task: string
    input_data?: Record<string, unknown>
    include_dependencies?: boolean
    max_concurrency?: number
    allow_high_risk_real_run?: boolean
  }) =>
    req('/api/admin/duty-graph/runs', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  /** 管理员：查询依赖图运行详情 */
  adminDutyGraphRunDetail: (runId: number | string) =>
    req(`/api/admin/duty-graph/runs/${encodeURIComponent(String(runId))}`),
  /** 管理员：员工自治闭环健康看板（缺岗、调度、待审 CR、未识别事件） */
  adminDutyGraphHealth: () => req('/api/admin/duty-graph/health'),
  /** 管理员：员工自治统一看板（建议/待办/协作/进化） */
  adminEmployeeAutonomyDashboard: (limitRecent = 30) =>
    req(`/api/admin/employee-autonomy/dashboard?limit_recent=${encodeURIComponent(String(limitRecent))}`),
  /** 管理员：建议单列表 */
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
    req(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(id))}/approve`, {
      method: 'POST',
      body: JSON.stringify({ dispatch_now: dispatchNow }),
    }),
  adminEmployeeSuggestionReject: (id: number | string, reason = '') =>
    req(`/api/admin/employee-autonomy/suggestions/${encodeURIComponent(String(id))}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  adminEmployeeSuggestionBatchReview: (payload: {
    ids: Array<number | string>
    action: 'approve' | 'reject'
    reason?: string
    dispatch_now?: boolean
  }) =>
    req('/api/admin/employee-autonomy/suggestions/batch-review', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  adminEmployeeBriefTasks: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/employee-autonomy/brief-tasks${q ? `?${q}` : ''}`)
  },
  adminEmployeeDispatchBriefTasks: (limit = 20) =>
    req('/api/admin/employee-autonomy/dispatch/brief-tasks', {
      method: 'POST',
      body: JSON.stringify({ limit }),
    }),
  adminEmployeeDispatchSuggestions: (limit = 20) =>
    req('/api/admin/employee-autonomy/dispatch/suggestions', {
      method: 'POST',
      body: JSON.stringify({ limit }),
    }),
  adminEmployeeEvolutionScan: (payload?: { lookback_hours?: number; min_failures?: number; limit?: number }) =>
    req('/api/admin/employee-autonomy/evolution/scan', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  adminEmployeeCollabThreads: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/employee-autonomy/collab/threads${q ? `?${q}` : ''}`)
  },
  adminEmployeeCreateCollabThread: (payload: {
    title: string
    participants: string[]
    created_by_employee_id?: string
    context?: Record<string, unknown>
  }) =>
    req('/api/admin/employee-autonomy/collab/threads', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  adminEmployeeCollabMessages: (threadId: number | string, limit = 100) =>
    req(
      `/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(threadId))}/messages?limit=${encodeURIComponent(String(limit))}`,
    ),
  adminEmployeePostCollabMessage: (
    threadId: number | string,
    payload: {
      sender_employee_id?: string
      content: string
      mentions?: string[]
      payload?: Record<string, unknown>
    },
  ) =>
    req(`/api/admin/employee-autonomy/collab/threads/${encodeURIComponent(String(threadId))}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  /** 管理员：异步下达自然语言任务，由 task_router 拆给合适的员工 */
  opsOrchestrateAsync: (payload: {
    task_description: string
    use_task_router?: boolean
    target_employee_id?: string
    max_concurrency?: number
    allow_high_risk_real_run?: boolean
  }) =>
    req('/api/ops/orchestrate/async', {
      method: 'POST',
      body: JSON.stringify({
        use_task_router: true,
        max_concurrency: 2,
        allow_high_risk_real_run: false,
        ...payload,
      }),
    }),
  /** 管理员：查询某条编排任务状态 */
  opsOrchestrateJob: (jobId: string) =>
    req(`/api/ops/orchestrate/jobs/${encodeURIComponent(jobId)}`),
  /** 管理员：列出自己最近的编排任务 */
  opsOrchestrateJobs: (limit = 20) =>
    req(`/api/ops/orchestrate/jobs?limit=${encodeURIComponent(String(limit))}`),
  /** 员工 Agent 变更审批队列 */
  adminChangeRequestsList: (params?: { status?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (params?.status) p.set('status', params.status)
    if (params?.limit != null) p.set('limit', String(params.limit))
    const q = p.toString()
    return req(`/api/admin/change-requests${q ? `?${q}` : ''}`)
  },
  adminChangeRequestDetail: (id: number | string) =>
    req(`/api/admin/change-requests/${encodeURIComponent(String(id))}`),
  adminChangeRequestApprove: (id: number | string) =>
    req(`/api/admin/change-requests/${encodeURIComponent(String(id))}/approve`, { method: 'POST' }),
  adminChangeRequestReject: (id: number | string, body: { reason?: string }) =>
    req(`/api/admin/change-requests/${encodeURIComponent(String(id))}/reject`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  /** 管理员：yuangon employee.yaml 与商城 employee_pack 上架对齐状态 */
  // ─── AI 员工账号池（QQ / 邮箱 / 微信等外部账号 → 一等公民入站渠道） ─────
  /** 列出所有 AI 员工账号（带 channel.paths：webhook URL 候选） */
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
  /** 新建账号 + 落地密钥；secret 是平台对应的 schema（QQ：app_id/app_secret/bot_token） */
  adminCreateAiAccount: (body: {
    platform: string
    external_id: string
    employee_id: string
    display_name?: string
    sandbox?: boolean
    notes?: string
    secret: Record<string, unknown>
  }) => req('/api/admin/ai-accounts', { method: 'POST', body: JSON.stringify(body) }),
  /** 改派 employee_id / 改状态 / 改备注 / 改沙箱 */
  adminUpdateAiAccount: (
    id: number | string,
    body: { employee_id?: string; display_name?: string; status?: string; sandbox?: boolean; notes?: string },
  ) =>
    req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  /** 轮换密钥（覆盖密钥文件） */
  adminRotateAiAccountSecret: (id: number | string, secret: Record<string, unknown>) =>
    req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}/rotate`, {
      method: 'POST',
      body: JSON.stringify({ secret }),
    }),
  /** 删除账号 + 销毁密钥文件 */
  adminDeleteAiAccount: (id: number | string) =>
    req(`/api/admin/ai-accounts/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  /** 查询 QQ 桥接当前状态（凭证来源、配齐与否、一等公民员工列表） */
  butlerQqStatus: () => req('/api/agent/butler/qq/status'),

  adminYuangonOnboardStatus: () => req('/api/admin/yuangon-onboard/status'),
  /** 管理员：运行 onboard_yuangon_employees.py（dry_run / force / pkg_ids） */
  adminYuangonOnboardRun: (body: { dry_run?: boolean; force?: boolean; pkg_ids?: string }) =>
    req('/api/admin/yuangon-onboard/run', { method: 'POST', body: JSON.stringify(body || {}) }),
  /** 管理员一键清空 mod 源码库：删 library/ 下所有 mod 目录 + 截断 user_mods 关联表，
   * 作为「重置仓库」的原子操作，避免前端循环单条 DELETE 因 list 缓存/关联残留导致「删不完」。 */
  adminPurgeAllMods: () => req('/api/admin/mods/purge-all', { method: 'POST' }),
  adminListCatalogComplaints: (status = '', limit = 50, offset = 0) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) p.set('status', status)
    return req(`/api/admin/catalog/complaints?${p}`)
  },
  adminReviewCatalogComplaint: (id: string | number, action: string, adminNote = '', extra: Record<string, unknown> = {}) =>
    req(`/api/admin/catalog/complaints/${encodeURIComponent(String(id))}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, admin_note: adminNote, ...extra }),
    }),
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
