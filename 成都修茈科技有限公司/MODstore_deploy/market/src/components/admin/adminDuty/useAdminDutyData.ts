/**
 * 花名册装载（Phase 1/2）、能力装载与自动刷新。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { nextTick } from 'vue'
import { api } from '../../../api'
import { BUTLER_PROFILE, butlerCapabilityView, extractEmployeeCapabilityView } from '../../../domain/butlerEmployeeProfile'
import { YUANGON_PKG_ROLE_LABELS } from '../../../domain/yuangonDutyRoster'
import type { LlmProviderStatus } from '../../../domain/llm/types'
import { providerRowHasUsableKey } from '../../../domain/llm/providerCredential'
import { ALL_PLANNED_IDS, CRAFT_PIPELINE_ORDER, isDeployedDutyRosterRow, craftEmployeeDependsOn } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { EmpRow, LlmProviderSt, EmpLlmCfg, EmpCapability } from './adminDutyTypes'

export function useAdminDutyData(s: AdminDutyState, ctx: { applyEmployeeQueryFromRoute: () => void | Promise<void> }) {
  const { applyEmployeeQueryFromRoute } = ctx
  const {
    employees, error, loading, loadingP2, healthMap, depsMap, empLlmMap, capabilityMap,
    empCapabilityViewMap, llmStatusMap, llmFernetConfigured, llmStatusFailed,
    anyProviderHasUsableKey, countdown, runTargetId, capLoading,
  } = s
  let countdownTimer = 0
  let refreshTimer = 0

function buildRosterEmployeeRows(missingIds: Set<string>): EmpRow[] {
  const ids = [...ALL_PLANNED_IDS].sort((a, b) =>
    (YUANGON_PKG_ROLE_LABELS[a] ?? a).localeCompare(YUANGON_PKG_ROLE_LABELS[b] ?? b, 'zh-CN'),
  )
  return ids.map((id) => ({
    id,
    name: YUANGON_PKG_ROLE_LABELS[id] ?? id,
    source: missingIds.has(id) ? ('v1_catalog' as const) : ('catalog' as const),
  }))
}


async function load() {
  error.value = ''
  loading.value = true
  employees.value = []
  healthMap.value = {}
  depsMap.value = {}
  empLlmMap.value = {}
  capabilityMap.value = {}
  empCapabilityViewMap.value = {}
  llmStatusFailed.value = false
  // Phase 4: fetch LLM provider key status once (runs in parallel with staffing)
  const llmStatusPromise = api.llmStatus().then((res: unknown) => {
    const r = res as Record<string, unknown>
    llmStatusFailed.value = false
    llmFernetConfigured.value = Boolean(r?.fernet_configured)
    const providers = Array.isArray(r?.providers) ? (r.providers as Record<string, unknown>[]) : []
    const m: Record<string, LlmProviderSt> = {}
    for (const p of providers) {
      const pid = String(p.provider ?? '').trim()
      if (pid) m[pid] = {
        provider: pid,
        label: String(p.label ?? pid),
        has_platform_key: Boolean(p.has_platform_key),
        has_user_override: Boolean(p.has_user_override),
      }
    }
    llmStatusMap.value = m
  }).catch(() => {
    llmStatusFailed.value = true
    llmFernetConfigured.value = false
    llmStatusMap.value = {}
  })

  try {
    const health = (await api.adminDutyGraphHealth()) as Record<string, unknown>
    const staffing = health?.staffing as Record<string, unknown> | undefined
    const errStaff = typeof staffing?.error === 'string' ? staffing.error : ''
    if (errStaff) throw new Error(errStaff)
    const missingRaw = Array.isArray(staffing?.missing_employees) ? staffing!.missing_employees : []
    const missingIds = new Set(
      (missingRaw as unknown[]).map((x) => String(x ?? '').trim()).filter(Boolean),
    )
    employees.value = [...buildRosterEmployeeRows(missingIds), butlerEmployeeRow()]
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
    // 仍展示编制矩阵，缺岗状态未知时按「已上架」乐观渲染，避免空白页
    employees.value = [...buildRosterEmployeeRows(new Set()), butlerEmployeeRow()]
  } finally {
    loading.value = false
  }
  seedVirtualEmployees()
  await llmStatusPromise
  if (!runTargetId.value && employees.value.length) runTargetId.value = employees.value[0].id
  const backendEmps = employees.value.filter(isDeployedDutyRosterRow)
  void loadPhase2(backendEmps)
  void loadCapabilities(backendEmps)
  await nextTick()
  void applyEmployeeQueryFromRoute()
}


function butlerEmployeeRow(): EmpRow {
  return {
    id: BUTLER_PROFILE.id,
    name: BUTLER_PROFILE.name,
    source: 'virtual',
    industry: BUTLER_PROFILE.industry,
  }
}


function seedVirtualEmployees() {
  const view = butlerCapabilityView()
  empCapabilityViewMap.value = {
    ...empCapabilityViewMap.value,
    [BUTLER_PROFILE.id]: view,
  }
  empLlmMap.value = {
    ...empLlmMap.value,
    [BUTLER_PROFILE.id]: {
      provider: 'auto',
      model: 'auto',
      handlers: view.handlers,
      needsLlm: true,
      activated: anyProviderHasUsableKey() || llmStatusFailed.value,
      keySource: 'auto',
    },
  }
  healthMap.value = {
    ...healthMap.value,
    [BUTLER_PROFILE.id]: { total: 0, success: 0, rate: 0, lastExecution: null },
  }
  capabilityMap.value = {
    ...capabilityMap.value,
    [BUTLER_PROFILE.id]: {
      employee_id: BUTLER_PROFILE.id,
      name: BUTLER_PROFILE.name,
      source: 'virtual',
      deployed: true,
      executable: true,
      reasons: [],
      handlers: view.handlers,
      declared_dependencies: view.dependsOn,
      llm: { provider: 'auto', model: 'auto', needs_llm: true, activated: true, key_source: 'auto' },
      risk: {
        high_risk: true,
        requires_confirmation: true,
        details: [
          {
            handler: 'butler_orchestrate',
            reason: 'vibe-coding 改写 Mod / 工作流 / 员工包属高风险动作，须用户明确确认',
            requires_approval: true,
          },
        ],
      },
      recent_execution: null,
      recent_ops_audits: [],
    },
  }

  for (const cid of CRAFT_PIPELINE_ORDER) {
    const prev = craftEmployeeDependsOn(cid)
    if (!employees.value.some((e) => e.id === cid)) {
      employees.value.push({
        id: cid,
        name: YUANGON_PKG_ROLE_LABELS[cid] || cid,
        source: 'virtual',
        industry: '制作车间',
      })
    }
    healthMap.value = { ...healthMap.value, [cid]: { total: 0, success: 0, rate: 0, lastExecution: null } }
    if (prev) depsMap.value = { ...depsMap.value, [cid]: [prev] }
  }
}


async function loadPhase2(emps: EmpRow[]) {
  if (!emps.length) return
  loadingP2.value = true
  const CONCUR = 6

  async function pool<T>(items: EmpRow[], fn: (e: EmpRow) => Promise<T>) {
    for (let i = 0; i < items.length; i += CONCUR) {
      await Promise.allSettled(items.slice(i, i + CONCUR).map(fn))
    }
  }

  await pool(emps, async (e) => {
    try {
      const s = await api.getEmployeeStatus(e.id) as Record<string, unknown>
      const st = (s?.execution_stats ?? {}) as Record<string, unknown>
      healthMap.value = {
        ...healthMap.value,
        [e.id]: {
          total:   Number(st.total_executions ?? 0),
          success: Number(st.success_count ?? 0),
          rate:    Number(st.success_rate ?? 0),
          lastExecution: typeof s.last_execution === 'string' ? s.last_execution : null,
        },
      }
    } catch { /* silent */ }
  })

  await pool(emps, async (e) => {
    try {
      const pack = await api.getEmployeeManifest(e.id) as Record<string, unknown>
      const mf = (pack?.manifest ?? pack) as Record<string, unknown>

      // ── depends_on ──────────────────────────────────────────────────────
      let deps: string[] = []
      if (Array.isArray(mf?.depends_on)) {
        deps = (mf.depends_on as unknown[]).map((d) => (typeof d === 'string' ? d.trim() : '')).filter(Boolean)
      } else {
        const v2d = mf?.employee_config_v2 as Record<string, unknown> | undefined
        const raw = (v2d?.collaboration as Record<string, unknown> | undefined)?.depends_on
        if (Array.isArray(raw)) deps = (raw as unknown[]).map((d) => (typeof d === 'string' ? d.trim() : '')).filter(Boolean)
      }
      if (deps.length) depsMap.value = { ...depsMap.value, [e.id]: deps }

      // ── Phase 4: extract LLM config from manifest ──────────────────────
      const v2 = mf?.employee_config_v2 as Record<string, unknown> | undefined
      const agentModel = (v2?.cognition as Record<string, unknown> | undefined)
        ?.agent as Record<string, unknown> | undefined
      const modelCfg = agentModel?.model as Record<string, unknown> | undefined
      const mfActions = mf?.actions as Record<string, unknown> | undefined
      const handlers = Array.isArray((v2?.actions as Record<string, unknown> | undefined)?.handlers)
        ? ((v2!.actions as Record<string, unknown>).handlers as string[])
        : (Array.isArray(mfActions?.handlers)
          ? (mfActions.handlers as unknown[]).map((h) => String(h ?? '')).filter(Boolean)
          : [])

      const provider   = String(modelCfg?.provider  ?? '').trim() || 'auto'
      const model      = String(modelCfg?.model_name ?? '').trim() || 'auto'
      const needsLlm   = handlers.some((h: string) => h !== 'echo' && h !== 'webhook')
      const isAutoLlm  = provider === 'auto' || model === 'auto'
      const provSt     = llmStatusMap.value[provider] as LlmProviderStatus | undefined
      const hasPlatKey = provSt?.has_platform_key ?? false
      const hasByokUsable =
        Boolean(provSt?.has_user_override) && llmFernetConfigured.value

      let credentialOk: boolean
      let keySource: EmpLlmCfg['keySource']
      if (isAutoLlm) {
        const anyOk = anyProviderHasUsableKey()
        credentialOk = anyOk
        keySource = anyOk ? 'auto' : 'none'
      } else {
        credentialOk = providerRowHasUsableKey(provSt, llmFernetConfigured.value)
        keySource = hasByokUsable ? 'byok' : hasPlatKey ? 'platform' : 'none'
      }

      const activated    = !needsLlm || credentialOk

      empLlmMap.value = {
        ...empLlmMap.value,
        [e.id]: { provider, model, handlers, needsLlm, activated, keySource },
      }

      // 「能做什么 · 怎么做」展示模型：直接复用 V2 manifest 字段
      empCapabilityViewMap.value = {
        ...empCapabilityViewMap.value,
        [e.id]: extractEmployeeCapabilityView(mf),
      }
    } catch { /* silent */ }
  })

  loadingP2.value = false
}


