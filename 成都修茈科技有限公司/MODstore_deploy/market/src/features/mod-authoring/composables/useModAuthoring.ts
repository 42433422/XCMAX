import { ref, computed, watch, reactive } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { api } from '@/api'
import { filterOutPlannedDutyEmployees } from '@/utils/workbenchEmployeeFilter'
import {
  getIndustryPreset,
  listIndustryPresets,
  manifestIndustryFromPreset,
} from '@/constants/industryPresets'
import {
  WORKFLOW_SUMMARY_MAX,
  asLooseRecord,
  truncatePlain,
  type LooseRecord,
  EXPERT_TABS,
} from '../types'

export function useModAuthoring(route: RouteLocationNormalizedLoaded, router: Router) {
const modDescriptionLine = computed(() => {
  const d = (modData.value as LooseRecord | null)?.manifest?.description
  return typeof d === 'string' && d.trim() ? d.trim() : ''
})

const employeeReadiness = computed<any>(() => {
  const fromDetail = (modData.value as LooseRecord | null)?.employee_readiness
  if (fromDetail && typeof fromDetail === 'object') return fromDetail
  const fromSummary = (summary.value as LooseRecord | null)?.employee_readiness
  if (fromSummary && typeof fromSummary === 'object') return fromSummary
  const fromBlueprint = (aiBlueprint.value as LooseRecord | null)?.employee_readiness
  if (fromBlueprint && typeof fromBlueprint === 'object') return fromBlueprint
  return null
})

const employeeReadinessRowsByIndex = computed(() => {
  const rows = Array.isArray(employeeReadiness.value?.employees) ? employeeReadiness.value.employees : []
  const map = new Map<number, any>()
  for (const row of rows) {
    const idx = Number(row?.index)
    if (Number.isFinite(idx) && idx >= 0) map.set(idx, row)
  }
  return map
})

const employeeReadinessGaps = computed(() => {
  const gaps = employeeReadiness.value?.gaps
  return Array.isArray(gaps) ? gaps.map((x: any) => String(x)).filter(Boolean).slice(0, 8) : []
})

const readinessSummaryLabel = computed(() => {
  const s = employeeReadiness.value?.summary
  const total = Number(s?.total || 0)
  const ready = Number(s?.ready || 0)
  if (!total) return '无员工'
  return `${ready}/${total} 可工作`
})

const workflowEmployeesRows = computed(() => {
  const raw = (modData.value as LooseRecord | null)?.manifest?.workflow_employees
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

const tab = ref('guide')
const loading = ref(true)
const loadError = ref('')
const modData = ref<LooseRecord | null>(null)
const summary = ref<LooseRecord | null>(null)
const aiBlueprint = ref<LooseRecord | null>(null)
const manifestText = ref('')
const manifestSaveWarnings = ref<string[]>([])
const message = ref('')
const messageOk = ref(true)
const savingManifest = ref(false)
const selectedPath = ref('')
const fileContent = ref('')
const loadingFile = ref(false)
const savingFile = ref(false)
const fileWarnings = ref<string[]>([])
const loadingSummary = ref(false)
const frontendBusy = ref(false)
const frontendBrief = ref('')

const snapshotsRows = ref<LooseRecord[]>([])
const snapshotsLoadErr = ref('')
const snapshotBusy = ref(false)
const snapshotLabelDraft = ref('')

const modId = computed(() => String(route.params.modId || ''))

const frontendConfigPath = computed(() => {
  const cfg = modData.value?.manifest?.config
  return typeof cfg?.frontend_spec === 'string' && cfg.frontend_spec.trim()
    ? cfg.frontend_spec.trim()
    : 'config/frontend_spec.json'
})

const frontendEntryPath = computed(() => {
  const frontend = modData.value?.manifest?.frontend
  if (!frontend || typeof frontend !== 'object') return ''
  if (typeof frontend.pro_entry_path === 'string' && frontend.pro_entry_path.trim()) return frontend.pro_entry_path.trim()
  const menu = Array.isArray(frontend.menu) ? frontend.menu : []
  const first = menu[0]
  return typeof first?.path === 'string' ? first.path.trim() : ''
})

const frontendSpecTitle = computed(() => {
  const spec = aiBlueprint.value?.frontend_app
  return spec && typeof spec === 'object' ? String(spec.title || spec.mod_name || '') : ''
})

const frontendSpecPreview = computed(() => {
  const spec = aiBlueprint.value?.frontend_app
  if (!spec || typeof spec !== 'object') return ''
  return JSON.stringify(spec, null, 2)
})

const PREFILL_KEY = 'modstore_employee_prefill'

// ── AI pipeline suggestions (读自 employee_config_v2.metadata) ────────────────
const suggestedSkills = computed<Array<{ name: string; brief: string }>>(() => {
  const meta = modData.value?.manifest?.employee_config_v2?.metadata
  return Array.isArray(meta?.suggested_skills) ? meta.suggested_skills : []
})

const suggestedPricing = computed<{ tier: string; cny: number; period: string; reasoning?: string } | null>(() => {
  const meta = modData.value?.manifest?.employee_config_v2?.metadata
  return meta?.suggested_pricing && typeof meta.suggested_pricing === 'object' ? meta.suggested_pricing : null
})

// ── Refine system prompt ──────────────────────────────────────────────────────
const refinePromptLoading = ref(false)
const refinePromptError = ref('')
const refinePromptDiff = ref('')

async function handleRefineSystemPrompt() {
  const v2 = modData.value?.manifest?.employee_config_v2
  const currentPrompt = v2?.cognition?.agent?.system_prompt || ''
  if (!currentPrompt) {
    flash('请先在配置中填写 system_prompt', false)
    return
  }
  const instruction = window.prompt('优化说明（可选）', '') || ''
  if (!instruction.trim()) return
  refinePromptLoading.value = true
  refinePromptError.value = ''
  refinePromptDiff.value = ''
  try {
    const res = await api.refineSystemPrompt({
      current_prompt: currentPrompt,
      instruction,
      role_context: `${modData.value?.manifest?.name || ''} - ${modData.value?.manifest?.description || ''}`,
    })
    if (!res?.improved_prompt) throw new Error('未收到优化结果')
    // Write back into manifest
    const mf = JSON.parse(JSON.stringify(modData.value?.manifest || {}))
    if (!mf.employee_config_v2) mf.employee_config_v2 = {}
    if (!mf.employee_config_v2.cognition) mf.employee_config_v2.cognition = {}
    if (!mf.employee_config_v2.cognition.agent) mf.employee_config_v2.cognition.agent = {}
    mf.employee_config_v2.cognition.agent.system_prompt = res.improved_prompt
    await api.putModManifest(modId.value, mf)
    refinePromptDiff.value = res.diff_explanation || ''
    flash('System Prompt 已优化并保存', true)
    await reload()
  } catch (e) {
    refinePromptError.value = (e as Error)?.message || String(e)
    flash(`Prompt 优化失败: ${refinePromptError.value}`, false)
  } finally {
    refinePromptLoading.value = false
  }
}

function applyPricingSuggestion() {
  if (!suggestedPricing.value) return
  // The pricing suggestion shows up in the guide; this helper opens the publishing modal
  // if it exists, or just copies the suggestion to clipboard as a hint.
  const p = suggestedPricing.value
  const text = `建议定价：${p.tier} ¥${p.cny}/${p.period === 'month' ? '月' : p.period === 'year' ? '年' : '次'}`
  navigator.clipboard?.writeText(text).then(
    () => flash('已复制定价建议', true),
    () => flash(text, true),
  )
}
// ─────────────────────────────────────────────────────────────────────────────

const industryCard = computed(() => {
  const card = aiBlueprint.value?.industry_card
  if (card && typeof card === 'object') return card
  const industry = aiBlueprint.value?.industry
  if (industry && typeof industry === 'object') {
    return {
      name: industry.name || '通用',
      scenario: industry.scenario || '',
    }
  }
  return null
})

const industryPresetList = listIndustryPresets()
const selectedIndustryPreset = ref('通用')
const selectedIndustryScenario = computed(() => getIndustryPreset(selectedIndustryPreset.value).scenario)

watch(
  () => modData.value?.manifest?.industry,
  (ind) => {
    const id = ind && typeof ind === 'object' ? String((ind as LooseRecord).id || '').trim() : ''
    if (id && industryPresetList.some((p) => p.id === id)) {
      selectedIndustryPreset.value = id
    }
  },
  { immediate: true },
)

async function applyIndustryPresetToManifest() {
  let parsed: LooseRecord
  try {
    parsed = JSON.parse(manifestText.value) as LooseRecord
  } catch (e) {
    flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
    return
  }
  parsed.industry = manifestIndustryFromPreset(selectedIndustryPreset.value)
  const preset = getIndustryPreset(selectedIndustryPreset.value)
  if (parsed.frontend && typeof parsed.frontend === 'object') {
    const fe = parsed.frontend as LooseRecord
    const shell = fe.shell && typeof fe.shell === 'object' ? (fe.shell as LooseRecord) : {}
    fe.shell = shell
    const settings =
      shell.settings && typeof shell.settings === 'object' ? (shell.settings as LooseRecord) : {}
    shell.settings = settings
    settings.default_industry = preset.id
    settings.industry_options = industryPresetList.map((p) => p.id)
  }
  manifestText.value = JSON.stringify(parsed, null, 2)
  const menuCount = Array.isArray((parsed.frontend as LooseRecord | undefined)?.menu)
    ? ((parsed.frontend as LooseRecord).menu as unknown[]).length
    : 0
  await saveManifest({
    successMessage: `行业已保存：${preset.name}（菜单 ${menuCount} 项）`,
    flashDurationMs: 4000,
  })
}

const manifestSidebarStatus = computed(() => {
  const m = modData.value?.manifest as LooseRecord | undefined
  const industry = m?.industry
  const industryId =
    industry && typeof industry === 'object' ? String((industry as LooseRecord).id || '').trim() : ''
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
  const src = aiBlueprint.value?.api_summary
  const nodes = Array.isArray(src?.nodes) ? src.nodes : []
  const warnings = Array.isArray(src?.warnings) ? src.warnings.map((x: unknown) => String(x)) : []
  return { nodes, warnings }
})

const workflowSandboxRows = computed(() => {
  const src = aiBlueprint.value?.workflow_sandbox
  return Array.isArray(src?.reports) ? src.reports : []
})

const workflowSandboxOk = computed(() => {
  const src = aiBlueprint.value?.workflow_sandbox
  if (!src || typeof src !== 'object') return false
  return src.ok !== false
})

const modSandboxChecks = computed(() => {
  const src = aiBlueprint.value?.mod_sandbox
  return Array.isArray(src?.checks) ? src.checks : []
})

const modSandboxOk = computed(() => {
  const src = aiBlueprint.value?.mod_sandbox
  if (!src || typeof src !== 'object') return false
  return src.ok !== false
})

const vibeHealReport = computed(() => {
  const src = aiBlueprint.value?.vibe_heal
  if (!src || typeof src !== 'object') return null
  return src as Record<string, any>
})

const vibeIndexReport = computed(() => {
  const src = aiBlueprint.value?.vibe_index
  if (!src || typeof src !== 'object') return null
  return src as Record<string, any>
})

const linkableWorkflows = ref<Array<{ id: number; name?: string }>>([])
const linkPick = reactive<Record<number, number>>({})
const linkWorkflowBusy = ref(false)
/** workflow_employees 行 index，一键登记 API 进行中 */
const registerCatalogBusy = ref(-1)
/** 重试「画布 employee 对齐」 */
const patchWorkflowBusy = ref(false)
const closureBusy = ref(false)

const empModalOpen = ref(false)
const empModalMode = ref('add')
const empEditIndex = ref(-1)
const empDraft = ref({ id: '', label: '', panel_title: '', panel_summary: '' })
const empScaffoldRouter = ref(false)
const empModalSaving = ref(false)
const empModalError = ref('')
const empModalMergeHint = ref('')
const empScaffoldDone = ref(false)

const empPickOpen = ref(false)
const empPickRows = ref<
  {
    pickKey: string
    id: string
    name: string
    version: string
    description: string
    sourceLabel: string
    catalogPkgId?: string
  }[]
>([])
const empPickLoading = ref(false)
const empPickError = ref('')
const empPickSaving = ref(false)

const EMP_ID_RE = /^[a-z][a-z0-9_-]{0,63}$/

function slugWorkflowEmpId(raw: string): string {
  let x = String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/\./g, '_')
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  if (!x || !/^[a-z]/.test(x)) {
    x = `emp${Date.now().toString(36)}`
  }
  x = x.slice(0, 64)
  if (!EMP_ID_RE.test(x)) {
    x = `e${Date.now().toString(36)}`.slice(0, 64)
  }
  return x
}

function allocateWorkflowEmployeeId(taken: Set<string>, preferredRaw: string): string {
  const base = slugWorkflowEmpId(preferredRaw)
  if (!taken.has(base)) return base
  for (let i = 2; i < 200; i++) {
    const suf = `x${i}`
    const maxBase = Math.max(1, 64 - suf.length)
    const candidate = `${base.slice(0, maxBase)}${suf}`
    if (!taken.has(candidate) && EMP_ID_RE.test(candidate)) return candidate
  }
  return slugWorkflowEmpId(`emp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`)
}

async function openEmployeePickModal() {
  empPickOpen.value = true
  empPickError.value = ''
  empPickRows.value = []
  await loadEmpPickList()
}

function closeEmployeePickModal() {
  empPickOpen.value = false
  empPickError.value = ''
  empPickLoading.value = false
}

async function loadEmpPickList() {
  empPickLoading.value = true
  empPickError.value = ''
  try {
    const [sqlRows, v1Rows, catalogRes] = await Promise.all([
      api.listEmployees().catch(() => []),
      api.listV1Packages('employee_pack', '', 120, 0).catch(() => ({ packages: [] })),
      api.catalog('', 'employee_pack', 120, 0).catch(() => ({ items: [] })),
    ])
    const merged = new Map<
      string,
      {
        pickKey: string
        id: string
        name: string
        version: string
        description: string
        sourceLabel: string
        catalogPkgId?: string
      }
    >()
    for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
      const ex = e as { id?: string; name?: string; version?: string; description?: string }
      const id = String(ex?.id || '').trim()
      if (!id) continue
      merged.set(id, {
        pickKey: id,
        id,
        name: String(ex?.name || id).trim() || id,
        version: String(ex?.version || '').trim(),
        description: typeof ex?.description === 'string' ? ex.description : '',
        sourceLabel: '执行器目录',
      })
    }
    for (const p of v1Rows?.packages || []) {
      const pkg = p as { id?: string; name?: string; version?: string; description?: string }
      const id = String(pkg?.id || '').trim()
      if (!id || merged.has(id)) continue
      merged.set(id, {
        pickKey: id,
        id,
        name: String(pkg?.name || id).trim() || id,
        version: String(pkg?.version || '').trim(),
        description: typeof pkg?.description === 'string' ? pkg.description : '',
        sourceLabel: '本地包目录',
      })
    }
    for (const it of catalogRes?.items || []) {
      const row = it as { pkg_id?: string; name?: string; version?: string; description?: string }
      const pkgId = String(row?.pkg_id || '').trim()
      if (!pkgId || merged.has(pkgId)) continue
      merged.set(pkgId, {
        pickKey: `catalog:${pkgId}`,
        id: pkgId,
        name: String(row?.name || pkgId).trim() || pkgId,
        version: String(row?.version || '').trim(),
        description: typeof row?.description === 'string' ? row.description : '',
        sourceLabel: 'AI 市场',
        catalogPkgId: pkgId,
      })
    }
    empPickRows.value = filterOutPlannedDutyEmployees([...merged.values()]).sort((a, b) =>
      String(a.name).localeCompare(String(b.name), 'zh-CN'),
    )
  } catch (e: unknown) {
    empPickError.value = e instanceof Error ? e.message : String(e)
    empPickRows.value = []
  } finally {
    empPickLoading.value = false
  }
}

function goMyEmployees() {
  closeEmployeePickModal()
  router.push({ name: 'workbench-unified', query: { focus: 'employee' } })
}

async function confirmPickEmployee(row: {
  id: string
  name: string
  description: string
  sourceLabel: string
  catalogPkgId?: string
}) {
  if (empPickSaving.value) return
  empPickSaving.value = true
  empPickError.value = ''
  try {
    const wf = getWorkflowEmployeesArray()
    const taken = new Set<string>()
    for (const x of wf) {
      const id = String(x?.id || '').trim()
      if (id) taken.add(id)
    }
    const internalId = allocateWorkflowEmployeeId(taken, row.id)
    const label = String(row.name || '').trim() || row.id
    const panel_title = String(row.name || '').trim() || row.id
    const panel_summary =
      typeof row.description === 'string' && row.description.trim()
        ? row.description.trim().slice(0, 8000)
        : `来自${row.sourceLabel}的员工包「${row.id}」。`
    const entry: Record<string, string> = {
      id: internalId,
      label,
      panel_title,
      panel_summary,
    }
    const catalogPkgId = String(row.catalogPkgId || row.id || '').trim()
    if (catalogPkgId && (row.sourceLabel === 'AI 市场' || row.catalogPkgId)) {
      entry.catalog_pkg_id = catalogPkgId
    }
    wf.push(entry)
    await persistWorkflowEmployees(wf)
    closeEmployeePickModal()
  } catch (e: unknown) {
    empPickError.value = e instanceof Error ? e.message : String(e)
  } finally {
    empPickSaving.value = false
  }
}

async function runWorkflowEmployeeClosure() {
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录后再执行员工闭环', false)
    return
  }
  if (!modId.value) return
  closureBusy.value = true
  try {
    const res = await api.runWorkflowEmployeeClosure(modId.value, {
      register_missing: true,
      patch_canvas: true,
      industry: String((modData.value as any)?.manifest?.industry?.id || '通用'),
    })
    const reg = res?.pack_register
    const regErrs = Array.isArray(reg?.errors) ? reg.errors.length : 0
    if (res?.ok) {
      flash('员工闭环完成：登记与画布已对齐', true)
    } else {
      const gaps = Array.isArray(res?.readiness_after?.gaps) ? res.readiness_after.gaps[0] : ''
      flash(
        regErrs
          ? `闭环已执行，登记有 ${regErrs} 项失败；${gaps || '请查看下方各行'}`
          : `闭环已执行，仍有缺口：${gaps || '请查看下方说明'}`,
        false,
      )
    }
    await reload()
  } catch (e: unknown) {
    const status = (e as { status?: number })?.status
    const msg = (e as Error)?.message || String(e)
    if (status === 404) {
      flash('员工闭环接口未就绪，请刷新页面或联系管理员升级服务区', false)
      return
    }
    flash(msg, false)
  } finally {
    closureBusy.value = false
  }
}

