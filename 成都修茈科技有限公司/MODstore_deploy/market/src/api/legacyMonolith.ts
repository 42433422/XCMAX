import { requestJson, fetchZipBlob, requestBlob, requestStreamBlob } from '../infrastructure/http/client'
import { clearAuthTokens, getAccessToken, setAuthTokens } from '../infrastructure/storage/tokenStore'
import type {
  PaymentCheckoutBody,
  PaymentCheckoutInput,
  PaymentCheckoutResponse,
  PaymentSignResponse,
  RefundApplyResponse,
  WorkflowSandboxRequest,
  WorkflowSandboxResponse,
} from '../types/api'

const req = requestJson

export function setTokensFromAuthResponse(res: { access_token?: string; refresh_token?: string } | null | undefined) {
  setAuthTokens(res)
}

type AuthResponse = { access_token?: string; refresh_token?: string; ok?: boolean; user?: { id: number; username?: string; email?: string } }

function catalogWriteHeaders(): Record<string, string> | undefined {
  const token = (import.meta.env?.VITE_MODSTORE_CATALOG_UPLOAD_TOKEN ?? '').toString().trim()
  return token ? { Authorization: `Bearer ${token}` } : undefined
}

function authHeaders(): Record<string, string> | undefined {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : undefined
}

async function authRequest(path: string, init: RequestInit = {}) {
  return req(path, init)
}

