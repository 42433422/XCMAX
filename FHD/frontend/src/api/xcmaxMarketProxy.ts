/**
 * 编制图读路径走 FHD 本地 API；写操作 / LLM 仍经 market-proxy（需市场管理员）。
 */
import api from '@/api/core'

const MARKET_PREFIX = '/api/xcmax/market-proxy'
const LOCAL_PREFIX = '/api/xcmax/local'

function marketPath(subpath: string): string {
  const p = String(subpath || '').replace(/^\//, '')
  return `${MARKET_PREFIX}/${p}`
}

async function marketReq<T = unknown>(
  subpath: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  const url = marketPath(subpath)
  const method = (init?.method || 'GET').toUpperCase()
  if (method === 'GET') return api.get(url) as Promise<T>
  if (method === 'DELETE') return api.delete(url) as Promise<T>
  if (method === 'PUT') return api.put(url, init?.body) as Promise<T>
  return api.post(url, init?.body) as Promise<T>
}

let localDutyApiAvailable: boolean | null = null
let localDutyApiProbe: Promise<boolean> | null = null

/** 探测 /api/xcmax/local/* 是否已由当前后端挂载（旧进程仅 404，避免 52× manifest 刷屏）。 */
export async function isLocalDutyApiAvailable(): Promise<boolean> {
  if (localDutyApiAvailable !== null) return localDutyApiAvailable
  if (!localDutyApiProbe) {
    localDutyApiProbe = (async () => {
      try {
        await api.get(`${LOCAL_PREFIX}/duty-graph/health`)
        localDutyApiAvailable = true
      } catch (e: unknown) {
        const err = e as { status?: number }
        localDutyApiAvailable = err?.status !== 404
      }
      return localDutyApiAvailable
    })()
  }
  return localDutyApiProbe
}

function explicitHealthOk(health: Record<string, unknown>): boolean {
  return health.ok === true || health.success === true || health.healthy === true
}

function assertDutyGraphHealth(health: Record<string, unknown>): void {
  const staffing = health.staffing as Record<string, unknown> | undefined
  const staffingError = typeof staffing?.error === 'string' ? staffing.error.trim() : ''
  const message = typeof health.message === 'string' ? health.message.trim() : ''
  if (staffingError || !explicitHealthOk(health)) {
    throw new Error(staffingError || message || '编制健康接口未返回可信健康状态')
  }
}

function dutyRuntimeUnavailable(resource: string): Error {
  return new Error(`AI 员工运行时不可用，无法读取${resource}`)
}

async function fallbackDutyHealth() {
  try {
    const ops = (await api.get('/api/xcmax/ops/duty-health')) as Record<string, unknown>
    const staffing = ops?.staffing
    if (staffing && typeof staffing === 'object') {
      return {
        ...ops,
        ok: explicitHealthOk(ops),
        source: 'ops-fallback',
        staffing,
      }
    }
  } catch {
    /* ignore */
  }
  return {
    ok: false,
    success: false,
    source: 'runtime-unavailable',
    message: '本地与运维编制健康接口均不可用',
    staffing: {
      error: '本地与运维编制健康接口均不可用',
      missing_employees: [],
      missing_local_employee_packs: [],
      extra_employees: [],
      areas: [],
    },
  }
}

const xcmaxMarketProxy = {
  assertDutyGraphHealth,
  adminListNoKeyEmployees: () => marketReq('admin/duty-graph/no-key-employees'),
  adminAlignSingleEmployeeLlmToAuto: (pkgId: string, dryRun = false) =>
    marketReq(`admin/employee-packs/${encodeURIComponent(pkgId)}/align-llm-to-auto-single?dry_run=${dryRun ? 'true' : 'false'}`, {
      method: 'POST',
    }),
  adminDutyGraphHealth: async () => {
    const available = await isLocalDutyApiAvailable()
    if (!available) return fallbackDutyHealth()
    try {
      return await api.get(`${LOCAL_PREFIX}/duty-graph/health`)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) {
        localDutyApiAvailable = false
        return fallbackDutyHealth()
      }
      throw e
    }
  },
  adminDutyGraphRunStart: (payload: Record<string, unknown>) =>
    marketReq('admin/duty-graph/runs', { method: 'POST', body: payload }),
  adminDutyGraphRunDetail: (runId: number | string) =>
    marketReq(`admin/duty-graph/runs/${encodeURIComponent(String(runId))}`),
  adminEmployeeExecutionCapabilities: (employeeIds?: string[]) =>
    marketReq('admin/employees/execution-capabilities', {
      method: 'POST',
      body: { employee_ids: Array.isArray(employeeIds) ? employeeIds : [] },
    }),
  adminEmployeeExecutionMetrics: (
    employeeId: string,
    params?: { limit?: number; offset?: number; user_id?: number },
  ) => {
    const p = new URLSearchParams()
    if (params?.limit != null) p.set('limit', String(params.limit))
    if (params?.offset != null) p.set('offset', String(params.offset))
    if (params?.user_id != null) p.set('user_id', String(params.user_id))
    const q = p.toString()
    return marketReq(
      `admin/employees/${encodeURIComponent(employeeId)}/execution-metrics${q ? `?${q}` : ''}`,
    )
  },
  getEmployeeStatus: async (employeeId: string) => {
    if (!(await isLocalDutyApiAvailable())) {
      throw dutyRuntimeUnavailable(`员工 ${employeeId} 的运行状态`)
    }
    try {
      return await api.get(`${LOCAL_PREFIX}/employees/${encodeURIComponent(employeeId)}/status`)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) {
        throw new Error(`AI 员工 ${employeeId} 的运行状态不存在`)
      }
      throw e
    }
  },
  getEmployeeManifest: async (employeeId: string) => {
    if (!(await isLocalDutyApiAvailable())) {
      throw dutyRuntimeUnavailable(`员工 ${employeeId} 的 manifest`)
    }
    try {
      return await api.get(`${LOCAL_PREFIX}/employees/${encodeURIComponent(employeeId)}/manifest`)
    } catch (e: unknown) {
      const err = e as { status?: number; message?: string }
      if (
        err?.status === 404
        || String(err?.message || '').includes('不存在')
        || String(err?.message || '').includes('未找到')
      ) {
        throw new Error(`AI 员工 ${employeeId} 的 manifest 不存在`)
      }
      throw e
    }
  },
  executeEmployeeTask: async (employeeId: string, task: string, inputData: unknown) => {
    const body = { task, input_data: inputData ?? {} }
    const marketExecute = () =>
      marketReq(`employees/${encodeURIComponent(employeeId)}/execute`, {
        method: 'POST',
        body,
      })
    if (!(await isLocalDutyApiAvailable())) return marketExecute()
    try {
      return await api.post(`${LOCAL_PREFIX}/employees/${encodeURIComponent(employeeId)}/execute`, body)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) {
        localDutyApiAvailable = false
        return marketExecute()
      }
      throw e
    }
  },
  localEmployeeCronJobs: () =>
    api.get(`${LOCAL_PREFIX}/employee-cron/jobs`) as Promise<unknown>,
  localRunEmployeeCronJob: (jobId: string, payload?: { task?: string; input_data?: unknown }) =>
    api.post(`${LOCAL_PREFIX}/employee-cron/jobs/${encodeURIComponent(jobId)}/run`, payload ?? {}) as Promise<unknown>,
  selfMaintenanceRuntimeStatus: async (limit = 80) => {
    const q = `limit=${encodeURIComponent(String(limit))}`
    try {
      return await api.get(`${LOCAL_PREFIX}/ops/self-maintenance/status?${q}`)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) {
        return marketReq(`ops/self-maintenance/status?${q}`)
      }
      throw e
    }
  },
  selfMaintenanceGovernanceReview: async (payload: { note?: string } = {}) => {
    try {
      return await api.post(`${LOCAL_PREFIX}/ops/self-maintenance/governance-review`, payload)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) {
        return marketReq('ops/self-maintenance/governance-review', {
          method: 'POST',
          body: payload,
        })
      }
      throw e
    }
  },
  llmStatus: () => marketReq('llm/status'),
  llmResolveChatDefault: () => marketReq('llm/resolve-chat-default'),
  llmChat: (provider: string, model: string, messages: unknown[], maxTokens = 1024) =>
    marketReq('llm/chat', {
      method: 'POST',
      body: { provider, model, messages, max_tokens: maxTokens },
    }),
  /** 员工大会轮询：走 FHD 本地 MODstore :8788，不再代理远端 xiu-ci。 */
  workbenchGetSession: (sessionId: string) =>
    api.get(`/api/xcmax/admin/all-hands-report/sessions/${encodeURIComponent(sessionId)}`) as Promise<unknown>,
  butlerAllHandsReportStartSession: (payload: Record<string, unknown>) =>
    api.post('/api/xcmax/admin/all-hands-report/sessions', payload) as Promise<unknown>,
}

export default xcmaxMarketProxy
