// 视图模型 computed：从详情/摘要/AI 蓝图派生的只读展示数据（原单体实现原样迁移）。
import { computed } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { getIndustryPreset } from '@/constants/industryPresets'
import { WORKFLOW_SUMMARY_MAX, asLooseRecord, truncatePlain, type LooseRecord } from '../../types'
import type { ModAuthoringData, ModAuthoringSummary, WorkflowEmployeeViewRow } from './types'

export interface ViewModelDeps {
  modData: Ref<ModAuthoringData | null>
  summary: Ref<ModAuthoringSummary | null>
  aiBlueprint: Ref<LooseRecord | null>
  modId: ComputedRef<string>
}

export function createViewModels(deps: ViewModelDeps) {
  const { modData, summary, aiBlueprint, modId } = deps

  const modDescriptionLine = computed(() => {
    const d = asLooseRecord(modData.value?.manifest).description
    return typeof d === 'string' && d.trim() ? d.trim() : ''
  })

  const employeeReadiness = computed<LooseRecord | null>(() => {
    const fromDetail = modData.value?.employee_readiness
    if (fromDetail && typeof fromDetail === 'object') return asLooseRecord(fromDetail)
    const fromSummary = summary.value?.employee_readiness
    if (fromSummary && typeof fromSummary === 'object') return asLooseRecord(fromSummary)
    const fromBlueprint = aiBlueprint.value?.employee_readiness
    if (fromBlueprint && typeof fromBlueprint === 'object') return asLooseRecord(fromBlueprint)
    return null
  })

  const employeeReadinessRowsByIndex = computed(() => {
    const rows = Array.isArray(employeeReadiness.value?.employees) ? employeeReadiness.value.employees : []
    const map = new Map<number, LooseRecord>()
    for (const value of rows) {
      const row = asLooseRecord(value)
      const idx = Number(row.index)
      if (Number.isFinite(idx) && idx >= 0) map.set(idx, row)
    }
    return map
  })

  const employeeReadinessGaps = computed(() => {
    const gaps = employeeReadiness.value?.gaps
    return Array.isArray(gaps)
      ? gaps
          .map((value: unknown) => String(value))
          .filter(Boolean)
          .slice(0, 8)
      : []
  })

  const readinessSummaryLabel = computed(() => {
    const s = employeeReadiness.value?.summary
    const summaryRecord = asLooseRecord(s)
    const total = Number(summaryRecord.total || 0)
    const ready = Number(summaryRecord.ready || 0)
    if (!total) return '无员工'
    return `${ready}/${total} 可工作`
  })

  const workflowEmployeesRows = computed<WorkflowEmployeeViewRow[]>(() => {
    const raw = asLooseRecord(modData.value?.manifest).workflow_employees
    if (!Array.isArray(raw)) return []
    return raw.map((item, index) => {
      const o = asLooseRecord(item)
      const id = typeof o.id === 'string' ? o.id.trim() : ''
      const label = typeof o.label === 'string' ? o.label.trim() : ''
      const panelTitle = typeof o.panel_title === 'string' ? o.panel_title.trim() : ''
      const summary = typeof o.panel_summary === 'string' ? o.panel_summary.trim() : ''
      const title = label || panelTitle || id || `员工 ${index + 1}`
      const bodyFull = summary
      const bodyShort = bodyFull ? truncatePlain(bodyFull, WORKFLOW_SUMMARY_MAX) : ''
      const widRaw = o.workflow_id ?? o.workflowId
      const linkedWorkflowId =
        widRaw == null || widRaw === ''
          ? 0
          : (() => {
              const n = parseInt(String(widRaw), 10)
              return Number.isFinite(n) && n > 0 ? n : 0
            })()
      const readiness = employeeReadinessRowsByIndex.value.get(index) || null
      return {
        index,
        raw: { ...o },
        id,
        label,
        panelTitle,
        title,
        bodyFull,
        bodyShort,
        isEmpty: !id && !label && !panelTitle,
        linkedWorkflowId,
        readiness,
        ready: Boolean(readiness?.ready),
      }
    })
  })

  const frontendConfigPath = computed(() => {
    const cfg = asLooseRecord(modData.value?.manifest?.config)
    return typeof cfg.frontend_spec === 'string' && cfg.frontend_spec.trim() ? cfg.frontend_spec.trim() : 'config/frontend_spec.json'
  })

  const frontendEntryPath = computed(() => {
    const frontend = asLooseRecord(modData.value?.manifest?.frontend)
    if (typeof frontend.pro_entry_path === 'string' && frontend.pro_entry_path.trim()) return frontend.pro_entry_path.trim()
    const menu = Array.isArray(frontend.menu) ? frontend.menu : []
    const first = asLooseRecord(menu[0])
    return typeof first.path === 'string' ? first.path.trim() : ''
  })

  const frontendSpecTitle = computed(() => {
    const spec = asLooseRecord(aiBlueprint.value?.frontend_app)
    return String(spec.title || spec.mod_name || '')
  })

  const frontendSpecPreview = computed(() => {
    const spec = aiBlueprint.value?.frontend_app
    if (!spec || typeof spec !== 'object') return ''
    return JSON.stringify(spec, null, 2)
  })

  const industryCard = computed<{ name: string; scenario: string } | null>(() => {
    const card = aiBlueprint.value?.industry_card
    if (card && typeof card === 'object') {
      const record = asLooseRecord(card)
      return { name: String(record.name || '通用'), scenario: String(record.scenario || '') }
    }
    const industry = aiBlueprint.value?.industry
    if (industry && typeof industry === 'object') {
      const record = asLooseRecord(industry)
      return {
        name: String(record.name || '通用'),
        scenario: String(record.scenario || ''),
      }
    }
    return null
  })

  const manifestSidebarStatus = computed(() => {
    const m = modData.value?.manifest as LooseRecord | undefined
    const industry = m?.industry
    const industryId = industry && typeof industry === 'object' ? String((industry as LooseRecord).id || '').trim() : ''
    const fe = m?.frontend as LooseRecord | undefined
    const menu = Array.isArray(fe?.menu) ? fe.menu : []
    const overrides = Array.isArray(m?.menu_overrides) ? (m.menu_overrides as unknown[]) : []
    return {
      industryId: industryId || '',
      industryName: industryId ? getIndustryPreset(industryId).name : '未写入',
      menuCount: menu.length,
      menuOverrideCount: overrides.length,
      modId: modId.value || '',
    }
  })

  const apiSummary = computed(() => {
    const src = asLooseRecord(aiBlueprint.value?.api_summary)
    const nodes = Array.isArray(src.nodes) ? src.nodes : []
    const warnings = Array.isArray(src.warnings) ? src.warnings.map((x: unknown) => String(x)) : []
    return { nodes, warnings }
  })

  const workflowSandboxRows = computed(() => {
    const src = asLooseRecord(aiBlueprint.value?.workflow_sandbox)
    return Array.isArray(src.reports) ? src.reports : []
  })

  const workflowSandboxOk = computed(() => {
    if (!aiBlueprint.value?.workflow_sandbox || typeof aiBlueprint.value.workflow_sandbox !== 'object') return false
    const src = asLooseRecord(aiBlueprint.value?.workflow_sandbox)
    return src.ok !== false
  })

  const modSandboxChecks = computed(() => {
    const src = asLooseRecord(aiBlueprint.value?.mod_sandbox)
    return Array.isArray(src.checks) ? src.checks : []
  })

  const modSandboxOk = computed(() => {
    if (!aiBlueprint.value?.mod_sandbox || typeof aiBlueprint.value.mod_sandbox !== 'object') return false
    const src = asLooseRecord(aiBlueprint.value?.mod_sandbox)
    return src.ok !== false
  })

  const vibeHealReport = computed(() => {
    const src = aiBlueprint.value?.vibe_heal
    if (!src || typeof src !== 'object') return null
    return asLooseRecord(src)
  })

  const vibeIndexReport = computed(() => {
    const src = aiBlueprint.value?.vibe_index
    if (!src || typeof src !== 'object') return null
    return asLooseRecord(src)
  })

  return {
    modDescriptionLine,
    employeeReadiness,
    employeeReadinessGaps,
    readinessSummaryLabel,
    workflowEmployeesRows,
    frontendConfigPath,
    frontendEntryPath,
    frontendSpecTitle,
    frontendSpecPreview,
    industryCard,
    manifestSidebarStatus,
    apiSummary,
    workflowSandboxRows,
    workflowSandboxOk,
    modSandboxChecks,
    modSandboxOk,
    vibeHealReport,
    vibeIndexReport,
  }
}