async function patchWorkflowEmployeeNodesRetry() {
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录后再重试图布对齐', false)
    return
  }
  if (!modId.value) return
  patchWorkflowBusy.value = true
  try {
    const res = await api.patchModWorkflowEmployeeNodes(modId.value)
    const patches = Array.isArray(res?.graph_patch?.patches) ? res.graph_patch.patches : []
    const errs = patches.filter((p: any) => p && typeof p.error === 'string' && p.error)
    const skips = patches.filter((p: any) => p && typeof p.skipped === 'string')
    if (errs.length) {
      flash(`修图部分失败：${errs.map((e: any) => e.error).join('；')}`, false)
    } else if (res?.employee_readiness?.ok) {
      flash('画布已对齐，员工可用性检查通过', true)
    } else {
      const g = Array.isArray(res?.employee_readiness?.gaps) ? res.employee_readiness.gaps[0] : ''
      const s0 = skips.length ? String(skips[0].skipped || '') : ''
      let msg = '已执行对齐，请查看下方各行说明'
      if (g) msg = `已执行对齐，仍有缺口：${g}`
      if (s0) msg = g ? `${msg}（${s0}）` : `已执行对齐：${s0}`
      flash(msg, false)
    }
    await reload()
  } catch (e: any) {
    flash(e?.message || String(e), false)
  } finally {
    patchWorkflowBusy.value = false
  }
}