/** @deprecated Prefer modular exports from `./api/index`; kept for endpoints not yet migrated. */
export const legacyApi = {
  register: async (username: string, password: string, email: string, verificationCode = '') => {
    const res = await authRequest('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, email, verification_code: verificationCode }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  login: async (username: string, password: string) => {
    const res = await authRequest('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  loginWithCode: async (email: string, code: string) => {
    const res = await authRequest('/api/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  sendPhoneCode: (phone: string) => req('/api/auth/send-phone-code', { method: 'POST', body: JSON.stringify({ phone }) }),
  loginWithPhoneCode: async (phone: string, code: string) => {
    const res = await authRequest('/api/auth/login-with-phone-code', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  me: () => req('/api/auth/me'),
  accountBootstrap: () => req('/api/account/bootstrap'),
  sendVerificationCode: (email: string) => req('/api/auth/send-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendRegisterVerificationCode: (email: string) => req('/api/auth/send-register-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendResetPasswordCode: (email: string) => req('/api/auth/send-reset-password-code', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    req('/api/auth/reset-password', { method: 'POST', body: JSON.stringify({ email, code, new_password: newPassword }) }),
  /** 落地页联系表单（匿名），写入 ``landing_contact_submissions`` */
  submitLandingContact: (data: {
    name: string
    email: string
    phone?: string
    company?: string
    message?: string
    source?: string
  }) =>
    req('/api/public/contact', {
      method: 'POST',
      body: JSON.stringify({
        name: data.name,
        email: data.email,
        phone: data.phone ?? '',
        company: data.company ?? '',
        message: data.message ?? '',
        source: data.source ?? 'home',
      }),
    }),
  updateProfile: (username: string) => req('/api/auth/profile', { method: 'PUT', body: JSON.stringify({ username }) }),
  changePassword: (currentPassword: string, newPassword: string) =>
    req('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),

  balance: () => req('/api/wallet/balance'),
  walletOverview: (limit = 20, offset = 0) => req(`/api/wallet/overview?limit=${limit}&offset=${offset}`),
  /** 管理员为本人钱包加款（仅 JWT，不依赖 MODSTORE_ADMIN_RECHARGE_TOKEN） */
  walletAdminSelfCredit: (amount: number, description = '') =>
    req('/api/wallet/admin-self-credit', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  recharge: (amount: number, description = '') => req('/api/wallet/recharge', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  transactions: (limit = 50, offset = 0) => req(`/api/wallet/transactions?limit=${limit}&offset=${offset}`),

  paymentPlans: () => req('/api/payment/plans'),
  paymentMyPlan: () => req('/api/payment/my-plan'),
  /** reconcile=true 时由后端主动调支付宝「交易查询」对账，补发异步通知未达时的权益 */
  paymentQuery: (orderId: string, options?: { reconcile?: boolean }) => {
    const r = options?.reconcile ? '?reconcile=true' : ''
    return req(`/api/payment/query/${encodeURIComponent(orderId)}${r}`)
  },
  paymentOrders: (status = '', limit = 50, offset = 0) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) q.set('status', status)
    return req(`/api/payment/orders?${q}`)
  },
  /** 从订单列表中隐藏已关闭/失败/已退款等，仅保留可继续处理或已支付/退款中 */
  paymentDismissNonActiveOrders: () =>
    req('/api/payment/orders/dismiss-non-active', { method: 'POST', body: '{}' }),
  paymentCancelOrder: (orderNo: string) => req(`/api/payment/cancel/${encodeURIComponent(orderNo)}`, { method: 'POST', body: '{}' }),
  paymentDiagnostics: () => req('/api/payment/diagnostics'),
  paymentEntitlements: () => req('/api/payment/entitlements'),
  paymentCheckout: async (data: PaymentCheckoutInput): Promise<PaymentCheckoutResponse> => {
    const sign = (await req('/api/payment/sign-checkout', {
      method: 'POST',
      body: JSON.stringify({
        plan_id: data?.plan_id ?? '',
        item_id: Number(data?.item_id ?? 0) || 0,
        total_amount: Number(data?.total_amount ?? 0) || 0,
        subject: data?.subject ?? '',
        wallet_recharge: Boolean(data?.wallet_recharge),
      }),
    })) as PaymentSignResponse
    const checkoutBody: PaymentCheckoutBody = {
      plan_id: sign.plan_id ?? '',
      item_id: sign.item_id ?? 0,
      total_amount: sign.total_amount ?? 0,
      subject: sign.subject ?? '',
      wallet_recharge: Boolean(sign.wallet_recharge),
      request_id: sign.request_id,
      timestamp: sign.timestamp,
      signature: sign.signature,
    }
    if (data?.pay_channel) checkoutBody.pay_channel = data.pay_channel
    if (data?.pay_type) checkoutBody.pay_type = data.pay_type
    const checkout = (await req('/api/payment/checkout', {
      method: 'POST',
      body: JSON.stringify(checkoutBody),
    })) as PaymentCheckoutResponse
    if (checkout?.ok === false) {
      return checkout
    }
    if (checkout?.ok !== true) {
      throw new Error('支付下单返回异常：缺少成功标识')
    }
    const payType = String(checkout.type || '').trim()
    if (!payType) {
      throw new Error('支付下单返回异常：缺少支付类型')
    }
    if (payType === 'page' || payType === 'wap') {
      const u = checkout.redirect_url
      if (!u || String(u).trim() === '') {
        throw new Error('支付下单返回异常：缺少跳转地址')
      }
    }
    if (payType === 'precreate' || payType === 'wechat_native') {
      const oid = checkout.order_id
      if (!oid || String(oid).trim() === '') {
        throw new Error('支付下单返回异常：缺少订单号')
      }
    }
    return checkout
  },

  refundsApply: async (orderNo: string, reason: string): Promise<RefundApplyResponse> => {
    const res = (await req('/api/refunds/apply', { method: 'POST', body: JSON.stringify({ order_no: orderNo, reason }) })) as RefundApplyResponse
    if (res?.ok === false) throw new Error(res.message || '退款申请失败')
    return res
  },
  refundsMy: () => req('/api/refunds/my'),
  refundsAdminPending: () => req('/api/refunds/admin/pending'),
  refundsAdminReview: (refundId: number, action: string, adminNote = '') =>
    req(`/api/refunds/admin/${encodeURIComponent(String(refundId))}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, admin_note: adminNote }),
    }),

  catalog: (
    q = '',
    artifact = '',
    limit = 50,
    offset = 0,
    industry = '',
    securityLevel = '',
    materialCategory = '',
    licenseScope = '',
    cacheBust = false,
  ) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (q) p.set('q', q)
    if (artifact) p.set('artifact', artifact)
    if (industry) p.set('industry', industry)
    if (securityLevel) p.set('security_level', securityLevel)
    if (materialCategory) p.set('material_category', materialCategory)
    if (licenseScope) p.set('license_scope', licenseScope)
    if (cacheBust) p.set('_cb', String(Date.now()))
    return req(`/api/market/catalog?${p}`)
  },
  catalogFacets: () => req('/api/market/facets'),
  catalogDetail: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}`),
  catalogQuality: (id: string | number, opts: boolean | { refresh?: boolean; llm?: boolean } = false) => {
    const options = typeof opts === 'boolean' ? { refresh: opts } : opts
    const params = new URLSearchParams()
    if (options.refresh) params.set('refresh', '1')
    if (options.llm) params.set('llm', '1')
    const q = params.toString()
    return req(`/api/market/catalog/${encodeURIComponent(String(id))}/quality${q ? `?${q}` : ''}`)
  },
  catalogReviews: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/reviews`),
  catalogSubmitReview: (id: string | number, rating: number, content = '') =>
    req(`/api/market/catalog/${encodeURIComponent(String(id))}/review`, { method: 'POST', body: JSON.stringify({ rating, content }) }),
  catalogSubmitComplaint: (id: string | number, complaintType: string, reason: string, evidence: Record<string, unknown> = {}) =>
    req(`/api/market/catalog/${encodeURIComponent(String(id))}/complaints`, {
      method: 'POST',
      body: JSON.stringify({ complaint_type: complaintType, reason, evidence }),
    }),
  catalogToggleFavorite: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/favorite`, { method: 'POST', body: '{}' }),
  buyItem: (id: string | number) => req(`/api/market/catalog/${encodeURIComponent(String(id))}/buy`, { method: 'POST' }),
  downloadItem: async (id: string | number) => {
    const blob = await fetchZipBlob(`/api/market/catalog/${encodeURIComponent(String(id))}/download`, authHeaders())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mod-${id}.zip`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    // 延后释放，避免浏览器尚未读完流时立即 revoke 导致落盘 0 字节
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
  myStore: (limit = 50, offset = 0) => req(`/api/my-store?limit=${limit}&offset=${offset}`),

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
  adminOpsSshHint: () => req('/api/admin/ops-ssh-hint'),
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

  /** 传 true 时追加查询参数，避免 CDN/浏览器对 GET /api/mods 的缓存导致「删了仍显示」 */
  listMods: (cacheBust = false) => req(`/api/mods${cacheBust ? `?_=${Date.now()}` : ''}`),
  deleteMod: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}`, { method: 'DELETE' }),
  createMod: (mod_id: string, display_name: string, industry_id = '通用') =>
    req('/api/mods/create', { method: 'POST', body: JSON.stringify({ mod_id, display_name, industry_id }) }),
  importZIP: (file: File, replace = true) => {
    const fd = new FormData()
    fd.append('file', file)
    return req(`/api/mods/import?replace=${replace}`, { method: 'POST', body: fd })
  },
  modAiScaffold: (
    brief: string,
    suggestedId = '',
    replace = true,
    industryId = '通用',
    provider?: string,
    model?: string,
  ) =>
    req('/api/mods/ai-scaffold', {
      method: 'POST',
      body: JSON.stringify({
        brief,
        suggested_id: suggestedId || undefined,
        replace,
        industry_id: industryId || '通用',
        provider,
        model,
      }),
    }),
  push: (mod_ids: unknown = null) => req('/api/sync/push', { method: 'POST', body: JSON.stringify({ mod_ids }) }),
  pull: (mod_ids: unknown = null) => req('/api/sync/pull', { method: 'POST', body: JSON.stringify({ mod_ids }) }),
  /** 库路径、XCAGI 根目录、宿主后端 URL（与 modstore_server GET/PUT /api/config 对齐） */
  getRepoConfig: () => req('/api/config'),
  putRepoConfig: (body: { library_root?: string; xcagi_root?: string; xcagi_backend_url?: string }) =>
    req('/api/config', { method: 'PUT', body: JSON.stringify(body || {}) }),
  getMod: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}`),
  putModManifest: (modId: string, manifest: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/manifest`, { method: 'PUT', body: JSON.stringify({ manifest }) }),
  attachCatalogEmployeeToMod: (
    modId: string,
    body: { pkg_id: string; catalog_item_id?: number | string },
  ) =>
    req(`/api/mods/${encodeURIComponent(modId)}/attach-catalog-employee`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getModFile: (modId: string, path: string) => req(`/api/mods/${encodeURIComponent(modId)}/file?path=${encodeURIComponent(path)}`),
  putModFile: (modId: string, path: string, content: string) => req(`/api/mods/${encodeURIComponent(modId)}/file`, { method: 'PUT', body: JSON.stringify({ path, content }) }),
  regenerateModFrontend: (modId: string, brief = '') =>
    req(`/api/mods/${encodeURIComponent(modId)}/frontend/regenerate`, { method: 'POST', body: JSON.stringify({ brief }) }),
  listModSnapshots: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/snapshots`),
  captureModSnapshot: (modId: string, label = '') => req(`/api/mods/${encodeURIComponent(modId)}/snapshots`, { method: 'POST', body: JSON.stringify({ label }) }),
  restoreModSnapshot: (modId: string, snapId: string) => req(`/api/mods/${encodeURIComponent(modId)}/snapshots/${encodeURIComponent(snapId)}/restore`, { method: 'POST', body: '{}' }),
  bumpModManifestPatchVersion: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/manifest/bump-patch-version`, { method: 'POST', body: '{}' }),
  modWorkflowLink: (modId: string, body: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/workflow-link`, { method: 'POST', body: JSON.stringify(body) }),
  scaffoldWorkflowEmployee: (modId: string, body: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/workflow-employees/scaffold`, { method: 'POST', body: JSON.stringify(body) }),
  getModAuthoringSummary: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/authoring-summary`),
  /** Mod 内蓝图路由（供编辑器渲染节点列表 / 路由树） */
  getModBlueprintRoutes: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/blueprint-routes`),
  /** 当前作者可用的扩展面（components / triggers / actions），可选合并宿主提供项 */
  getAuthoringExtensionSurface: (mergeHost = false) =>
    req(`/api/authoring/extension-surface?merge_host=${mergeHost ? 'true' : 'false'}`),
  /**
   * 从 Mod 的 workflow_employees[index] 生成 employee_pack 最小 zip。
   * 兼容旧路由 /export_employee_pack（下划线版本）：若新路由 404，则回退尝试一次。
   */
  exportEmployeePackZip: async (modId: string, workflowIndex = 0): Promise<Blob> => {
    const mid = String(modId || '').trim()
    const n = Number.parseInt(String(workflowIndex ?? 0), 10)
    const idx = Number.isFinite(n) && n >= 0 ? n : 0
    const q = `workflow_index=${idx}`
    const headers = authHeaders()
    const urls = [
      `/api/mods/${encodeURIComponent(mid)}/export-employee-pack?${q}`,
      `/api/mods/${encodeURIComponent(mid)}/export_employee_pack?${q}`,
    ]
    const staleHint =
      '8765 上的 API 进程里若没有该路由，会返回 Not Found。请完全退出旧进程后重启：在 MODstore_deploy 目录执行 start-modstore.bat / restart.bat，或手动运行 python -m modstore_server。自检：打开 http://127.0.0.1:8765/docs 搜索「export-employee-pack」，搜不到即仍是旧代码。'
    const looksLikeMissingRoute = (raw: string): boolean => {
      const m = String(raw || '').trim()
      if (/mod\s*不存在|Mod 不存在/i.test(m)) return false
      if (/^not found$/i.test(m)) return true
      if (m === '{"detail":"Not Found"}') return true
      try {
        const j = JSON.parse(m)
        const d = j?.detail
        if (d === 'Not Found') return true
        if (Array.isArray(d) && d.some((x: any) => String(x?.msg || '').toLowerCase() === 'not found')) return true
      } catch {
        /* ignore */
      }
      return false
    }
    let lastErr: unknown
    for (let i = 0; i < urls.length; i++) {
      try {
        return await fetchZipBlob(urls[i], headers)
      } catch (e) {
        lastErr = e
        const msg = String((e as Error)?.message || '').trim()
        if (looksLikeMissingRoute(msg) && i === 0) continue
        break
      }
    }
    const base = String((lastErr as Error)?.message || '导出失败').trim()
    if (looksLikeMissingRoute(base)) {
      throw new Error(`${base} — ${staleHint}`)
    }
    throw lastErr instanceof Error ? lastErr : new Error(base)
  },
  exportModZip: (modId: string) => fetchZipBlob(`/api/mods/${encodeURIComponent(modId)}/export`, authHeaders()),
  /** 沙盒审核：multipart file（.zip/.xcemp），可选 metadata JSON 含 artifact */
  auditPackage: (file: File, metadata: unknown = null) => {
    const fd = new FormData()
    fd.append('file', file)
    if (metadata != null) fd.append('metadata', JSON.stringify(metadata))
    return req('/api/package-audit', { method: 'POST', body: fd })
  },

  listV1Packages: (artifact = '', q = '', limit = 50, offset = 0, cacheBust = false) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (artifact) p.set('artifact', artifact)
    if (q) p.set('q', q)
    if (cacheBust) p.set('_', String(Date.now()))
    return req(`/v1/packages?${p}`)
  },
  listCatalogPackageVersions: (pkgId: string) => req(`/v1/packages/by-id/${encodeURIComponent(pkgId)}/versions`),
  promoteCatalogPackage: (pkgId: string, fromVersion: string) =>
    req(`/v1/packages/${encodeURIComponent(pkgId)}/promote`, { method: 'POST', body: JSON.stringify({ from_version: fromVersion }), headers: catalogWriteHeaders() }),
  downloadCatalogPackageBlob: (pkgId: string, version: string) => fetchZipBlob(`/v1/packages/${encodeURIComponent(pkgId)}/${encodeURIComponent(version)}/download`),
  uploadPackage: (metadata: unknown, file: File) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(metadata))
    fd.append('file', file)
    return req('/v1/packages', { method: 'POST', body: fd, headers: catalogWriteHeaders() })
  },
  registerWorkflowEmployeeCatalog: (modId: string, workflowIndex = 0, opts: { industry?: string; price?: number; release_channel?: string } = {}) =>
    req(`/api/mods/${encodeURIComponent(modId)}/register-workflow-employee-catalog`, {
      method: 'POST',
      body: JSON.stringify({ workflow_index: workflowIndex, industry: opts.industry || '通用', price: opts.price ?? 0, release_channel: opts.release_channel || 'stable' }),
    }),
  /** 再次对齐画布 employee 节点与 manifest 推导的 pack id（可补 start/end 骨架） */
  patchModWorkflowEmployeeNodes: (modId: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/patch-workflow-employee-nodes`, { method: 'POST' }),
  runWorkflowEmployeeClosure: (
    modId: string,
    opts: { register_missing?: boolean; patch_canvas?: boolean; industry?: string } = {},
  ) =>
    req(`/api/mods/${encodeURIComponent(modId)}/workflow-employee-closure`, {
      method: 'POST',
      body: JSON.stringify({
        register_missing: opts.register_missing !== false,
        patch_canvas: opts.patch_canvas !== false,
        industry: opts.industry || '通用',
      }),
    }),

  /** 员工上架：LLM 生成 1-5 级测试任务 → 执行 → 量化打分 → 五维审核 */
  employeeBenchTest: (employeeId: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-bench-test', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, provider: provider || null, model: model || null }),
    }),

  /** 员工上架：bench 通过后写入 catalog_store + catalog_items */
  employeePublish: (employeeId: string, opts?: { price?: number; industry?: string; release_channel?: string }) =>
    req('/api/workbench/employee-publish', {
      method: 'POST',
      body: JSON.stringify({ employee_id: employeeId, ...(opts || {}) }),
    }),

  /**
   * 保存当前编辑器 manifest 到服务器库（持久化）并通过 vibe-coding 注册 ESkill。
   * 返回保存的 pack_id、已注册 eskill 数量和更新后的 manifest（含 eskill_id）。
   */
  employeeSaveManifest: (
    manifest: unknown,
    employeeId?: string,
    opts?: { provider?: string; model?: string; registerSkills?: boolean },
  ) =>
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

  /**
   * 根据当前 manifest 生成完整 .xcemp（含 blueprints.py + employee.py）并下载。
   * 不落盘，直接返回 zip 流。
   * `standalone: true` 时额外打入 zipapp（__main__.py、standalone/），可本机 `python *.xcemp validate`。
   */
  employeeExportZip: async (
    manifest: unknown,
    employeeId?: string,
    opts?: { standalone?: boolean },
  ): Promise<Blob> => {
    const headers = authHeaders() || {}
    headers['Content-Type'] = 'application/json'
    const res = await fetch('/api/workbench/employee-export', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        manifest,
        employee_id: employeeId || null,
        standalone: opts?.standalone === true,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err?.detail || err?.error || `HTTP ${res.status}`))
    }
    return res.blob()
  },

  /**
   * 员工同步测试：bench → 发布到 catalog → 推送到宿主 fhd-sandbox-runtime /api/mod-store/install
   * 成功后员工出现在宿主「一键托管」面板
   */
  employeeSyncTest: (employeeId: string, fhdBaseUrl?: string, provider?: string, model?: string) =>
    req('/api/workbench/employee-sync-test', {
      method: 'POST',
      body: JSON.stringify({
        employee_id: employeeId,
        fhd_base_url: fhdBaseUrl || null,
        provider: provider || null,
        model: model || null,
      }),
    }),

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

  // 开发者门户：Personal Access Token
  developerListTokens: () => req('/api/developer/tokens'),
  developerCreateToken: (name: string, scopes: string[] = [], expiresDays: number | null = null) =>
    req('/api/developer/tokens', {
      method: 'POST',
      body: JSON.stringify({ name, scopes, expires_days: expiresDays }),
    }),
  developerRevokeToken: (tokenId: string | number) =>
    req(`/api/developer/tokens/${tokenId}`, { method: 'DELETE' }),

  developerExportKeyBundle: (payload: {
    recipient_public_key_spki_b64: string
    current_password: string
    token_ids: number[]
    rotate_source_tokens?: boolean
  }) =>
    req('/api/developer/key-export/bundle', {
      method: 'POST',
      body: JSON.stringify({
        recipient_public_key_spki_b64: payload.recipient_public_key_spki_b64,
        current_password: payload.current_password,
        token_ids: payload.token_ids,
        rotate_source_tokens: payload.rotate_source_tokens !== false,
      }),
    }),
  developerListKeyExportAudit: (limit = 50) =>
    req(`/api/developer/key-export/audit?limit=${encodeURIComponent(String(limit))}`),

  // 开发者门户：Webhook 订阅
  developerWebhookEventCatalog: () => req('/api/developer/webhooks/event-catalog'),
  developerListWebhooks: () => req('/api/developer/webhooks'),
  developerCreateWebhook: (payload: {
    name: string
    target_url: string
    secret?: string
    enabled_events?: string[]
    description?: string
    is_active?: boolean
  }) => req('/api/developer/webhooks', { method: 'POST', body: JSON.stringify(payload) }),
  developerUpdateWebhook: (
    id: string | number,
    payload: {
      name?: string
      target_url?: string
      secret?: string
      enabled_events?: string[]
      description?: string
      is_active?: boolean
    },
  ) => req(`/api/developer/webhooks/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  developerDeleteWebhook: (id: string | number) =>
    req(`/api/developer/webhooks/${id}`, { method: 'DELETE' }),
  developerListWebhookDeliveries: (
    id: string | number,
    opts: { limit?: number; offset?: number; status?: string } = {},
  ) => {
    const p = new URLSearchParams()
    if (opts.limit) p.set('limit', String(opts.limit))
    if (opts.offset) p.set('offset', String(opts.offset))
    if (opts.status) p.set('status', opts.status)
    const qs = p.toString()
    return req(`/api/developer/webhooks/${id}/deliveries${qs ? `?${qs}` : ''}`)
  },
  developerRetryWebhookDelivery: (deliveryId: string | number) =>
    req(`/api/developer/webhooks/deliveries/${deliveryId}/retry`, { method: 'POST' }),
  developerTestWebhook: (id: string | number) =>
    req(`/api/developer/webhooks/${id}/test`, { method: 'POST' }),

  // 模板市场
  templatesList: (
    opts: { q?: string; category?: string; difficulty?: string; sort?: string; limit?: number; offset?: number } = {},
  ) => {
    const p = new URLSearchParams()
    if (opts.q) p.set('q', opts.q)
    if (opts.category) p.set('category', opts.category)
    if (opts.difficulty) p.set('difficulty', opts.difficulty)
    if (opts.sort) p.set('sort', opts.sort)
    if (opts.limit) p.set('limit', String(opts.limit))
    if (opts.offset) p.set('offset', String(opts.offset))
    return req(`/api/templates${p.toString() ? '?' + p.toString() : ''}`)
  },
  templatesCategories: () => req('/api/templates/categories'),
  templateDetail: (id: string | number) => req(`/api/templates/${encodeURIComponent(String(id))}`),
  templateInstall: (id: string | number) =>
    req(`/api/templates/${encodeURIComponent(String(id))}/install`, { method: 'POST' }),
  saveWorkflowAsTemplate: (
    workflowId: string | number,
    payload: {
      name: string
      description?: string
      template_category?: string
      template_difficulty?: string
      price?: number
      is_public?: boolean
      industry?: string
    },
  ) =>
    req(`/api/templates/from-workflow/${workflowId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  notificationsList: (unreadOnly = false, limit = 50, kind = '') => {
    const p = new URLSearchParams({ unread_only: unreadOnly ? 'true' : 'false', limit: String(limit) })
    if (kind) p.set('kind', kind)
    return req(`/api/notifications/?${p}`)
  },
  notificationMarkRead: (id: string | number) => req(`/api/notifications/${id}/read`, { method: 'POST' }),
  notificationsMarkAllRead: () => req('/api/notifications/read-all', { method: 'POST' }),
  analyticsDashboard: () => req('/api/analytics/dashboard'),

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
  /** 管理员：排查员工 manifest 404 — 目录路径、packages.json、Mod 库与可选 pack_id 探测 */
  employeeCatalogManifestDiagnostics: (packId?: string) => {
    const q = packId ? `?pack_id=${encodeURIComponent(packId)}` : ''
    return req(`/api/employees/catalog-manifest-diagnostics${q}`)
  },
  executeEmployeeTask: (employeeId: string, task: string, inputData: unknown) =>
    req(`/api/employees/${employeeId}/execute`, { method: 'POST', body: JSON.stringify({ task, input_data: inputData }) }),
  /** multipart：原始表格给员工包执行（不走知识抽取）；与 Nginx / MODSTORE_EMPLOYEE_FILE_MAX_BYTES 上限一致。 */
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
  /** 下载 execute-file 持久化后的产出（需登录，与 employeeExecuteFile 配套）。 */
  employeeOutputDownload: (jobId: string, filename: string) =>
    requestBlob(
      `/api/employees/downloads/${encodeURIComponent(jobId)}/${encodeURIComponent(filename)}`,
      { method: 'GET' },
    ),

  llmStatus: () => req('/api/llm/status'),
  llmResolveChatDefault: () => req('/api/llm/resolve-chat-default'),
  llmCatalog: (refresh = false) => req(`/api/llm/catalog?refresh=${refresh ? 1 : 0}`),
  llmSaveCredentials: (provider: string, apiKey: string, baseUrl?: string | null) => req(`/api/llm/credentials/${encodeURIComponent(provider)}`, { method: 'PUT', body: JSON.stringify({ api_key: apiKey, base_url: baseUrl ?? null }) }),
  llmDeleteCredentials: (provider: string) => req(`/api/llm/credentials/${encodeURIComponent(provider)}`, { method: 'DELETE' }),
  llmSavePreferences: (provider: string, model: string) => req('/api/llm/preferences', { method: 'PUT', body: JSON.stringify({ provider, model }) }),
  llmPricing: () => req('/api/llm/pricing'),
  llmUsage: (limit = 50, offset = 0) => req(`/api/llm/usage?limit=${limit}&offset=${offset}`),
  llmConversations: (limit = 30, offset = 0) => req(`/api/llm/conversations?limit=${limit}&offset=${offset}`),
  llmConversationDetail: (id: string | number) => req(`/api/llm/conversations/${encodeURIComponent(String(id))}`),
  llmAdminSavePrice: (data: Record<string, unknown>) => req('/api/llm/admin/pricing', { method: 'PUT', body: JSON.stringify(data || {}) }),
  llmAdminModelCapabilities: (opts?: { provider?: string; q?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (opts?.provider) p.set('provider', opts.provider)
    if (opts?.q) p.set('q', opts.q)
    if (opts?.limit != null) p.set('limit', String(opts.limit))
    const qs = p.toString()
    return req(`/api/llm/admin/model-capabilities${qs ? `?${qs}` : ''}`)
  },
  llmAdminModelCapabilityReview: (body: { provider: string; model: string; l3_status: string; notes?: string }) =>
    req('/api/llm/admin/model-capabilities/review', { method: 'PUT', body: JSON.stringify(body) }),
  llmChat: async (
    provider: string,
    model: string,
    messages: unknown[],
    maxTokens: number | null = null,
    conversationId: number | null = null,
  ) => {
    const res = (await req('/api/llm/chat', {
      method: 'POST',
      body: JSON.stringify({ provider, model, messages, max_tokens: maxTokens, conversation_id: conversationId }),
    })) as { billed?: boolean; charge_amount?: number; content?: unknown } & Record<string, unknown>
    if (res && (res.billed === true || (Number(res.charge_amount) || 0) > 0)) {
      void import('../utils/llmBillingRefresh').then((m) => m.refreshLevelAndWalletAfterLlm())
    }
    return res
  },
  llmChatStream: (provider: string, model: string, messages: unknown[], maxTokens: number | null = null, conversationId: number | null = null, signal?: AbortSignal) => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    headers.set('Accept', 'text/event-stream')
    return fetch('/api/llm/chat/stream', {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify({ provider, model, messages, max_tokens: maxTokens, conversation_id: conversationId }),
    })
  },
  llmGenerateImage: (provider: string, model: string, prompt: string, opts: { size?: string; count?: number; n?: number } = {}) =>
    req('/api/llm/image', {
      method: 'POST',
      body: JSON.stringify({
        provider,
        model,
        prompt,
        size: opts.size || '1024x1024',
        n: opts.count || opts.n || 1,
      }),
    }),
  llmGenerateVideo: (provider: string, model: string, prompt: string, opts: { size?: string; seconds?: number; durationSec?: number } = {}) =>
    req('/api/llm/video', {
      method: 'POST',
      body: JSON.stringify({
        provider,
        model,
        prompt,
        size: opts.size || '1280x720',
        seconds: opts.seconds || opts.durationSec || 5,
      }),
    }),
  llmGeneratePptxBlob: async (title: string, markdown: string, filename = 'ai-presentation.pptx') => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    const res = await fetch('/api/llm/pptx', {
      method: 'POST',
      headers,
      body: JSON.stringify({ title, markdown, filename }),
    })
    const buf = await res.arrayBuffer()
    if (!res.ok) {
      let message = res.statusText || '生成 PPT 失败'
      try {
        const text = new TextDecoder().decode(buf)
        const data = JSON.parse(text)
        message = data?.detail || data?.message || message
      } catch {
        /* ignore */
      }
      throw new Error(message)
    }
    return new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
  },
  workbenchResearchContext: (body: unknown) => req('/api/workbench/research-context', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSession: (body: unknown) => req('/api/workbench/sessions', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSessionWithFiles: (body: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(body || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/sessions', { method: 'POST', body: fd })
  },
  /**
   * 工作台三档对话中的即席文件处理（Canvas Skill 模式）。
   * 轮询方式，结果通过 workbenchGetSession 查询，不持久化到数据库。
   *
   * ⚠️ 与 /api/script-workflows/sessions（SSE）是两条独立产品线：
   *   - workbenchStartScriptSession → 即席、一次性、在工作台内完成
   *   - /api/script-workflows/sessions → ScriptWorkflowComposerView 中创建可复用的命名工作流，结果持久化到 script_workflows 表
   */
  workbenchStartScriptSession: (metadata: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(metadata || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/script-sessions', { method: 'POST', body: fd })
  },
  workbenchGetSession: (sessionId: string) => req(`/api/workbench/sessions/${encodeURIComponent(sessionId)}`),
  workbenchRetrySession: (sessionId: string) => req(`/api/workbench/sessions/${encodeURIComponent(sessionId)}/retry`, { method: 'POST' }),

  /**
   * 启动 6 阶段 AI 员工生成流水线（SSE）。
   * 推荐使用 `useAgentLoop().runEmployeeDraft()`（Bearer + Pinia 流水线快照 + EmployeeAiDraftReview）。
   * SSE `data:` 行 JSON 字段 `event` 取值包括但不限于：
   * stage_start | stage_progress | stage_done | stage_error | pipeline_done | pipeline_error
   * 对话审核扩展（可选，后端实现）：review_reply | clarification_question（正文可用 message 或 content）。
   * 审核上行（可选）：POST /api/workbench/employee-ai/draft/review-chat body `{ message, run_id }`。
   * 与 workbenchStartSession/workbenchGetSession（轮询）完全独立。
   */
  streamEmployeeAiDraft: (
    brief: string,
    opts?: { provider?: string; model?: string; suggestedId?: string },
  ): Promise<Response> =>
    fetch('/api/workbench/employee-ai/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        brief,
        provider: opts?.provider || undefined,
        model: opts?.model || undefined,
        suggested_id: opts?.suggestedId || undefined,
      }),
    }),

  /** LLM 优化 system prompt，返回 {improved_prompt, diff_explanation}。 */
  refineSystemPrompt: (body: {
    current_prompt: string
    instruction: string
    role_context?: string
    provider?: string
    model?: string
  }) =>
    req('/api/workbench/employee-ai/refine-prompt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** 微软在线神经 TTS（服务端 edge-tts），返回 MP3 Blob */
  workbenchEdgeTts: (text: string, voice?: string, rate?: number) =>
    requestBlob('/api/workbench/tts/edge', {
      method: 'POST',
      body: JSON.stringify({
        text,
        ...(voice ? { voice } : {}),
        ...(rate != null && Number.isFinite(rate) ? { rate } : {}),
      }),
    }),

  /** 微软在线神经 TTS 流式（chunked MP3） */
  workbenchEdgeTtsStream: (text: string, voice?: string, rate?: number) =>
    requestStreamBlob('/api/workbench/tts/edge/stream', {
      method: 'POST',
      body: JSON.stringify({
        text,
        ...(voice ? { voice } : {}),
        ...(rate != null && Number.isFinite(rate) ? { rate } : {}),
      }),
    }),

  listStudioAssets: (params?: { offset?: number; limit?: number }) => {
    const o = params?.offset ?? 0
    const l = params?.limit ?? 50
    return req(`/api/workbench/studio-assets?offset=${encodeURIComponent(String(o))}&limit=${encodeURIComponent(String(l))}`)
  },
  uploadStudioAsset: (file: File, opts?: { kind?: string; metadata?: Record<string, unknown> }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.kind) form.append('kind', opts.kind)
    if (opts?.metadata && Object.keys(opts.metadata).length) {
      form.append('metadata', JSON.stringify(opts.metadata))
    }
    return req('/api/workbench/studio-assets', { method: 'POST', body: form })
  },
  deleteStudioAsset: (id: number) =>
    req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  patchStudioAssetMetadata: (id: number, metadata: Record<string, unknown>) =>
    req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify({ metadata }),
    }),
  downloadStudioAssetBlob: (id: number) =>
    requestBlob(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}/file`),

  knowledgeStatus: () => req('/api/knowledge/status'),
  knowledgeListDocuments: () => req('/api/knowledge/documents'),
  knowledgeUploadDocument: (file: File, opts?: { embeddingProvider?: string; embeddingModel?: string }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.embeddingProvider) form.append('embedding_provider', opts.embeddingProvider)
    if (opts?.embeddingModel) form.append('embedding_model', opts.embeddingModel)
    return req('/api/knowledge/documents', { method: 'POST', body: form })
  },
  knowledgeDeleteDocument: (docId: string) => req(`/api/knowledge/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }),
  knowledgeExtractText: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return req('/api/knowledge/extract-text', { method: 'POST', body: form })
  },
  knowledgeSearch: (query: string, limit = 6, opts?: { embeddingProvider?: string; embeddingModel?: string }) =>
    req('/api/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        limit,
        embedding_provider: opts?.embeddingProvider,
        embedding_model: opts?.embeddingModel,
      }),
    }),

  // v2: 集合 + 共享 + 跨上下文检索
  knowledgeV2Status: () => req('/api/knowledge/v2/status'),
  knowledgeV2ListCollections: (params?: { ownerKind?: string; ownerId?: string }) => {
    const qs: string[] = []
    if (params?.ownerKind) qs.push(`owner_kind=${encodeURIComponent(params.ownerKind)}`)
    if (params?.ownerId !== undefined && params?.ownerId !== null)
      qs.push(`owner_id=${encodeURIComponent(String(params.ownerId))}`)
    const suffix = qs.length ? `?${qs.join('&')}` : ''
    return req(`/api/knowledge/v2/collections${suffix}`)
  },
  knowledgeV2CreateCollection: (body: {
    owner_kind?: string
    owner_id?: string
    name: string
    description?: string
    visibility?: string
    embedding_model?: string
    embedding_dim?: number
  }) => req('/api/knowledge/v2/collections', { method: 'POST', body: JSON.stringify(body) }),
  knowledgeV2UpdateCollection: (
    id: number,
    body: { name?: string; description?: string; visibility?: string },
  ) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  knowledgeV2DeleteCollection: (id: number) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  knowledgeV2ListDocuments: (id: number) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`),
  knowledgeV2UploadDocument: (id: number, file: File, opts?: { embeddingProvider?: string; embeddingModel?: string }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.embeddingProvider) form.append('embedding_provider', opts.embeddingProvider)
    if (opts?.embeddingModel) form.append('embedding_model', opts.embeddingModel)
    return req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`,
      { method: 'POST', body: form },
    )
  },
  knowledgeV2DeleteDocument: (id: number, docId: string) =>
    req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    ),
  knowledgeV2ShareCollection: (
    id: number,
    body: { grantee_kind: string; grantee_id: string; permission?: string },
  ) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  knowledgeV2Unshare: (id: number, membershipId: number) =>
    req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share/${encodeURIComponent(String(membershipId))}`,
      { method: 'DELETE' },
    ),
  knowledgeV2Retrieve: (body: {
    query: string
    top_k?: number
    min_score?: number
    employee_id?: string | null
    workflow_id?: number | null
    org_id?: string | null
    collection_ids?: number[]
    embedding_provider?: string | null
    embedding_model?: string | null
  }) => req('/api/knowledge/v2/retrieve', { method: 'POST', body: JSON.stringify(body) }),

  openApiListConnectors: () => req('/api/openapi-connectors/'),
  openApiGetConnector: (id: number | string) => req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`),
  openApiImportConnector: (payload: unknown) =>
    req('/api/openapi-connectors/import', { method: 'POST', body: JSON.stringify(payload) }),
  openApiDeleteConnector: (id: number | string) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  openApiSaveCredentials: (id: number | string, authType: string, config: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, {
      method: 'PUT',
      body: JSON.stringify({ auth_type: authType, config }),
    }),
  openApiDeleteCredentials: (id: number | string) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, { method: 'DELETE' }),
  openApiToggleOperation: (id: number | string, operationId: string, enabled: boolean) =>
    req(
      `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}`,
      { method: 'PATCH', body: JSON.stringify({ enabled }) },
    ),
  openApiTestOperation: (id: number | string, operationId: string, payload: unknown) =>
    req(
      `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}/test`,
      { method: 'POST', body: JSON.stringify(payload || {}) },
    ),
  openApiPublishWorkflowNode: (id: number | string, payload: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/publish-workflow-node`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  openApiListLogs: (id: number | string, limit = 50, offset = 0) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/logs?limit=${limit}&offset=${offset}`),

  customerServiceChat: (payload: { message: string; session_id?: number | null; context?: Record<string, unknown> }) =>
    req('/api/customer-service/chat', { method: 'POST', body: JSON.stringify(payload) }),
  customerServiceSessions: () => req('/api/customer-service/sessions'),
  customerServiceSessionDetail: (id: number | string) =>
    req(`/api/customer-service/sessions/${encodeURIComponent(String(id))}`),
  customerServiceTickets: (status = '') =>
    req(`/api/customer-service/tickets${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  customerServiceTicketDetail: (id: number | string) =>
    req(`/api/customer-service/tickets/${encodeURIComponent(String(id))}`),
  customerServiceActions: (ticketId?: number | string) =>
    req(`/api/customer-service/actions${ticketId ? `?ticket_id=${encodeURIComponent(String(ticketId))}` : ''}`),
  customerServiceStandards: () => req('/api/customer-service/standards'),
  customerServiceCreateStandard: (payload: unknown) =>
    req('/api/customer-service/standards', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateStandard: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/standards/${encodeURIComponent(String(id))}`, {
      method: 'PUT',
      body: JSON.stringify(payload || {}),
    }),
  customerServiceIntegrations: () => req('/api/customer-service/integrations'),
  customerServiceCreateIntegration: (payload: unknown) =>
    req('/api/customer-service/integrations', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateIntegration: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/integrations/${encodeURIComponent(String(id))}`, {
      method: 'PUT',
      body: JSON.stringify(payload || {}),
    }),

  // ─── AI 数字管家 Butler ─────────────────────────────────────────────
  /** POST /api/agent/butler/corp-chat — 官网公开咨询（无需登录） */
  agentCorpChat: (payload: {
    messages: Array<{ role: string; content: string }>
    page_id?: string
    page_context?: string
    max_tokens?: number
  }) =>
    req('/api/agent/butler/corp-chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /api/agent/butler/chat — 发送对话（非流式） */
  agentButlerChat: (payload: {
    messages: unknown[]
    conversation_id?: number | null
    page_context?: string
  }) =>
    req('/api/agent/butler/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /api/agent/butler/chat/stream — SSE 流式对话 */
  agentButlerChatStream: (
    payload: {
      messages: unknown[]
      conversation_id?: number | null
      page_context?: string
    },
    signal?: AbortSignal,
  ) => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    headers.set('Accept', 'text/event-stream')
    return fetch('/api/agent/butler/chat/stream', {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify(payload),
    })
  },

  /** GET /api/agent/butler/skills — 获取 butler 类型的技能列表 */
  listButlerSkills: () => req('/api/agent/butler/skills'),

  /** POST /api/agent/butler/actions — 记录操作审计 */
  recordButlerAction: (payload: {
    route: string
    action: string
    args?: Record<string, unknown>
    risk: string
    status: 'success' | 'failed' | 'cancelled'
  }) =>
    req('/api/agent/butler/actions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** PATCH /api/agent/butler/skills/:id — 更新技能激活状态 */
  updateButlerSkillActive: (id: number | string, isActive: boolean) =>
    req(`/api/agent/butler/skills/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    }),

  /**
   * POST /api/agent/butler/orchestrate — 启动 vibe-coding 改写管线。
   * 返回 { session_id, status }，进度通过 workbenchGetSession 轮询。
   */
  butlerOrchestrateStart: (payload: {
    target_type: 'mod' | 'workflow' | 'employee'
    target_id: string
    brief: string
    scope?: string
    focus_paths?: string[]
    with_snapshot?: boolean
    provider?: string
    model?: string
  }) =>
    req('/api/agent/butler/orchestrate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /**
   * POST /api/agent/butler/all-hands-report — 数字管家召集全员汇报（管理员）。
   * 让每个在岗员工自己讲：① 文件架构与工作逻辑 ② 最近问题与解决 ③ 联网+GitHub 调研后的自我优化（含联动）。
   * 返回结构化 JSON（每岗一段固定 4 节 Markdown）；阻塞至全部完成（`concurrency` 决定快慢）。
   */
  butlerAllHandsReportStartSession: (payload: {
    employee_ids?: string[]
    with_research?: boolean
    max_employees?: number
    concurrency?: number
    user_question?: string
    synthesize?: boolean
  }) =>
    req('/api/agent/butler/all-hands-report/sessions', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),

  /**
   * 同步版：等待全员汇报完成后一次性返回。
   * 如果前置网关超时较短，建议优先使用 butlerAllHandsReportStartSession + workbenchGetSession 轮询。
   */
  butlerAllHandsReport: (payload: {
    employee_ids?: string[]
    with_research?: boolean
    max_employees?: number
    concurrency?: number
    user_question?: string
    synthesize?: boolean
  }) =>
    req('/api/agent/butler/all-hands-report', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
}

export { clearAuthTokens }
