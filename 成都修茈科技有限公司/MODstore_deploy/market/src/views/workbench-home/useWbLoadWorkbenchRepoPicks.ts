import { ref, computed } from 'vue'
import { api } from '../../api'
import { computeOrchProgress } from '../../utils/orchestrationSteps'
import type { OrchStepLike } from '../../utils/orchestrationSteps'
import type { useWbLoadDirectEmployeeOptions } from './useWbLoadDirectEmployeeOptions'
import type { WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 2499–2503, 2528–2528, 2529–2529 …）；逐字迁移，行为不变。
export function useWbLoadWorkbenchRepoPicks(ctx: ReturnType<typeof useWbLoadDirectEmployeeOptions>) {
  const {
    router, route, draft, displayName, pendingHandoff, makeCompletionResult,
    finalizeLoading, orchestrationSession, orchPhase, orchestrationEtaSeconds, orchestrationEtaReason, __wbState,
    orchTimingStartMs, orchElapsedTick, workflowLinkOffer, planSession, planReplyDraft, knowledgeUploading,
    CANVAS_SKILL_INTENT, isCanvasSkillIntent, composerIntent, modFrontendEnabled, directAttachedFiles, directMessages,
    voiceMessages, voiceTitle, requireLoginForWorkbenchUse, llmCatalog, llmCatalogLoading, llmCatalogError,
    selectedProvider, selectedModel, modelMode, llmDdOpen, intentGuideCollapsed, catalogEmployeeRows,
    catalogModRows, pickEmployeeKey, pickModId, loadDirectEmployeeOptions,
  } = ctx

const llmMobilePickerSummary = computed(() => {
  if (modelMode.value === 'auto') return '模型 · Auto'
  const model = selectedModel.value || '未选'
  return `模型 · ${currentProviderLabel.value} / ${model}`
})
const hasModRepo = computed(() => hasWorkflow.value)
const hasEmployeeIntent = computed(() => hasWorkflow.value)
function isMakeToolbarIntentActive(intent: string): boolean {
  if (intent === 'employee') {
    return hasWorkflow.value && composerIntent.value === 'employee'
  }
  if (intent === CANVAS_SKILL_INTENT) {
    return hasWorkflow.value && composerIntent.value === CANVAS_SKILL_INTENT
  }
  return composerIntent.value === intent
}
function buildVoiceRouteContext() {
  const ps = planSession.value
  const lastAssistant = [...voiceMessages.value].reverse().find((m) => m.role === 'assistant')
  return {
    orchPhase: orchPhase.value,
    hasPlanSession: Boolean(ps),
    hasPendingHandoff: Boolean(pendingHandoff.value),
    canRunOrch: canRunOrchestration.value,
    planSessionPhase: ps?.phase,
    planIntentKey: ps?.intentKey,
    orchestrating:
      orchPhase.value === 'running' ||
      orchPhase.value === 'estimating' ||
      finalizeLoading.value,
    composerIntent: composerIntent.value,
    pendingHandoff: Boolean(pendingHandoff.value),
    finalizeLoading: finalizeLoading.value,
    voiceTitle: ps?.summaryTitle || ps?.intentTitle || '',
    checklistLineCount: ps?.checklistLines?.length ?? 0,
    lastAssistantSnippet: String(lastAssistant?.content || '').slice(0, 280),
  }
}
const intentRepoPickShow = computed(() => {
  if (!hasWorkflow.value || planSession.value) return false
  return composerIntent.value === 'employee' || composerIntent.value === 'mod'
})
const showIntentGuide = computed(() => !intentRepoPickShow.value || !intentGuideCollapsed.value)
async function loadWorkbenchRepoPicks() {
  catalogEmployeeRows.value = []
  catalogModRows.value = []
  if (!localStorage.getItem('modstore_token')) return
  try {
    const r = await api.listV1Packages('employee_pack', '', 80, 0)
    const rows = []
    for (const p of r.packages || []) {
      const id = String(p.id || '').trim()
      const ver = String(p.version || '').trim()
      if (!id || !ver) continue
      const ch = String(p.release_channel || 'stable').toLowerCase()
      const displayName = String(p.name || id).trim() || id
      const description = typeof p.description === 'string' ? p.description : ''
      const industry = typeof p.industry === 'string' && p.industry.trim() ? p.industry.trim() : ''
      const artifact = String(p.artifact || 'employee_pack').toLowerCase()
      const probe = typeof p.probe_mod_id === 'string' && p.probe_mod_id.trim() ? p.probe_mod_id.trim() : ''
      rows.push({
        k: `${id}@${ver}`,
        id,
        ver,
        displayName,
        label: `${p.name || id} · ${ver}${ch === 'draft' ? '（测试）' : ''}`,
        description,
        industry,
        artifact,
        release_channel: ch,
        probe_mod_id: probe,
      })
    }
    catalogEmployeeRows.value = rows
  } catch {
    catalogEmployeeRows.value = []
  }
  try {
    const m = await api.listMods()
    catalogModRows.value = Array.isArray(m?.data) ? m.data : []
  } catch {
    catalogModRows.value = []
  }
  await loadDirectEmployeeOptions()
}
function _goEditEmployeeFromPick() {
  if (!requireLoginForWorkbenchUse()) return
  const v = pickEmployeeKey.value
  if (!v) return
  const at = v.lastIndexOf('@')
  if (at <= 0) return
  const id = v.slice(0, at)
  const ver = v.slice(at + 1)
  router.push({ name: 'workbench-employee', query: { edit_pkg: id, edit_ver: ver } })
}
function _goEditModFromPick() {
  if (!requireLoginForWorkbenchUse()) return
  const id = (pickModId.value || '').trim()
  if (!id) return
  router.push({ name: 'mod-authoring', params: { modId: id }, query: { mode: 'edit' } })
}
/** 侧栏与输入脚「当前」主标题：{name} Skill 组 / Mod / AI 员工 */
const _composerMainTitle = computed(() => {
  if (workflowLinkOffer.value?.workflowName) {
    return `${workflowLinkOffer.value.workflowName} Skill 组`
  }
  const ph = pendingHandoff.value
  if (isCanvasSkillIntent(ph?.intentKey)) {
    const n = (ph?.workflowName || '').trim()
    if (n) return `${n} Skill 组`
  }
  if (ph?.intentKey === 'mod') {
    const n = (ph.suggestedModId || '').trim()
    if (n) return `${n} Mod`
  }
  if (ph?.intentKey === 'employee') {
    const d = (ph.description || '').trim().split('\n')[0].trim().slice(0, 36)
    if (d) return `${d} AI 员工`
  }
  const k = composerIntent.value
  if (k === 'mod') return '做 Mod'
  if (k === 'employee') return '做员工'
  return '生成 Skill 组'
})
const handoffDescLabel = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') return 'Mod 需求描述'
  if (k === 'employee') return '员工能力描述'
  return 'Skill 组描述'
})
const orchestrationButtonLabel = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') return '开始生成 Mod'
  if (k === 'employee') return '开始生成员工包'
  const files = pendingHandoff.value?.files
  if (isCanvasSkillIntent(k) && Array.isArray(files) && files.length > 0) {
    return '开始处理附件（AI 生成 Python 脚本）'
  }
  if (isCanvasSkillIntent(k)) return '开始生成 Skill 组并校验'
  return '开始创建并校验'
})
const orchestrationButtonPendingLabel = computed(() => {
  if (!finalizeLoading.value) return orchestrationButtonLabel.value
  if (orchPhase.value === 'estimating') return '估算用时…'
  return '执行中…'
})
const makeHasActiveTask = computed(() =>
  Boolean(
    planSession.value ||
      pendingHandoff.value ||
      workflowLinkOffer.value ||
      finalizeLoading.value ||
      makeCompletionResult.value ||
      orchestrationSession.value?.steps?.length,
  ),
)
const _makeComposerRows = computed(() => {
  if (planSession.value?.phase === 'chat') return 2
  return makeHasActiveTask.value ? 1 : 4
})
const orchestrationProgress = computed(() =>
  computeOrchProgress(orchestrationSession.value?.steps),
)
const orchQualityReport = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return []
  const qr = (art as Record<string, unknown>).quality_report as Record<string, unknown> | unknown[] | undefined
  if (Array.isArray(qr)) {
    return qr as Array<{
      check?: string
      ok?: boolean | null
      note?: string
      critical?: boolean
    }>
  }
  if (qr && typeof qr === 'object' && Array.isArray((qr as Record<string, unknown>).items)) {
    return (qr as Record<string, unknown>).items as Array<{ check?: string; ok?: boolean | null; note?: string; critical?: boolean }>
  }
  return []
})
const orchQualityMeta = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  const qr = (art as Record<string, unknown>).quality_report as Record<string, unknown> | undefined
  if (!qr || typeof qr !== 'object' || Array.isArray(qr)) return null
  return {
    score: qr.score as number | undefined,
    runnable: qr.runnable as boolean | undefined,
    criticalFailed: qr.critical_failed as boolean | undefined,
    pipelineLabel: String(qr.pipeline_label || ''),
  }
})
/** Phase A：vibecoding 轮次 / 黄金 parity / 领域冒烟（编排 artifact） */
const orchVibecodingMeta = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  const a = art as Record<string, unknown>
  const rt = a.runtime_generation as Record<string, unknown> | undefined
  const gc = a.golden_comparison as Record<string, unknown> | undefined
  const ds = a.domain_smoke as Record<string, unknown> | undefined
  if (!rt && !gc && !ds) return null
  return {
    source: rt ? String(rt.source || '') : '',
    round: rt?.round as number | undefined,
    generated: rt?.generated === true,
    parity: gc?.parity_score as number | undefined,
    goldenPassed: gc?.passed === true,
    smokeOk: ds?.ok as boolean | undefined,
    diffCount: Array.isArray(gc?.diff_items) ? (gc.diff_items as unknown[]).length : 0,
  }
})
function formatWallClockSec(sec: unknown): string {
  const s = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m >= 60) {
    const h = Math.floor(m / 60)
    const mm = m % 60
    return `${h}:${String(mm).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  }
  if (m === 0) return `${r}秒`
  return `${m}分${String(r).padStart(2, '0')}秒`
}
function stopOrchestrationElapsedTicker() {
  if (__wbState.orchElapsedTimer != null) {
    clearInterval(__wbState.orchElapsedTimer)
    __wbState.orchElapsedTimer = null
  }
}
function startOrchestrationElapsedTicker() {
  stopOrchestrationElapsedTicker()
  orchElapsedTick.value = 0
  __wbState.orchElapsedTimer = setInterval(() => {
    orchElapsedTick.value += 1
  }, 500)
}
const ORCH_ESTIMATE_SYSTEM = [
  '你是「工作台异步编排」的 wall-clock 耗时估算助手。用户即将启动一次服务端多步任务（可能含多次 LLM、写盘、工作流/沙箱等）。',
  '请只根据 intent、需求摘要与清单规模，推断从「开始执行」到「全部完成」的总秒数；不得照抄示例数字，须结合复杂度自行推理。',
  '只输出一个 JSON 对象，不要用 markdown 代码围栏，不要其它文字。',
  '字段：estimated_seconds（整数，通常 120～3600，极端不超过 7200），confidence（"low"|"medium"|"high"），one_line_reason（一句中文，≤80 字）。',
].join('')
function parseOrchestrationEtaFromLlmText(text: unknown): { seconds: number | null; reason: string } {
  let s = String(text || '').trim()
  if (!s) return { seconds: null, reason: '' }
  if (s.startsWith('```')) {
    s = s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim()
  }
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start < 0 || end <= start) return { seconds: null, reason: '' }
  try {
    const o = JSON.parse(s.slice(start, end + 1))
    const n = Number(o.estimated_seconds)
    if (!Number.isFinite(n)) return { seconds: null, reason: String(o.one_line_reason || '').trim().slice(0, 120) }
    const sec = Math.round(Math.max(30, Math.min(n, 7200)))
    return {
      seconds: sec,
      reason: String(o.one_line_reason || '').trim().slice(0, 120),
    }
  } catch {
    return { seconds: null, reason: '' }
  }
}
/** 模型未返回 estimated_seconds 时，用清单规模与意图粗估总秒数，避免「预计 —」不可读 */
function fallbackOrchestrationSecondsEstimate(ctx: {
  intent: string
  checklistLen: number
  generateFrontend?: boolean
  employeeTarget?: string
  scriptFileCount?: number
}): number {
  let n = 150
  const cl = Math.max(0, Math.floor(Number(ctx.checklistLen) || 0))
  n += cl * 95
  const intent = String(ctx.intent || CANVAS_SKILL_INTENT)
  if (intent === 'mod') {
    n += 260
    if (ctx.generateFrontend) n += 480
  } else if (intent === 'employee') {
    n += 320
    if (String(ctx.employeeTarget || '').includes('pack_plus')) n += 260
  } else {
    n += 200
  }
  const sf = Math.max(0, Math.floor(Number(ctx.scriptFileCount) || 0))
  n += sf * 160
  return Math.round(Math.min(7200, Math.max(120, n)))
}
const orchestrationEtaDisplay = computed(() => {
  if (!finalizeLoading.value) return '—'
  if (orchPhase.value === 'estimating') return '模型推算中…'
  orchElapsedTick.value
  let sec = orchestrationEtaSeconds.value
  const h = pendingHandoff.value
  if ((sec == null || !Number.isFinite(sec)) && orchPhase.value === 'running' && h) {
    const scriptFiles = isCanvasSkillIntent(h.intentKey) && Array.isArray(h.files) ? h.files : []
    sec = fallbackOrchestrationSecondsEstimate({
      intent: String(h.intentKey || CANVAS_SKILL_INTENT),
      checklistLen: Array.isArray(h.executionChecklist) ? h.executionChecklist.length : 0,
      generateFrontend: h.intentKey === 'mod' ? modFrontendEnabled.value : false,
      employeeTarget: h.intentKey === 'employee' ? String(h.employeeTarget || '').trim() : '',
      scriptFileCount: scriptFiles.length,
    })
  }
  if (sec == null || !Number.isFinite(sec)) {
    return orchestrationEtaReason.value
      ? `未算出数值（${orchestrationEtaReason.value}）`
      : '未算出数值'
  }
  const totalLabel = `总估约 ${formatWallClockSec(sec)}`
  const t0 = orchTimingStartMs.value
  if (t0 == null) return `${totalLabel}（即将计时）`
  const elapsed = (Date.now() - t0) / 1000
  const rem = sec - elapsed
  if (rem >= 20) return `${totalLabel} · 剩余约 ${formatWallClockSec(rem)}`
  if (rem >= 0) return `${totalLabel} · 收尾中`
  return `${totalLabel} · 已超过估算，仍在执行`
})
const orchestrationTimingTooltip = computed(() => {
  if (!finalizeLoading.value) return ''
  const r = String(orchestrationEtaReason.value || '').trim()
  return r || '总时长为模型推算或按步骤量粗估；剩余时间按总估与已用时间相减。'
})
const orchestrationElapsedDisplay = computed(() => {
  orchElapsedTick.value
  if (!finalizeLoading.value) return '—'
  if (orchPhase.value === 'estimating') return '—'
  const t0 = orchTimingStartMs.value
  if (t0 == null) return '—'
  return formatWallClockSec((Date.now() - t0) / 1000)
})
const canRunOrchestration = computed(() => {
  const h = pendingHandoff.value
  if (!h?.description?.trim()) return false
  if (isCanvasSkillIntent(h.intentKey)) return Boolean(h.workflowName?.trim())
  return true
})
const handoffFootNote = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') {
    return '生成成功后进入 Mod 制作页。页面会区分“名片已生成”和“员工可工作”：未登记员工包、未绑定工作流或未真实执行都会列为缺口。'
  }
  if (k === 'employee') {
    const isRealSkill = pendingHandoff.value?.employeeTarget === 'pack_plus_workflow'
    if (isRealSkill) {
      return '员工包已生成真实 Python 脚本并注册为可执行 Skill，画布每个节点都对应已沙箱校验的代码；上架请到「员工制作」。'
    }
    return '员工包写入你的本地库；上架请到「员工制作」上传。商店执行器以已上架包为准。'
  }
  if (Array.isArray(pendingHandoff.value?.files) && pendingHandoff.value.files.length > 0) {
    return '已选择附件：将生成可复用的「脚本工作流」，成功后自动进入沙箱调试页；你可以继续上传同类 Excel 文件验证脚本输出。若要生成节点与连线的流程图，请先移除附件再提交。'
  }
  return '创建并校验成功后进入画布编辑 Skill 组；尚无节点时跳过拓扑沙盒。'
})
const handoffAssetNote = computed(() => {
  const files = pendingHandoff.value?.files
  if (!Array.isArray(files) || !files.length) return ''
  return `已附带 ${files.length} 个资产`
})
const hasRepo = computed(() => router.hasRoute('workbench-repository'))
const hasWorkflow = computed(() => router.hasRoute('workbench-workflow'))
/** Teleport 到 body；keep-alive 下切到统一工作台等路由时首页仍缓存，需按当前路由隐藏 FAB */
const _showDirectTierFab = computed(() => {
  if (!hasWorkflow.value) return false
  const n = String(route.name || '')
  return n === 'home' || n === 'workbench-home'
})
const _hasScriptWorkflowRoute = computed(() => router.hasRoute('script-workflow-new'))
const hasEmployee = computed(() => router.hasRoute('workbench-employee'))
const _hasPlans = computed(() => router.hasRoute('plans'))
/** 一档有聊天记录时默认锁定挡位切换，需用户显式解锁（同一会话内保持） */
const gearNavUserUnlocked = ref(false)
const _gearNavHardLocked = computed(
  () => Boolean(hasWorkflow.value && directMessages.value.length && !gearNavUserUnlocked.value),
)
function _unlockGearNav() {
  gearNavUserUnlocked.value = true
}
const greetingLine = computed(() => {
  const n = displayName.value.trim()
  if (!n) return ''
  return `你好，${n}`
})
const placeholder = computed(() => {
  if (composerIntent.value === 'mod') return '描述你想做的 Mod…'
  if (composerIntent.value === 'employee') return '描述员工职责…'
  return '描述你的想法…'
})
/** 「做」模式主输入：无规划或与助手对话时合并到底栏，避免双文本框 */
const makeComposerInput = computed({
  get() {
    if (planSession.value?.phase === 'chat') return planReplyDraft.value
    return draft.value
  },
  set(v: string) {
    if (planSession.value?.phase === 'chat') {
      planReplyDraft.value = v
    } else {
      draft.value = v
    }
  },
})
const _makeComposerInputLabel = computed(() =>
  planSession.value?.phase === 'chat' ? '补充或追问' : '描述想法',
)
const makeComposerPlaceholder = computed(() =>
  planSession.value?.phase === 'chat' ? '补充…' : placeholder.value,
)
const composerSendDisabled = computed(() => {
  if (knowledgeUploading.value) return true
  const ps = planSession.value
  if (ps?.phase === 'chat') {
    return ps.loading || !String(planReplyDraft.value || '').trim()
  }
  if (ps) return true
  if (!hasWorkflow.value) return true
  const text = String(draft.value || '').trim()
  const uploading = directAttachedFiles.value.some((f) => f.status === 'uploading')
  if (uploading) return true
  return !text && !directAttachedFiles.value.length
})
const currentLlmBlock = computed(() => {
  if (!llmCatalog.value?.providers) return null
  return llmCatalog.value.providers.find((p: WorkbenchStateRecord) => p.provider === selectedProvider.value) || null
})
const currentProviderLabel = computed(() => {
  const list = llmCatalog.value?.providers
  if (!Array.isArray(list)) return '厂商'
  const b = list.find((p: WorkbenchStateRecord) => p.provider === selectedProvider.value)
  const lab = typeof b?.label === 'string' ? b.label.trim() : ''
  const id = typeof b?.provider === 'string' ? b.provider.trim() : ''
  return lab || id || '厂商'
})
const modelModeHint = computed(() => {
  if (modelMode.value === 'auto') {
    return 'Auto：系统将根据任务自动选择合适模型'
  }
  if (selectedModel.value) {
    return `自选：${currentProviderLabel.value} · ${selectedModel.value}`
  }
  return '自选：请选择厂商与模型'
})
const modelPickerEnabled = computed(() => {
  const block = currentLlmBlock.value
  return Boolean(block && Array.isArray(block.models) && block.models.length)
})
function categoryLabel(cat: string): string {
  return llmCatalog.value?.category_labels?.[cat] || cat
}
function modelsForWorkbenchCategory(cat: string): WorkbenchStateRecord[] {
  const block = currentLlmBlock.value
  const detailed = block?.models_detailed
  if (detailed && detailed.length) {
    return detailed.filter((r: WorkbenchStateRecord) => r.category === cat)
  }
  if (cat === 'llm' && block?.models?.length) {
    return block.models.map((id: string) => ({ id, category: 'llm' }))
  }
  return []
}
function syncManualSelectionFromPreferences() {
  const res = llmCatalog.value
  if (!res?.providers?.length) return
  const pref = res.preferences || {}
  let p = pref.provider || 'openai'
  if (!res.providers.some((x: WorkbenchStateRecord) => x.provider === p)) {
    p = res.providers[0]?.provider || 'openai'
  }
  selectedProvider.value = p
  const block = res.providers.find((x: WorkbenchStateRecord) => x.provider === p)
  const mids = block?.models || []
  let m = pref.model || ''
  if (!m || !mids.includes(m)) m = mids[0] || ''
  selectedModel.value = m
}
async function loadLlmCatalogForWorkbench() {
  if (!localStorage.getItem('modstore_token')) return
  llmCatalogLoading.value = true
  llmCatalogError.value = ''
  try {
    const res = await api.llmCatalog(false)
    llmCatalog.value = res
    syncManualSelectionFromPreferences()
  } catch (e: unknown) {
    llmCatalog.value = null
    llmCatalogError.value = e instanceof Error ? e.message : String(e)
  } finally {
    llmCatalogLoading.value = false
  }
}
function onWorkbenchProviderChange() {
  const block = currentLlmBlock.value
  const mids = block?.models || []
  selectedModel.value = mids[0] || ''
}
function toggleLlmDd(which: 'provider' | 'model' | 'directProvider' | 'directModel'): void {
  llmDdOpen.value = llmDdOpen.value === which ? null : which
}
function pickProvider(p: unknown): void {
  if (typeof p !== 'string' || !p) return
  selectedProvider.value = p
  onWorkbenchProviderChange()
  llmDdOpen.value = null
}
function pickModel(id: unknown): void {
  if (typeof id !== 'string' || !id) return
  selectedModel.value = id
  llmDdOpen.value = null
}
function onLlmDocPointerDown(ev: PointerEvent): void {
  if (!llmDdOpen.value) return
  const t = ev.target as Element | null
  if (t && typeof t.closest === 'function' && t.closest('.wb-llm-dd')) return
  llmDdOpen.value = null
}
function onLlmEscape(ev: KeyboardEvent): void {
  if (ev.key === 'Escape') llmDdOpen.value = null
}
function _orchStepClass(st: OrchStepLike): Record<string, boolean> {
  return {
    'wb-step--done': st.status === 'done',
    'wb-step--running': st.status === 'running',
    'wb-step--error': st.status === 'error',
    'wb-step--pending': st.status === 'pending',
    'wb-step--skipped': st.status === 'skipped',
  }
}

  return {
    ...ctx, llmMobilePickerSummary, hasModRepo, hasEmployeeIntent, isMakeToolbarIntentActive,
    buildVoiceRouteContext, intentRepoPickShow, showIntentGuide, loadWorkbenchRepoPicks, _goEditEmployeeFromPick,
    _goEditModFromPick, _composerMainTitle, handoffDescLabel, orchestrationButtonLabel, orchestrationButtonPendingLabel,
    makeHasActiveTask, _makeComposerRows, orchestrationProgress, orchQualityReport, orchQualityMeta,
    orchVibecodingMeta, formatWallClockSec, stopOrchestrationElapsedTicker, startOrchestrationElapsedTicker, ORCH_ESTIMATE_SYSTEM,
    parseOrchestrationEtaFromLlmText, fallbackOrchestrationSecondsEstimate, orchestrationEtaDisplay, orchestrationTimingTooltip, orchestrationElapsedDisplay,
    canRunOrchestration, handoffFootNote, handoffAssetNote, hasRepo, hasWorkflow,
    _showDirectTierFab, _hasScriptWorkflowRoute, hasEmployee, _hasPlans, gearNavUserUnlocked,
    _gearNavHardLocked, _unlockGearNav, greetingLine, placeholder, makeComposerInput,
    _makeComposerInputLabel, makeComposerPlaceholder, composerSendDisabled, currentLlmBlock, currentProviderLabel,
    modelModeHint, modelPickerEnabled, categoryLabel, modelsForWorkbenchCategory, syncManualSelectionFromPreferences,
    loadLlmCatalogForWorkbench, onWorkbenchProviderChange, toggleLlmDd, pickProvider, pickModel,
    onLlmDocPointerDown, onLlmEscape, _orchStepClass,
  }
}

export type useWbLoadWorkbenchRepoPicksBinds = ReturnType<typeof useWbLoadWorkbenchRepoPicks>