async function registerWorkflowEmployeeCatalog(row: any) {
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录工作台后再一键登记', false)
    return
  }
  registerCatalogBusy.value = row.index
  try {
    const res = await api.registerWorkflowEmployeeCatalog(modId.value, row.index)
    const pkg = res?.package
    const pid = pkg?.id || ''
    const ver = pkg?.version || ''
    const readyRow = Array.isArray(res?.employee_readiness?.employees)
      ? res.employee_readiness.employees.find((x: any) => Number(x?.index) === Number(row.index))
      : null
    const nextGap = Array.isArray(readyRow?.gaps) && readyRow.gaps.length ? `；下一步：${readyRow.gaps[0]}` : ''
    flash(
      (pid && ver ? `已登记到本地仓库：${pid} @ ${ver}` : '已登记到本地仓库（/v1/packages）') + nextGap,
      true,
    )
    await reload()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    registerCatalogBusy.value = -1
  }
}

function goEmployeePrefill(row: any) {
  const mid = modId.value
  const wi = row.index
  const desc = row.bodyFull
    ? `声明摘要：${row.bodyFull}\n来源 Mod：${mid}（workflow_employees[${wi}]）。已带入员工制作页预填；也可在本页点「一键登记」写入 /v1/packages，或完成向导后手动登记。`
    : `来自 Mod「${mid}」的 workflow_employees[${wi}]（ID：${row.id || '—'}）。已带入员工制作页预填；也可点「一键登记」或完成向导后登记。`
  try {
    sessionStorage.setItem(
      PREFILL_KEY,
      JSON.stringify({
        modId: mid,
        workflowIndex: wi,
        workflowEmployee: row.raw && typeof row.raw === 'object' ? row.raw : {},
        name: String(row.title || '员工').slice(0, 200),
        description: desc.slice(0, 4000),
      }),
    )
  } catch {
    /* ignore */
  }
  router.push({ name: 'workbench-employee' })
}

