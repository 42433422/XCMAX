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

function emptyLocalManifest(employeeId: string) {
  return { employee_id: employeeId, name: employeeId, handlers: [] }
}

function emptyLocalStatus(employeeId: string) {
  return {
    employee_id: employeeId,
    deployed: false,
    last_execution: null,
    execution_stats: { total_executions: 0, success_count: 0, success_rate: 0 },
  }
}

async function fallbackDutyHealth() {
  try {
    const ops = (await api.get('/api/xcmax/ops/duty-health')) as Record<string, unknown>
    const staffing = ops?.staffing
    if (staffing && typeof staffing === 'object') {
      return { ok: true, source: 'ops-fallback', staffing }
    }
  } catch {
    /* ignore */
  }
  return {
    ok: true,
    source: 'client-fallback',
    staffing: {
      planned_count: 0,
      registered_count: 0,
      missing_employees: [],
      extra_employees: [],
      areas: [],
    },
  }
}

const xcmaxMarketProxy = {
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
  adminYuangonOnboardStatus: () => marketReq('admin/yuangon-onboard/status'),
  adminYuangonOnboardRun: (
    payload: { pkg_ids?: string[] | string; dry_run?: boolean; force?: boolean } = {},
  ) => {
    const pkgIds = Array.isArray(payload.pkg_ids)
      ? payload.pkg_ids.map((id) => String(id || '').trim()).filter(Boolean).join(',')
      : String(payload.pkg_ids || '').trim()
    return marketReq('admin/yuangon-onboard/run', {
      method: 'POST',
      body: {
        dry_run: Boolean(payload.dry_run),
        force: Boolean(payload.force),
        pkg_ids: pkgIds,
      },
    })
  },
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
    if (!(await isLocalDutyApiAvailable())) return emptyLocalStatus(employeeId)
    try {
      return await api.get(`${LOCAL_PREFIX}/employees/${encodeURIComponent(employeeId)}/status`)
    } catch (e: unknown) {
      const err = e as { status?: number }
      if (err?.status === 404) return emptyLocalStatus(employeeId)
      throw e
    }
  },
  getEmployeeManifest: async (employeeId: string) => {
    if (!(await isLocalDutyApiAvailable())) return emptyLocalManifest(employeeId)
    try {
      return await api.get(`${LOCAL_PREFIX}/employees/${encodeURIComponent(employeeId)}/manifest`)
    } catch (e: unknown) {
      const err = e as { status?: number; message?: string }
      if (
        err?.status === 404
        || String(err?.message || '').includes('不存在')
        || String(err?.message || '').includes('未找到')
      ) {
        return emptyLocalManifest(employeeId)
      }
      throw e
    }
  },
  executeEmployeeTask: (employeeId: string, task: string, inputData: unknown) =>
    marketReq(`employees/${encodeURIComponent(employeeId)}/execute`, {
      method: 'POST',
      body: { task, input_data: inputData ?? {} },
    }),
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