async function loadCapabilities(emps: EmpRow[]) {
  if (!emps.length) {
    capabilityMap.value = {}
    return
  }
  capLoading.value = true
  try {
    const payload = (await api.adminEmployeeExecutionCapabilities(
      emps.map((e) => e.id),
    )) as { items?: EmpCapability[] }
    const rows = Array.isArray(payload?.items) ? payload.items : []
    const next: Record<string, EmpCapability> = {}
    for (const row of rows) {
      const eid = String(row?.employee_id ?? '').trim()
      if (!eid) continue
      next[eid] = {
        employee_id: eid,
        name: String(row?.name ?? eid),
        source: String(row?.source ?? ''),
        deployed: Boolean(row?.deployed),
        executable: Boolean(row?.executable),
        reasons: Array.isArray(row?.reasons) ? row.reasons.map((x) => String(x ?? '')) : [],
        handlers: Array.isArray(row?.handlers) ? row.handlers.map((x) => String(x ?? '')) : [],
        declared_dependencies: Array.isArray(row?.declared_dependencies)
          ? row.declared_dependencies.map((x) => String(x ?? ''))
          : [],
        llm: {
          provider: String(row.llm?.provider ?? 'auto'),
          model: String(row.llm?.model ?? 'auto'),
          needs_llm: Boolean(row.llm?.needs_llm),
          activated: Boolean(row.llm?.activated),
          key_source: String(row.llm?.key_source ?? 'none'),
        },
        risk: {
          high_risk: Boolean(row.risk?.high_risk),
          requires_confirmation: Boolean(row.risk?.requires_confirmation),
          details: Array.isArray(row.risk?.details)
            ? row.risk.details.map((d) => ({
                handler: String(d?.handler ?? ''),
                reason: String(d?.reason ?? ''),
                command_id: String(d?.command_id ?? ''),
                requires_approval: Boolean(d?.requires_approval),
              }))
            : [],
        },
        recent_execution: row.recent_execution
          ? {
              id: Number(row.recent_execution.id) || 0,
              status: String(row.recent_execution.status ?? ''),
              task: String(row.recent_execution.task ?? ''),
              duration_ms: Number(row.recent_execution.duration_ms) || 0,
              llm_tokens: Number(row.recent_execution.llm_tokens) || 0,
              error: String(row.recent_execution.error ?? ''),
              created_at: typeof row.recent_execution.created_at === 'string'
                ? row.recent_execution.created_at
                : null,
            }
          : null,
        recent_ops_audits: Array.isArray(row.recent_ops_audits)
          ? row.recent_ops_audits.map((a) => ({
              id: Number(a?.id) || 0,
              handler: String(a?.handler ?? ''),
              command_id: String(a?.command_id ?? ''),
              exit_code: a?.exit_code == null ? null : Number(a.exit_code),
              dry_run: Boolean(a?.dry_run),
              approval_required: Boolean(a?.approval_required),
              created_at: typeof a?.created_at === 'string' ? a.created_at : null,
            }))
          : [],
      }
    }
    capabilityMap.value = next
  } catch {
    capabilityMap.value = {}
  } finally {
    capLoading.value = false
  }
}


function startAutoRefresh() {
  stopAutoRefresh()
  countdown.value = 30
  countdownTimer = window.setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      countdown.value = 30
      void loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
    }
  }, 1000)
  refreshTimer = 0 // not used separately; countdown drives refresh
}


function stopAutoRefresh() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = 0 }
  if (refreshTimer)   { clearInterval(refreshTimer);   refreshTimer   = 0 }
}


  return { buildRosterEmployeeRows, load, butlerEmployeeRow, seedVirtualEmployees, loadPhase2, loadCapabilities, startAutoRefresh, stopAutoRefresh }
}

export type AdminDutyData = ReturnType<typeof useAdminDutyData>