function getWorkflowEmployeesArray() {
  const m = modData.value?.manifest
  const raw = m?.workflow_employees
  if (!Array.isArray(raw)) return []
  return raw.map((x: any) => (x && typeof x === 'object' ? { ...x } : {}))
}

function openEmployeeModal(mode: 'add' | 'edit', index = -1) {
  empModalMode.value = mode
  empModalError.value = ''
  empModalMergeHint.value = ''
  empScaffoldDone.value = false
  empScaffoldRouter.value = false
  if (mode === 'add') {
    empEditIndex.value = -1
    empDraft.value = { id: '', label: '', panel_title: '', panel_summary: '' }
  } else {
    empEditIndex.value = index
    const row = workflowEmployeesRows.value.find((r) => r.index === index)
    const o = row?.raw || {}
    empDraft.value = {
      id: typeof o.id === 'string' ? o.id : '',
      label: typeof o.label === 'string' ? o.label : '',
      panel_title: typeof o.panel_title === 'string' ? o.panel_title : '',
      panel_summary: typeof o.panel_summary === 'string' ? o.panel_summary : '',
    }
  }
  empModalOpen.value = true
}

function closeEmployeeModal() {
  empModalOpen.value = false
  empModalError.value = ''
  empModalMergeHint.value = ''
  empScaffoldDone.value = false
}

