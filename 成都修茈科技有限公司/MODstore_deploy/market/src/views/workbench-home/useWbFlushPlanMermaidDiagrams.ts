import { ref, computed, nextTick } from 'vue'
import { api } from '../../api'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'
import { sanitizeMermaidSource, friendlyMermaidRenderError } from '../../utils/mermaidSanitize'
import { stripInternalMarkers } from '../../utils/lightMarkdown'
import { showAppToast } from '../../composables/useAppToast'
import type { useWbRestoreMakeProgressCache } from './useWbRestoreMakeProgressCache'
import type { WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 6409–6415, 6426–6432, 9255–9258 …）；逐字迁移，行为不变。
export function useWbFlushPlanMermaidDiagrams(ctx: ReturnType<typeof useWbRestoreMakeProgressCache>) {
  const {
    wbSidebar, workbenchErrorMessage, pendingHandoff, makeCompletionResult, finalizeLoading, orchestrationSession,
    __wbState, workflowLinkOffer, planSession, planReplyDraft, planOptionSelections, PLAN_OPTION_OTHER_ID,
    planOptionOtherText, clearPlanOptionOtherText, knowledgeStatus, knowledgeDocs, knowledgeLoading, knowledgeUploading,
    knowledgeError, knowledgeFileInputRef, knowledgeDragActive, isCanvasSkillIntent, showMakePlatformCasualChat, activeBot,
    useTypewriter, voiceSessionState, voiceTitle, shouldAutoDismissStaleVoicePlan, syncVoiceWorkPhase, requireLoginForWorkbenchUse,
    truncateWorkbenchText, makeHasActiveTask, greetingLine, parsePlanAssistantContent, planQuickOptions, planPanelTitle,
    mermaidChecklistLabel,
  } = ctx

async function dismissPlanSessionFromVoice() {
  dismissPlanSession()
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  voiceSessionState.value.planDismissedAt = Date.now()
  syncVoiceWorkPhase()
}
function dismissStaleVoicePlanSilently() {
  if (!shouldAutoDismissStaleVoicePlan()) return
  dismissPlanSession()
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  syncVoiceWorkPhase()
}
const planChecklistFlowMarkdown = computed(() => {
  const lines = Array.isArray(planSession.value?.checklistLines) ? planSession.value.checklistLines : []
  return buildChecklistFlowMarkdown(lines)
})
function buildChecklistFlowMarkdown(lines: unknown): string {
  const list = Array.isArray(lines) ? lines.filter((x) => String(x || '').trim()).slice(0, 18) : []
  if (!list.length) {
    return '```mermaid\nflowchart TD\n  start["开始"] --> done["完成"]\n```'
  }
  const out = ['```mermaid', 'flowchart TD', '  start["开始"]']
  list.forEach((line, idx) => {
    out.push(`  S${idx + 1}["${idx + 1}. ${mermaidChecklistLabel(line)}"]`)
  })
  out.push('  done["完成"]')
  out.push('  start --> S1')
  for (let i = 1; i < list.length; i += 1) {
    out.push(`  S${i} --> S${i + 1}`)
  }
  out.push(`  S${list.length} --> done`)
  out.push('```')
  return out.join('\n')
}
function cancelPlanSummary() {
  __wbState.planSummaryStreamHandle?.abort()
  __wbState.planSummaryStreamHandle = null
  dismissPlanSession()
  showAppToast('已取消任务摘要生成', { variant: 'info' })
}
function compactPlanVisibleText(text: unknown, max = 260): string {
  const s = stripInternalMarkers(String(text || ''))
    .replace(/【本次上传附件全文】[\s\S]*?(?=\n\n---\n|$)/g, '【本次上传附件全文已读取，界面不展开】')
    .replace(/【我的文件资料库命中片段】[\s\S]*?(?=\n\n---\n|$)/g, '【资料库片段已读取，界面不展开】')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '请根据上传内容和输入描述进行规划'
  return s.length > max ? `${s.slice(0, max)}…` : s
}
/** 制作区大标题：从交接描述里优先取「初始想法」段，否则整段压缩 */
function extractInitialIdeaFromHandoff(description: unknown): string {
  const s = String(description || '')
  const m = s.match(/【初始想法】\s*\n+([\s\S]*?)(?=\n\n---|\n【|$)/)
  const chunk = m?.[1]?.trim() ? m[1].trim() : s.trim()
  if (!chunk) return ''
  return compactPlanVisibleText(chunk, 900)
}
const MAKE_HERO_TITLE_MAX = 64
const makeHeroTitle = computed(() => {
  if (!makeHasActiveTask.value) return '今天有什么安排？'
  const ps = planSession.value
  if (ps) {
    const title = String(ps.summaryTitle || '').trim()
    if (title) return truncateWorkbenchText(title, MAKE_HERO_TITLE_MAX)
    if (ps.phase === 'summary') {
      const body = String(ps.summaryText || '').replace(/\s+/g, ' ').trim()
      if (body) return truncateWorkbenchText(body, MAKE_HERO_TITLE_MAX)
    }
    const firstUser = ps.messages?.find((m: WorkbenchStateRecord) => m.role === 'user')
    if (firstUser?.content) {
      return truncateWorkbenchText(compactPlanVisibleText(String(firstUser.content), 800), MAKE_HERO_TITLE_MAX)
    }
    return truncateWorkbenchText(planPanelTitle.value, MAKE_HERO_TITLE_MAX)
  }
  if (finalizeLoading.value) {
    const ps = planSession.value
    const title = String(ps?.summaryTitle || '').trim()
    if (title) return truncateWorkbenchText(title, MAKE_HERO_TITLE_MAX)
    const h = pendingHandoff.value
    const nm = h?.workflowName?.trim() || h?.employeeWorkflowName?.trim()
    if (nm) return truncateWorkbenchText(nm, MAKE_HERO_TITLE_MAX)
    const idea = h ? extractInitialIdeaFromHandoff(h.description) : ''
    if (idea) return truncateWorkbenchText(idea, MAKE_HERO_TITLE_MAX)
    return '制作进行中…'
  }
  if (makeCompletionResult.value?.title) {
    return truncateWorkbenchText(String(makeCompletionResult.value.title), MAKE_HERO_TITLE_MAX)
  }
  const h = pendingHandoff.value
  if (h) {
    if (isCanvasSkillIntent(h.intentKey) && h.workflowName?.trim()) {
      return truncateWorkbenchText(h.workflowName.trim(), MAKE_HERO_TITLE_MAX)
    }
    const idea = extractInitialIdeaFromHandoff(h.description)
    if (idea) return truncateWorkbenchText(idea, MAKE_HERO_TITLE_MAX)
    return truncateWorkbenchText(h.intentTitle || '制作草稿', MAKE_HERO_TITLE_MAX)
  }
  const orch = orchestrationSession.value
  if (orch?.steps?.length) {
    const art = orch.artifact || {}
    const nm = String(art.workflow_name || art.workflowName || art.name || orch.workflow_name || '').trim()
    if (nm) return truncateWorkbenchText(nm, MAKE_HERO_TITLE_MAX)
    const st = orch.steps.find((s) => s.status === 'running') || orch.steps[0]
    if (st?.label) return truncateWorkbenchText(String(st.label), MAKE_HERO_TITLE_MAX)
    return '制作进行中'
  }
  const wf = workflowLinkOffer.value
  if (wf?.workflowName) return truncateWorkbenchText(String(wf.workflowName), MAKE_HERO_TITLE_MAX)
  return '进行中的任务'
})
const activeModeReset = computed(() => wbSidebar.activeMode)
const directTitleText = computed(() => {
  if (activeBot.value) return activeBot.value.name
  if (showMakePlatformCasualChat.value) return '先说说你想做什么'
  return '有什么想问的？'
})
const directSubText = computed(() => {
  if (activeBot.value?.desc) return activeBot.value.desc
  if (showMakePlatformCasualChat.value) {
    return '仍在「做」档位：先对齐需求再动手。需要规划 Mod / 员工 / Skill 时，先关闭顶栏「闲聊」再使用做 Mod / 做员工。'
  }
  return '像聊天一样提问，我直接帮你分析、总结和给出可执行答案。'
})
const makeKickerText = computed(() => greetingLine.value || '')
const makeTitleText = computed(() => makeHeroTitle.value)
const directTitleTw = useTypewriter(directTitleText, 55, activeModeReset)
const directSubTw = useTypewriter(directSubText, 40, activeModeReset)
const makeKickerTw = useTypewriter(makeKickerText, 40, activeModeReset)
const makeTitleTw = useTypewriter(makeTitleText, 40, activeModeReset)
const voiceTitleText = computed(() => voiceTitle.value)
const _voiceTitleTw = useTypewriter(voiceTitleText, 55, activeModeReset)
function buildPlanSummarySystemPrompt(intentTitle: unknown, mode?: string): string {
  const lines = [
    '你是需求摘要助手。你只负责把用户上传文件和输入内容总结成一个简短、准确的任务摘要，供用户确认。',
    `当前制作类型：${intentTitle || '未指定'}`,
    '输出格式必须严格为：',
    'TITLE: 一句话任务标题，不超过22个中文字符',
    'SUMMARY: 2到3句话说明任务目标、输入文件、期望产出',
  ]
  if (mode === 'employee-voice') {
    lines.push(
      '若输入含【语音对话记录】且用户已说明员工职责、处理对象或期望产出，必须给出具体 TITLE，禁止 TITLE:待澄清。',
      '对话中已确认的细节（如全量提取、JSON 输出、使用场景）应写入 SUMMARY；仅把对话里尚未回答的问题列为「待确认：…」。',
    )
  } else {
    lines.push(
      '若输入信息不足以构成明确任务（如 ASR 噪声、闲聊碎片、缺少具体职责），必须输出：',
      'TITLE: 待澄清',
      'SUMMARY: 列出还需要用户补充的具体信息（不要编造未提及的内容）',
    )
  }
  lines.push(
    '禁止编造用户未提及的上传文件、工作表现数据、Excel 等内容。',
    '不要输出流程图，不要输出选项，不要输出执行清单，不要泄露附件全文。',
  )
  return lines.join('\n')
}
function parsePlanSummary(raw: unknown, fallback: unknown): { title: string; summary: string } {
  const text = String(raw || '').trim()
  const titleMatch = text.match(/^TITLE:\s*(.+)$/im)
  const summaryMatch = text.match(/^SUMMARY:\s*([\s\S]+)$/im)
  const lines = text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  const fallbackText = compactPlanVisibleText(fallback, 180)
  const title = (titleMatch?.[1] || lines[0] || fallbackText || '确认任务').replace(/^#+\s*/, '').trim().slice(0, 36)
  const summary = (summaryMatch?.[1] || lines.slice(1).join(' ') || fallbackText || title).trim()
  return { title, summary }
}
const canSendPlanQuickPicks = computed(() => {
  const opts = planQuickOptions.value
  if (!opts.length) return false
  const sel = planOptionSelections.value
  return opts.every((q) => {
    const cid = sel[q.id]
    if (!cid) return false
    if (cid === PLAN_OPTION_OTHER_ID) {
      return Boolean(String(planOptionOtherText[q.id] || '').trim())
    }
    return true
  })
})
function planAssistantParts(raw: unknown) {
  return parsePlanAssistantContent(raw)
}
/** 助手气泡 Mermaid 渲染错误（按消息下标） */
const planDiagramError = ref<Record<string, string>>({})
/** 规划流程图：完整预览浮层（消息下标，null 为关闭） */
const planDiagramPreviewIdx = ref<number | null>(null)
const planDiagramPreviewMountRef = ref<HTMLElement | null>(null)
const planDiagramPreviewViewportRef = ref<HTMLElement | null>(null)
const planPreviewScale = ref(1)
const planPreviewTx = ref(0)
const planPreviewTy = ref(0)
const planDiagramPreviewPanStyle = computed(() => ({
  transform: `translate(${planPreviewTx.value}px, ${planPreviewTy.value}px) scale(${planPreviewScale.value})`,
  transformOrigin: '0 0',
}))
function clearPlanDiagramPreviewPointerListeners() {
  if (__wbState.planDiagramPreviewPointerCleanup) {
    __wbState.planDiagramPreviewPointerCleanup()
    __wbState.planDiagramPreviewPointerCleanup = null
  }
  planDiagramPreviewViewportRef.value?.classList.remove('wb-plan-diagram-preview-viewport--drag')
}
function onPlanDiagramPreviewWheel(e: WheelEvent) {
  const vp = planDiagramPreviewViewportRef.value
  if (!vp) return
  const rect = vp.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const oldS = planPreviewScale.value
  const factor = e.deltaY > 0 ? 0.9 : 1.1
  const newS = Math.min(6, Math.max(0.06, oldS * factor))
  if (Math.abs(newS - oldS) < 1e-6) return
  planPreviewTx.value = mx - ((mx - planPreviewTx.value) * newS) / oldS
  planPreviewTy.value = my - ((my - planPreviewTy.value) * newS) / oldS
  planPreviewScale.value = newS
}
function onPlanDiagramPreviewPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const vp = planDiagramPreviewViewportRef.value
  if (!vp || !planDiagramPreviewMountRef.value) return
  clearPlanDiagramPreviewPointerListeners()
  const sx = e.clientX
  const sy = e.clientY
  const stx = planPreviewTx.value
  const sty = planPreviewTy.value
  vp.classList.add('wb-plan-diagram-preview-viewport--drag')
  const move = (ev: PointerEvent) => {
    planPreviewTx.value = stx + (ev.clientX - sx)
    planPreviewTy.value = sty + (ev.clientY - sy)
  }
  const end = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
    vp.classList.remove('wb-plan-diagram-preview-viewport--drag')
    __wbState.planDiagramPreviewPointerCleanup = null
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', end)
  window.addEventListener('pointercancel', end)
  __wbState.planDiagramPreviewPointerCleanup = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
    vp.classList.remove('wb-plan-diagram-preview-viewport--drag')
  }
}
function planDiagramPreviewZoomStep(dir: number) {
  const vp = planDiagramPreviewViewportRef.value
  if (!vp) return
  const mx = vp.clientWidth / 2
  const my = vp.clientHeight / 2
  const oldS = planPreviewScale.value
  const factor = dir < 0 ? 1 / 1.22 : 1.22
  const newS = Math.min(6, Math.max(0.06, oldS * factor))
  planPreviewTx.value = mx - ((mx - planPreviewTx.value) * newS) / oldS
  planPreviewTy.value = my - ((my - planPreviewTy.value) * newS) / oldS
  planPreviewScale.value = newS
}
async function planDiagramPreviewFitView() {
  await nextTick()
  const vp = planDiagramPreviewViewportRef.value
  const mount = planDiagramPreviewMountRef.value
  const svg = mount?.querySelector('svg')
  if (!vp || !svg) return
  planPreviewScale.value = 1
  planPreviewTx.value = 0
  planPreviewTy.value = 0
  await nextTick()
  await new Promise<void>((r) => requestAnimationFrame(() => r()))
  let nw = 0
  let nh = 0
  try {
    const bb = svg.getBBox()
    nw = bb.width
    nh = bb.height
  } catch {
    /* ignore */
  }
  if (!nw || !nh) {
    const r = svg.getBoundingClientRect()
    nw = r.width || 1
    nh = r.height || 1
  }
  const pad = 36
  const vw = Math.max(64, vp.clientWidth - pad * 2)
  const vh = Math.max(64, vp.clientHeight - pad * 2)
  const s = Math.min(vw / nw, vh / nh, 3)
  const fit = Number.isFinite(s) && s > 0 ? s : 1
  planPreviewScale.value = fit
  const bw = nw * fit
  const bh = nh * fit
  planPreviewTx.value = (vp.clientWidth - bw) / 2
  planPreviewTy.value = (vp.clientHeight - bh) / 2
}
async function openPlanDiagramPreview(idx: string | number): Promise<void> {
  const diagramIndex = Number(idx)
  planDiagramPreviewIdx.value = diagramIndex
  planPreviewScale.value = 1
  planPreviewTx.value = 0
  planPreviewTy.value = 0
  if (__wbState.planDiagramPreviewEscUnlisten) {
    __wbState.planDiagramPreviewEscUnlisten()
    __wbState.planDiagramPreviewEscUnlisten = null
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closePlanDiagramPreview()
  }
  window.addEventListener('keydown', onKey)
  __wbState.planDiagramPreviewEscUnlisten = () => window.removeEventListener('keydown', onKey)
  await nextTick()
  await nextTick()
  const host = document.getElementById(`wb-plan-mer-${diagramIndex}`)
  const svg = host?.querySelector('svg')
  const target = planDiagramPreviewMountRef.value
  if (!target) return
  target.innerHTML = ''
  if (svg) {
    const clone = svg.cloneNode(true) as SVGElement
    clone.style.maxWidth = 'none'
    clone.style.width = 'auto'
    clone.style.height = 'auto'
    target.appendChild(clone)
  } else {
    const p = document.createElement('p')
    p.className = 'wb-plan-diagram-preview-empty'
    p.textContent = '流程图尚未渲染完成，请稍后再次点击「完整预览」。'
    target.appendChild(p)
  }
  await nextTick()
  await planDiagramPreviewFitView()
  target.focus()
}
function closePlanDiagramPreview() {
  clearPlanDiagramPreviewPointerListeners()
  if (__wbState.planDiagramPreviewEscUnlisten) {
    __wbState.planDiagramPreviewEscUnlisten()
    __wbState.planDiagramPreviewEscUnlisten = null
  }
  planDiagramPreviewIdx.value = null
}
async function getMermaidSingleton() {
  if (!__wbState.mermaidApi) {
    const mod = await import('mermaid')
    __wbState.mermaidApi = mod.default
  }
  if (!__wbState.mermaidInitDone) {
    __wbState.mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'dark',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    })
    __wbState.mermaidInitDone = true
  }
  return __wbState.mermaidApi
}
async function flushPlanMermaidDiagrams() {
  const ps = planSession.value
  if (!ps?.messages?.length) {
    planDiagramError.value = {}
    return
  }
  const nextErr: Record<string, string> = {}
  let mer
  try {
    mer = await getMermaidSingleton()
  } catch {
    planDiagramError.value = { _: '无法加载流程图组件' }
    return
  }
  for (const [idx, m] of ps.messages.entries()) {
    if (m.role !== 'assistant') continue
    const { diagram, hasDiagram } = parsePlanAssistantContent(m.content)
    const host = document.getElementById(`wb-plan-mer-${idx}`)
    if (!host) continue
    host.innerHTML = ''
    if (!hasDiagram) continue
    const cleaned = sanitizeMermaidSource(diagram)
    const graphEl = document.createElement('div')
    graphEl.className = 'mermaid'
    graphEl.textContent = cleaned
    host.appendChild(graphEl)
    try {
      await mer.run({ nodes: [graphEl] })
    } catch (e) {
      if (cleaned !== diagram) {
        host.innerHTML = ''
        const retryEl = document.createElement('div')
        retryEl.className = 'mermaid'
        retryEl.textContent = diagram
        host.appendChild(retryEl)
        try {
          await mer.run({ nodes: [retryEl] })
          continue
        } catch {
          host.innerHTML = ''
        }
      } else {
        host.innerHTML = ''
      }
      nextErr[idx] = friendlyMermaidRenderError(e)
    }
  }
  planDiagramError.value = nextErr
}
function dismissPlanSession() {
  closePlanDiagramPreview()
  planSession.value = null
  planReplyDraft.value = ''
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  planDiagramError.value = {}
}
async function loadKnowledgeDocuments(requireLogin = false) {
  if (!getAccessToken()) {
    if (requireLogin) requireLoginForWorkbenchUse()
    knowledgeStatus.value = null
    knowledgeDocs.value = []
    knowledgeError.value = ''
    return
  }
  knowledgeLoading.value = true
  knowledgeError.value = ''
  try {
    const [st, docs] = await Promise.all([
      api.knowledgeStatus(),
      api.knowledgeListDocuments(),
    ])
    knowledgeStatus.value = st
    knowledgeDocs.value = Array.isArray(docs?.documents) ? docs.documents : []
  } catch (e: unknown) {
    knowledgeError.value = workbenchErrorMessage(e)
    knowledgeDocs.value = []
  } finally {
    knowledgeLoading.value = false
  }
}
function openKnowledgeFilePicker() {
  if (knowledgeUploading.value || planSession.value) return
  if (!requireLoginForWorkbenchUse()) return
  knowledgeFileInputRef.value?.click?.()
}
function onKnowledgeDragEnter() {
  if (knowledgeUploading.value || planSession.value) return
  knowledgeDragActive.value = true
}
function onKnowledgeDragLeave(e: DragEvent): void {
  const current = e.currentTarget as HTMLElement | null
  const related = e.relatedTarget as Node | null
  if (current && related && current.contains?.(related)) return
  knowledgeDragActive.value = false
}
function fileExtension(filename: unknown): string {
  const ext = String(filename || '').split('.').pop()?.toLowerCase() || 'file'
  return ext.length > 5 ? ext.slice(0, 5) : ext
}
function fileKind(doc: WorkbenchStateRecord): string {
  const ext = fileExtension(doc?.filename)
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx') return 'doc'
  if (ext === 'xlsx' || ext === 'csv') return 'sheet'
  if (ext === 'json') return 'json'
  if (ext === 'md') return 'md'
  return 'text'
}
function fileKindClass(doc: WorkbenchStateRecord): string {
  return `wb-kb-card--${fileKind(doc)}`
}
function fileKindLabel(doc: WorkbenchStateRecord): string {
  const m = {
    pdf: 'PDF 文档',
    doc: 'Word 文档',
    sheet: '表格数据',
    json: 'JSON 配置',
    md: 'Markdown',
    text: '文本资料',
  }
  return m[fileKind(doc) as keyof typeof m] || '文件'
}
function formatBytes(value: unknown): string {
  const n = Number(value || 0)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  if (n < 1024) return `${Math.round(n)} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
async function deleteKnowledgeDocument(docId: string): Promise<void> {
  if (!docId) return
  if (!requireLoginForWorkbenchUse()) return
  try {
    await api.knowledgeDeleteDocument(docId)
    await loadKnowledgeDocuments()
  } catch (e: unknown) {
    knowledgeError.value = workbenchErrorMessage(e)
  }
}
function formatKnowledgeContext(items: unknown): string {
  const rows = Array.isArray(items) ? items : []
  if (!rows.length) return ''
  return rows
    .slice(0, 6)
    .map((it: WorkbenchStateRecord, i: number) => {
      const filename = it?.filename || '资料'
      const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
      const content = String(it?.content || '').trim()
      return `### ${i + 1}. ${filename}${pageNo ? `（第 ${pageNo} 页）` : ''}\n${content}`
    })
    .join('\n\n---\n\n')
}

  return {
    ...ctx, dismissPlanSessionFromVoice, dismissStaleVoicePlanSilently, planChecklistFlowMarkdown, buildChecklistFlowMarkdown,
    cancelPlanSummary, compactPlanVisibleText, extractInitialIdeaFromHandoff, MAKE_HERO_TITLE_MAX, makeHeroTitle,
    activeModeReset, directTitleText, directSubText, makeKickerText, makeTitleText,
    directTitleTw, directSubTw, makeKickerTw, makeTitleTw, voiceTitleText,
    _voiceTitleTw, buildPlanSummarySystemPrompt, parsePlanSummary, canSendPlanQuickPicks, planAssistantParts,
    planDiagramError, planDiagramPreviewIdx, planDiagramPreviewMountRef, planDiagramPreviewViewportRef, planPreviewScale,
    planPreviewTx, planPreviewTy, planDiagramPreviewPanStyle, clearPlanDiagramPreviewPointerListeners, onPlanDiagramPreviewWheel,
    onPlanDiagramPreviewPointerDown, planDiagramPreviewZoomStep, planDiagramPreviewFitView, openPlanDiagramPreview, closePlanDiagramPreview,
    getMermaidSingleton, flushPlanMermaidDiagrams, dismissPlanSession, loadKnowledgeDocuments, openKnowledgeFilePicker,
    onKnowledgeDragEnter, onKnowledgeDragLeave, fileExtension, fileKind, fileKindClass,
    fileKindLabel, formatBytes, deleteKnowledgeDocument, formatKnowledgeContext,
  }
}

export type useWbFlushPlanMermaidDiagramsBinds = ReturnType<typeof useWbFlushPlanMermaidDiagrams>