async function persistWorkflowEmployees(nextList: any[]) {
  const parsed = JSON.parse(JSON.stringify(modData.value?.manifest || {}))
  parsed.workflow_employees = nextList
  await api.putModManifest(modId.value, parsed)
  manifestSaveWarnings.value = []
  flash('员工名片已保存')
  await reload()
}

function copyMergeHint() {
  if (!empModalMergeHint.value) return
  navigator.clipboard?.writeText(empModalMergeHint.value).then(
    () => flash('已复制到剪贴板', true),
    () => flash('复制失败', false),
  )
}

async function submitEmployeeModal() {
  empModalError.value = ''
  empModalMergeHint.value = ''
  const id = empDraft.value.id.trim()
  const label = empDraft.value.label.trim()
  const panel_title = empDraft.value.panel_title.trim()
  const panel_summary = empDraft.value.panel_summary.trim()
  if (!label) {
    empModalError.value = '请填写显示名（label）'
    return
  }
  if (empModalMode.value === 'add' && !id) {
    empModalError.value = '请填写内部 ID（id）'
    return
  }
  if (empModalMode.value === 'add' && !EMP_ID_RE.test(id)) {
    empModalError.value = '内部 ID 须小写字母开头，仅含小写字母、数字、下划线、连字符（1–64 字符）'
    return
  }
  const wf = getWorkflowEmployeesArray()
  if (empModalMode.value === 'add') {
    if (wf.some((x) => String(x.id || '').trim() === id)) {
      empModalError.value = '该内部 ID 已存在'
      return
    }
  }
  empModalSaving.value = true
  try {
    if (empModalMode.value === 'add' && empScaffoldRouter.value) {
      const res = await api.scaffoldWorkflowEmployee(modId.value, {
        id,
        label,
        panel_title,
        panel_summary,
        template: 'skeleton_router',
        force_auto_merge: false,
      })
      await reload()
      if (res.merge_hint) {
        empModalMergeHint.value = String(res.merge_hint)
        empScaffoldDone.value = true
        flash(
          res.merged_blueprint
            ? '已添加员工；已尝试合并 blueprints。请查看下方合并说明，可复制给开发者。'
            : '已添加员工与占位文件；请按下方说明手动合并 blueprints。',
          true,
        )
      } else {
        flash('已添加员工并生成占位路由', true)
        closeEmployeeModal()
      }
      return
    }
    const entry = { id, label, panel_title, panel_summary }
    if (empModalMode.value === 'add') {
      wf.push(entry)
    } else {
      const idx = empEditIndex.value
      if (idx < 0 || idx >= wf.length) {
        empModalError.value = '索引无效'
        return
      }
      const prev = wf[idx] || {}
      wf[idx] = { ...prev, ...entry, id: typeof prev.id === 'string' && prev.id ? prev.id : id }
    }
    await persistWorkflowEmployees(wf)
    closeEmployeeModal()
  } catch (e) {
    empModalError.value = (e as Error)?.message || String(e)
  } finally {
    empModalSaving.value = false
  }
}

async function confirmDeleteEmployee(index: number) {
  const wf = getWorkflowEmployeesArray()
  if (index < 0 || index >= wf.length) return
  const row = wf[index]
  const name = (row && row.label) || row?.id || `第 ${index + 1} 条`
  if (!window.confirm(`确定从 manifest 中删除员工「${name}」？（不会删除已生成的 Python 文件）`)) return
  wf.splice(index, 1)
  empModalSaving.value = true
  try {
    await persistWorkflowEmployees(wf)
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    empModalSaving.value = false
  }
}

function normPath(p: unknown): string {
  return String(p || '').replace(/\\/g, '/').replace(/^\//, '')
}

const fileSet = computed(() => {
  const files = modData.value?.files
  if (!Array.isArray(files)) return new Set()
  return new Set<string>(files.map((f: unknown) => normPath(f)))
})

const scaffoldEnvHint = computed(() => '')

const sortedFiles = computed(() => {
  const files = modData.value?.files
  if (!Array.isArray(files)) return []
  return [...files].map(normPath).sort((a, b) => a.localeCompare(b))
})

const backendEntryRel = computed(() => {
  const m = modData.value?.manifest
  const entry = typeof m?.backend?.entry === 'string' ? m.backend.entry : 'blueprints'
  const stem = entry.replace(/\.py$/i, '')
  return `backend/${stem}.py`
})

const checklist = computed(() => {
  const fs = fileSet.value
  const entryPath = backendEntryRel.value
  const rows = [
    { key: 'manifest', label: 'manifest.json', ok: fs.has('manifest.json') },
    { key: 'init', label: 'backend/__init__.py', ok: fs.has('backend/__init__.py') },
    { key: 'entry', label: entryPath, ok: fs.has(entryPath) },
    { key: 'routes', label: 'frontend/routes.js', ok: fs.has('frontend/routes.js') },
  ]
  return rows
})

const artifactNote = computed(() => {
  const art = modData.value?.manifest?.artifact || modData.value?.manifest?.kind
  if (art === 'employee_pack') return '类型：employee_pack'
  if (art === 'bundle') return '类型：bundle'
  return ''
})

let flashTimer: ReturnType<typeof setTimeout> | null = null

function flash(msg: string, ok = true, durationMs = 5000) {
  if (flashTimer) clearTimeout(flashTimer)
  message.value = msg
  messageOk.value = ok
  flashTimer = setTimeout(() => {
    message.value = ''
    flashTimer = null
  }, durationMs)
}

function openWorkflowSandboxDecompose(row: any) {
  const wid = row.linkedWorkflowId
  if (!wid) {
    flash('当前员工条目未声明 workflow_id，请先在 manifest 中关联 MODstore 工作流', false)
    return
  }
  router.push({ name: 'workbench-workflow', query: { edit: String(wid), tab: 'sandbox' } })
}

async function loadLinkableWorkflows() {
  try {
    linkableWorkflows.value = (await api.listWorkflows()) || []
  } catch {
    linkableWorkflows.value = []
  }
}

async function applyWorkflowLinkToRow(row: any) {
  const wid = Number(linkPick[row.index])
  if (!modId.value || !Number.isFinite(wid) || wid <= 0) {
    flash('请在下拉框中选择一个工作流', false)
    return
  }
  linkWorkflowBusy.value = true
  try {
    const res = await api.modWorkflowLink(modId.value, {
      workflow_id: wid,
      workflow_index: row.index,
    })
    const mw = Array.isArray(res?.manifest_warnings) ? res.manifest_warnings : []
    if (mw.length) manifestSaveWarnings.value = mw
    flash('已写入 workflow_id，可点「拆解与沙盒测试」', true)
    await reload()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    linkWorkflowBusy.value = false
  }
}

function formatSnapTime(ts: unknown): string {
  const n = Number(ts)
  if (!Number.isFinite(n) || n <= 0) return '—'
  try {
    return new Date(n * 1000).toLocaleString()
  } catch {
    return String(ts)
  }
}

async function refreshSnapshots() {
  if (!modId.value) return
  snapshotsLoadErr.value = ''
  try {
    const res = await api.listModSnapshots(modId.value)
    const rows = Array.isArray(res?.snapshots) ? res.snapshots : Array.isArray(res) ? res : []
    snapshotsRows.value = rows
  } catch (e: unknown) {
    snapshotsRows.value = []
    const status = (e as { status?: number })?.status
    const msg = (e as Error)?.message || String(e)
    // 旧版后端未注册 snapshots 路由时勿阻断制作页
    if (status === 404 && /not found/i.test(msg)) return
    snapshotsLoadErr.value = msg
  }
}

async function captureSnapshotManual() {
  if (!modId.value) return
  snapshotBusy.value = true
  try {
    await api.captureModSnapshot(modId.value, snapshotLabelDraft.value.trim())
    snapshotLabelDraft.value = ''
    flash('已创建快照', true)
    await refreshSnapshots()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    snapshotBusy.value = false
  }
}

async function restoreSnapshot(snapId: string) {
  if (!modId.value || !snapId) return
  if (!window.confirm('将用该快照覆盖当前 manifest.json，确定继续？')) return
  snapshotBusy.value = true
  try {
    await api.restoreModSnapshot(modId.value, snapId)
    flash('已从快照恢复 manifest', true)
    await reload()
    await refreshSnapshots()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    snapshotBusy.value = false
  }
}

async function bumpManifestPatch() {
  if (!modId.value) return
  snapshotBusy.value = true
  try {
    const res = await api.bumpModManifestPatchVersion(modId.value)
    const w = Array.isArray(res?.warnings) ? res.warnings : []
    if (w.length) manifestSaveWarnings.value = w
    flash(`manifest 版本已更新为 ${res?.manifest?.version || '新版本'}`, true)
    await reload()
    await refreshSnapshots()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    snapshotBusy.value = false
  }
}

function goRepo() {
  router.push({ name: 'workbench-repository' })
}

async function refreshSummary() {
  if (!modId.value) return
  loadingSummary.value = true
  try {
    summary.value = await api.getModAuthoringSummary(modId.value)
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    loadingSummary.value = false
  }
}

async function loadAiBlueprint() {
  aiBlueprint.value = null
  if (!modId.value) return
  if (!fileSet.value.has('config/ai_blueprint.json')) return
  try {
    const res = await api.getModFile(modId.value, 'config/ai_blueprint.json')
    const parsed = JSON.parse(String(res?.content || '{}'))
    aiBlueprint.value = parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    aiBlueprint.value = null
  }
}

async function reload() {
  loadError.value = ''
  loading.value = true
  manifestSaveWarnings.value = []
  fileWarnings.value = []
  try {
    const [detail, sum] = await Promise.all([
      api.getMod(modId.value),
      api.getModAuthoringSummary(modId.value).catch(() => null),
    ])
    modData.value = detail
    summary.value = sum
    manifestText.value = JSON.stringify(detail.manifest || {}, null, 2)
    await loadAiBlueprint()
    void loadLinkableWorkflows()
    void refreshSnapshots()
    if (!selectedPath.value || !fileSet.value.has(normPath(selectedPath.value))) {
      selectedPath.value = ''
      fileContent.value = ''
    }
  } catch (e) {
    modData.value = null
    summary.value = null
    loadError.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
}

async function saveManifest(opts?: { successMessage?: string; flashDurationMs?: number }) {
  let parsed
  try {
    parsed = JSON.parse(manifestText.value)
  } catch (e) {
    flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
    return
  }
  savingManifest.value = true
  manifestSaveWarnings.value = []
  try {
    try {
      await api.captureModSnapshot(modId.value, `保存前 ${new Date().toISOString().slice(0, 19)}`)
    } catch {
      /* 快照失败不阻断保存 */
    }
    const res = await api.putModManifest(modId.value, parsed)
    manifestSaveWarnings.value = Array.isArray(res.warnings) ? res.warnings : []
    flash(opts?.successMessage ?? 'manifest 已保存', true, opts?.flashDurationMs ?? 5000)
    await reload()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    savingManifest.value = false
  }
}

async function regenerateFrontend() {
  if (!modId.value) return
  frontendBusy.value = true
  try {
    const res = await api.regenerateModFrontend(modId.value, frontendBrief.value.trim())
    const menuN = manifestSidebarStatus.value.menuCount
    flash(`前端已生成（菜单 ${menuN} 项）`, true, 4000)
    if (res.frontend_spec && typeof res.frontend_spec === 'object') {
      aiBlueprint.value = {
        ...(aiBlueprint.value && typeof aiBlueprint.value === 'object' ? aiBlueprint.value : {}),
        frontend_app: res.frontend_spec,
      }
    }
    selectedPath.value = 'frontend/views/HomeView.vue'
    await reload()
    if (fileSet.value.has(selectedPath.value)) {
      await loadSelectedFile()
    }
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    frontendBusy.value = false
  }
}

async function loadSelectedFile() {
  const p = normPath(selectedPath.value)
  if (!p) return
  loadingFile.value = true
  fileWarnings.value = []
  try {
    const res = await api.getModFile(modId.value, p)
    fileContent.value = res.content ?? ''
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    loadingFile.value = false
  }
}

function onPathSelect() {
  fileContent.value = ''
  fileWarnings.value = []
}

async function saveFile() {
  const p = normPath(selectedPath.value)
  if (!p) return
  savingFile.value = true
  fileWarnings.value = []
  try {
    const res = await api.putModFile(modId.value, p, fileContent.value)
    fileWarnings.value = Array.isArray(res.manifest_warnings) ? res.manifest_warnings : []
    flash('文件已保存')
    await reload()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    savingFile.value = false
  }
}

watch(
  modId,
  (id) => {
    if (!id) {
      loadError.value = '缺少 modId'
      loading.value = false
      modData.value = null
      return
    }
    reload()
  },
  { immediate: true },
)

watch(
  () => [String(route.query.mode || '').toLowerCase(), modId.value],
  ([mode]) => {
    if (mode === 'edit' && modId.value) tab.value = 'snapshots'
  },
  { immediate: true },
)
  const nameDraft = ref('')
  watch(
    () => String((modData.value as LooseRecord | null)?.manifest?.name || modId.value || '').trim(),
    (v) => {
      nameDraft.value = v
    },
    { immediate: true },
  )

  const descriptionDraft = ref('')
  watch(
    () => modDescriptionLine.value,
    (v) => {
      descriptionDraft.value = v
    },
    { immediate: true },
  )

  async function saveDescriptionFromWizard() {
    const name = nameDraft.value.trim()
    const desc = descriptionDraft.value.trim()
    if (!name) {
      flash('请填写 Mod 名称', false)
      return false
    }
    if (!desc) {
      flash('请填写一句话介绍', false)
      return false
    }
    let parsed: LooseRecord
    try {
      parsed = JSON.parse(manifestText.value) as LooseRecord
    } catch (e) {
      flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
      return false
    }
    parsed.name = name
    parsed.description = desc
    const fe = parsed.frontend
    if (fe && typeof fe === 'object' && Array.isArray((fe as LooseRecord).menu)) {
      const menu = (fe as LooseRecord).menu as LooseRecord[]
      if (menu[0] && typeof menu[0] === 'object') {
        menu[0].label = name
      }
    }
    manifestText.value = JSON.stringify(parsed, null, 2)
    await saveManifest({ successMessage: '名称与介绍已保存' })
    return true
  }

  return {
    EXPERT_TABS,
    tab,
    loading,
    loadError,
    modData,
    summary,
    aiBlueprint,
    manifestText,
    manifestSaveWarnings,
    message,
    messageOk,
    savingManifest,
    selectedPath,
    fileContent,
    loadingFile,
    savingFile,
    fileWarnings,
    loadingSummary,
    frontendBusy,
    frontendBrief,
    snapshotsRows,
    snapshotsLoadErr,
    snapshotBusy,
    snapshotLabelDraft,
    modId,
    modDescriptionLine,
    nameDraft,
    descriptionDraft,
    saveDescriptionFromWizard,
    employeeReadiness,
    employeeReadinessGaps,
    readinessSummaryLabel,
    workflowEmployeesRows,
    frontendConfigPath,
    frontendEntryPath,
    frontendSpecTitle,
    frontendSpecPreview,
    suggestedSkills,
    suggestedPricing,
    refinePromptLoading,
    refinePromptError,
    refinePromptDiff,
    handleRefineSystemPrompt,
    applyPricingSuggestion,
    industryCard,
    industryPresetList,
    selectedIndustryPreset,
    selectedIndustryScenario,
    applyIndustryPresetToManifest,
    manifestSidebarStatus,
    apiSummary,
    workflowSandboxRows,
    workflowSandboxOk,
    modSandboxChecks,
    modSandboxOk,
    vibeHealReport,
    vibeIndexReport,
    linkableWorkflows,
    linkPick,
    linkWorkflowBusy,
    registerCatalogBusy,
    patchWorkflowBusy,
    closureBusy,
    empModalOpen,
    empModalMode,
    empEditIndex,
    empDraft,
    empScaffoldRouter,
    empModalSaving,
    empModalError,
    empModalMergeHint,
    empScaffoldDone,
    empPickOpen,
    empPickRows,
    empPickLoading,
    empPickError,
    empPickSaving,
    openEmployeePickModal,
    closeEmployeePickModal,
    goMyEmployees,
    confirmPickEmployee,
    runWorkflowEmployeeClosure,
    patchWorkflowEmployeeNodesRetry,
    registerWorkflowEmployeeCatalog,
    goEmployeePrefill,
    openEmployeeModal,
    closeEmployeeModal,
    submitEmployeeModal,
    copyMergeHint,
    confirmDeleteEmployee,
    sortedFiles,
    scaffoldEnvHint,
    checklist,
    artifactNote,
    flash,
    openWorkflowSandboxDecompose,
    applyWorkflowLinkToRow,
    formatSnapTime,
    refreshSnapshots,
    captureSnapshotManual,
    restoreSnapshot,
    bumpManifestPatch,
    goRepo,
    refreshSummary,
    reload,
    saveManifest,
    regenerateFrontend,
    loadSelectedFile,
    onPathSelect,
    saveFile,
    fileSet,
    backendEntryRel,
    getWorkflowEmployeesArray,
    persistWorkflowEmployees,
  }
}
