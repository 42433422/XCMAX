import { nextTick } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import type { SixDimensionReport } from '../../types/sixDimension'
import { api } from '../../api'
import { mergeOrchStepsMonotonic } from '../../utils/orchestrationSteps'
import type { OrchStepLike } from '../../utils/orchestrationSteps'
import { resetVoiceSessionState } from '../../composables/voiceSessionAgent'
import type { useWbFlushPlanMermaidDiagrams } from './useWbFlushPlanMermaidDiagrams'
import type { DirectKbResult, KnowledgeRetrieveResponse, PendingHandoff, WorkbenchCompletionResult, WorkbenchOrchestrationSession } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 2578–2595, 4698–4783, 8062–8083 …）；逐字迁移，行为不变。
export function useWbRetrieveKnowledgeForDirect(ctx: ReturnType<typeof useWbFlushPlanMermaidDiagrams>) {
  const {
    router, draft, workbenchErrorMessage, workbenchHttpStatus, inputRef, handoffPanelRef,
    pendingHandoff, makeCompletionResult, employeeSixDimModalOpen, employeeSixDimReport, makeCompletionRef, finalizeLoading,
    finalizeError, orchestrationSession, orchestrationSessionId, pollStop, orchPhase, orchestrationEtaSeconds,
    orchestrationEtaReason, orchTimingStartMs, workflowLinkOffer, linkMods, linkModId, linkBusy,
    linkError, planPanelRef, knowledgeUploading, knowledgeError, isEmbeddingConfigured, isCanvasSkillIntent,
    composerIntent, voiceSessionModeForIntent, directAttachedFiles, directChatEmployeeId, activeConversation, personalSettingsOpen,
    activeBot, tierPanelOpen, empPanelOpen, convPopoverOpen, voiceSessionState, withRequestTimeout,
    DIRECT_KB_RETRIEVE_MS, syncVoiceWorkPhase, selectedProvider, selectedModel, modelMode, pickEmployeeKey,
    pickModId, stopOrchestrationElapsedTicker, startOrchestrationElapsedTicker, hasWorkflow, hasEmployee, _trackStepMessages,
    clearMakeProgressCache, clearWorkbenchHandoffSession, planDiagramPreviewIdx, dismissPlanSession, formatKnowledgeContext,
  } = ctx

function clearMakePanelsForCasualChat() {
  pollStop.value = true
  dismissPendingHandoff()
  dismissPlanSession()
  workflowLinkOffer.value = null
  makeCompletionResult.value = null
  employeeSixDimModalOpen.value = false
  employeeSixDimReport.value = null
  tierPanelOpen.value = false
  empPanelOpen.value = false
  pickEmployeeKey.value = ''
  pickModId.value = ''
  finalizeError.value = ''
  resetVoiceSessionState(voiceSessionState, voiceSessionModeForIntent(composerIntent.value))
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  syncVoiceWorkPhase()
}
async function retrieveKnowledgeForDirect(
  userText: string,
  provider: string,
  model: string,
): Promise<DirectKbResult> {
  let knowledgePack = ''
  let citations: DirectKbResult['citations'] = []
  if (!userText.trim()) return { knowledgePack, citations }
  // AI 客服 Bot：优先管理端 persy 知识库（小C SSOT）
  if (String(activeBot.value?.id || '') === 'customer-service') {
    try {
      const res: KnowledgeRetrieveResponse = await withRequestTimeout(
        api.csSsotRetrieve({ query: userText, top_k: 6 }),
        DIRECT_KB_RETRIEVE_MS,
      )
      const chunks = Array.isArray(res?.chunks) ? res.chunks : []
      if (chunks.length > 0) {
        const lines = chunks.slice(0, 6).map((c, i) => {
          const text = String(c?.text || c?.content || c?.snippet || '').trim()
          const source = String(c?.source || c?.document_id || c?.filename || 'persy').trim()
          return `[${i + 1}] (${source}) ${text.slice(0, 500)}`
        })
        knowledgePack = `【管理端知识库·persy-knowledge】\n${lines.join('\n')}`
        citations = chunks.slice(0, 6).map((c, i) => ({
          title: `${i + 1}. ${String(c?.source || c?.filename || '管理端知识库')}`,
          snippet: String(c?.text || c?.content || '').trim().slice(0, 200),
        }))
        return { knowledgePack, citations }
      }
    } catch {
      /* fall through to market knowledge */
    }
  }
  try {
    const pickedEmp = String(directChatEmployeeId.value || '').trim()
    const botEmp = String(activeBot.value?.id || '').trim()
    const employeeId = pickedEmp || botEmp
    const res: KnowledgeRetrieveResponse = await withRequestTimeout(
      api.knowledgeV2Retrieve({
        query: userText,
        top_k: 6,
        employee_id: employeeId || undefined,
        embedding_provider: provider,
        embedding_model: model,
      }),
      DIRECT_KB_RETRIEVE_MS,
    )
    const items = Array.isArray(res?.items) ? res.items : []
    if (items.length > 0) {
      knowledgePack = formatKnowledgeContext(items)
      citations = items.slice(0, 6).map((it, i) => {
        const filename = String(it?.filename || '资料')
        const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
        const snippet = String(it?.content || '').trim().slice(0, 200)
        return { title: `${i + 1}. ${filename}${pageNo ? ` · 第 ${pageNo} 页` : ''}`, snippet }
      })
    }
  } catch {
    try {
      const ready = directAttachedFiles.value.some((f) => f.status === 'ready')
      const hasUserUploads = activeConversation.value?.messages?.some(
        (m) => Array.isArray(m.attachments) && m.attachments.some((a) => a.status === 'ready'),
      )
      if ((ready || hasUserUploads) && isEmbeddingConfigured()) {
        const res: KnowledgeRetrieveResponse = await withRequestTimeout(
          api.knowledgeSearch(userText, 6, {
            embeddingProvider: provider,
            embeddingModel: model,
          }),
          DIRECT_KB_RETRIEVE_MS,
        )
        const items = Array.isArray(res?.items) ? res.items : []
        knowledgePack = formatKnowledgeContext(items)
        citations = items.slice(0, 6).map((it, i) => {
          const filename = String(it?.filename || '资料')
          const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
          const snippet = String(it?.content || '').trim().slice(0, 200)
          return { title: `${i + 1}. ${filename}${pageNo ? ` · 第 ${pageNo} 页` : ''}`, snippet }
        })
      }
    } catch {
      /* 检索失败不阻塞聊天 */
    }
  }
  return { knowledgePack, citations }
}
async function retryOrchStep(_st: OrchStepLike) {
  const sid = String(orchestrationSessionId.value || '').trim()
  if (!sid) return
  try {
    const res = await api.workbenchRetrySession(sid)
    if (res?.session_id) {
      orchestrationSessionId.value = res.session_id
      pollStop.value = false
      if (orchPhase.value !== 'estimating') {
        orchPhase.value = 'running'
        if (!orchTimingStartMs.value) orchTimingStartMs.value = Date.now()
        startOrchestrationElapsedTicker()
      }
      const final = await pollWorkbenchSession(res.session_id)
      if (final && final.status === 'error') {
        finalizeError.value = final.error || '编排失败'
      }
    }
  } catch (e: unknown) {
    finalizeError.value = workbenchErrorMessage(e) || '重试失败'
  }
}
/** 二档制作主输入：开启全新任务，清空草稿、附件、规划与执行态。 */
function resetMakeComposer() {
  if (knowledgeUploading.value) return
  dismissPendingHandoff()
  dismissPlanSession()
  makeCompletionResult.value = null
  employeeSixDimModalOpen.value = false
  employeeSixDimReport.value = null
  draft.value = ''
  knowledgeError.value = ''
  const files = directAttachedFiles.value.slice()
  directAttachedFiles.value = []
  for (const item of files as Array<{ docId?: string }>) {
    if (item.docId) {
      void api.knowledgeDeleteDocument(item.docId).catch(() => {
        /* 与移除单附件一致 */
      })
    }
  }
  clearMakeProgressCache()
  nextTick(() => {
    const el = inputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}
function dismissWorkflowLinkOffer() {
  workflowLinkOffer.value = null
  linkMods.value = []
  linkModId.value = ''
  linkError.value = ''
  linkBusy.value = false
}
async function loadLinkMods() {
  try {
    const res = await api.listMods()
    linkMods.value = Array.isArray(res?.data) ? res.data : []
  } catch {
    linkMods.value = []
  }
}
async function openWorkflowCanvasOnly() {
  const o = workflowLinkOffer.value
  if (!o) return
  const wid = o.workflowId
  dismissWorkflowLinkOffer()
  await router.push({ name: 'workbench-workflow', query: { edit: String(wid) } })
}
async function confirmWorkflowModLink() {
  const o = workflowLinkOffer.value
  if (!o || !linkModId.value) return
  linkBusy.value = true
  linkError.value = ''
  try {
    await api.modWorkflowLink(String(linkModId.value), {
      workflow_id: o.workflowId,
      label: o.workflowName,
    })
    const mid = linkModId.value
    dismissWorkflowLinkOffer()
    await router.push({ name: 'mod-authoring', params: { modId: mid } })
  } catch (e: unknown) {
    linkError.value = workbenchErrorMessage(e)
  } finally {
    linkBusy.value = false
  }
}
function dismissPendingHandoff() {
  pendingHandoff.value = null
  finalizeError.value = ''
  makeCompletionResult.value = null
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  orchPhase.value = 'idle'
  orchTimingStartMs.value = null
  orchestrationEtaSeconds.value = null
  orchestrationEtaReason.value = ''
  finalizeLoading.value = false
  dismissWorkflowLinkOffer()
  clearWorkbenchHandoffSession()
}
function buildMakeCompletionResult(
  final: WorkbenchOrchestrationSession,
  intent: string,
  handoffSnapshot: PendingHandoff,
): WorkbenchCompletionResult {
  const art = final?.artifact || {}
  const finIntent = final?.intent || intent
  if (finIntent === 'employee') {
    const packId = art.pack_id != null ? String(art.pack_id) : ''
    const q: Record<string, string> = {
      focus: 'employee',
      fromAi: '1',
      packId,
      name: art.name != null ? String(art.name) : '',
      desc: art.description != null ? String(art.description) : '',
    }
    const wfId = art.workflow_id ?? art.workflow_attachment?.workflow_id
    if (wfId != null && Number(wfId) > 0) q.wfId = String(wfId)
    const name = String(art.name || handoffSnapshot?.employeeWorkflowName || '员工包').trim()
    return {
      intent: 'employee',
      title: `${name} 已生成`,
      subtitle: packId ? `员工包 ID：${packId}` : '员工包已写入本地库',
      usageLines: [
        '员工包已写入本地目录，尚未自动上架到商店。',
        '打开「员工制作」→ 测试运行 → 确认无误后手动上传/上架。',
        'Word 提取类员工：上传 .doc/.docx，输出同名 .txt。',
        wfId ? `已绑定画布工作流 id=${wfId}，可在 Skill 组画布继续调整。` : '',
      ].filter(Boolean),
      primaryLabel: '打开员工制作',
      primaryRoute: hasEmployee.value
        ? { name: 'workbench-unified', query: q }
        : null,
      secondaryLabel: wfId ? '打开 Skill 组画布' : '',
      secondaryRoute: wfId && hasWorkflow.value
        ? { name: 'workbench-unified', query: { focus: 'skill', edit: String(wfId) } }
        : null,
    }
  }
  if (finIntent === 'mod' && art.mod_id) {
    return {
      intent: 'mod',
      title: `Mod「${art.mod_id}」已生成`,
      subtitle: '仓库骨架、manifest 与员工名片已写入',
      usageLines: [
        '在 Mod 制作页完善行业 JSON、员工包与工作流绑定。',
        '完成绑定后可在宿主中切换 Mod 并做真实执行验证。',
      ],
      primaryLabel: '打开 Mod 制作',
      primaryRoute: { name: 'mod-authoring', params: { modId: String(art.mod_id) } },
      secondaryLabel: '',
      secondaryRoute: null,
    }
  }
  const gid = art.skill_group_id ?? art.workflow_id
  if (isCanvasSkillIntent(finIntent) && gid != null) {
    const nm = String(
      art.skill_group_name || art.workflow_name || handoffSnapshot?.workflowName || `Skill 组 ${gid}`,
    ).trim()
    return {
      intent: 'skill',
      title: `${nm} 已生成`,
      subtitle: art.sandbox_ok === false ? '部分校验未通过，请在画布中查看详情' : '节点与 Skill 已写入画布',
      usageLines: [
        '打开 Skill 组画布查看节点、连线和沙箱校验结果。',
        '可按需调整 Skill 输入输出与触发策略后再发布。',
      ],
      primaryLabel: '打开 Skill 组画布',
      primaryRoute: hasWorkflow.value ? { name: 'workbench-workflow', query: { edit: String(gid) } } : null,
      secondaryLabel: '',
      secondaryRoute: null,
    }
  }
  return {
    intent: finIntent,
    title: '制作已完成',
    subtitle: '',
    usageLines: ['请在工作台相关页面查看产物详情。'],
    primaryLabel: '知道了',
    primaryRoute: null,
    secondaryLabel: '',
    secondaryRoute: null,
  }
}
async function scrollMakeFlowToEnd() {
  await nextTick()
  const el = makeCompletionRef.value || handoffPanelRef.value || planPanelRef.value
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    return
  }
  const scene = document.querySelector('.wb-mode-scene--make-flow')
  if (scene && typeof scene.scrollTo === 'function') {
    scene.scrollTo({ top: scene.scrollHeight, behavior: 'smooth' })
  }
}
async function openMakeCompletionPrimary() {
  const r = makeCompletionResult.value
  if (!r?.primaryRoute) {
    makeCompletionResult.value = null
    return
  }
  try {
    await router.push(r.primaryRoute as RouteLocationRaw)
  } catch {
    finalizeError.value = '无法打开目标页面，请从左侧导航进入对应功能。'
  }
}
async function openMakeCompletionSecondary() {
  const r = makeCompletionResult.value
  if (!r?.secondaryRoute) return
  try {
    await router.push(r.secondaryRoute as RouteLocationRaw)
  } catch {
    finalizeError.value = '无法打开 Skill 组画布，请从工作流列表进入。'
  }
}
function closeEmployeeSixDimModal() {
  employeeSixDimModalOpen.value = false
}
/** Teleport 到 body 的遮罩在 keep-alive 切走首页后仍会挡住「统一工作台」等路由（z-index 12000）。 */
function dismissHomeBodyOverlays() {
  employeeSixDimModalOpen.value = false
  planDiagramPreviewIdx.value = null
  convPopoverOpen.value = false
  personalSettingsOpen.value = false
}
/** 开发/联调：打开六维雷达弹窗样例（?wb_test_sixdim=1 或控制台 __wbOpenSixDimTest()） */
/** 仅 ?wb_test_sixdim=1 / 控制台联调用；正式完成走 artifact.six_dimension_report */
function openSixDimTestPreview() {
  employeeSixDimReport.value = {
    dimensions: {
      requirement_clarity: {
        score: 88,
        grade: 'A',
        grade_label: 'A级·优秀',
        label: '需求理解',
        description: '需求是否被正确理解：brief 净化、结构化规格与 Word/资产管线识别是否一致。',
        reasons: ['routing brief 有效', 'Word 场景已识别 direct_python'],
      },
      pack_compliance: {
        score: 92,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '包体合规',
        description: 'manifest 可读性、artifact 类型、员工声明字段与 validate 硬错误。',
        reasons: ['manifest 可读', '包体声明与校验通过'],
      },
      code_robustness: {
        score: 85,
        grade: 'A',
        grade_label: 'A级·优秀',
        label: '代码健壮',
        description: 'Python 编译、包体一致性、mod 沙箱轻量校验结果。',
        reasons: ['Python 编译通过', 'mod 沙箱轻量校验通过'],
      },
      executability: {
        score: 90,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '可执行性',
        description: 'handlers 契约、独立 zipapp 自检、目录登记与领域 runtime。',
        reasons: ['handlers 契约通过', 'Word convert runtime 就绪'],
      },
      workflow_connectivity: {
        score: 78,
        grade: 'B',
        grade_label: 'B级·良好',
        label: '流程贯通',
        description: '员工包登记、工作流结构校验与真实员工调用。',
        reasons: ['登记成功', '工作流结构校验通过'],
      },
      domain_delivery: {
        score: 95,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '领域交付',
        description: '与 Word 全量提取管线匹配的交付能力。',
        reasons: ['Word 全量提取 runtime 通过', 'rule_spec runtime_kind 正确'],
      },
    },
    overall_score: 94.9,
    overall_grade: 'S',
    overall_grade_label: 'S级·卓越',
    passed: true,
    critical_failed: false,
    pipeline_label: 'word_full_extract',
    grade_scale: {
      S: '92–100：卓越，可直接交付',
      A: '85–91.9：优秀',
      B: '78–84.9：良好',
      P: '70–77.9：平级达标（达到流水线通过线）',
      C: '60–69.9：合格但有明显短板',
      D: '50–59.9：待改进',
      F: '40–49.9：高风险',
      G: '0–39.9 或关键维未达标：不可用',
    },
  }
  employeeSixDimModalOpen.value = true
}
function tryOpenEmployeeSixDimModal(final: WorkbenchOrchestrationSession): void {
  const art = final?.artifact
  if (!art || typeof art !== 'object') return
  const rep =
    (art as Record<string, unknown>).six_dimension_report ||
    ((art as Record<string, unknown>).quality_report as Record<string, unknown> | undefined)
      ?.six_dimension_report
  if (!rep || typeof rep !== 'object' || !(rep as Record<string, unknown>).dimensions) return
  employeeSixDimReport.value = rep as SixDimensionReport
  employeeSixDimModalOpen.value = true
}
async function persistManualLlmIfNeeded() {
  if (modelMode.value !== 'manual' || !selectedModel.value || !selectedProvider.value) return
  try {
    await api.llmSavePreferences(selectedProvider.value, selectedModel.value)
  } catch {
    /* 仍尝试创建工作流 */
  }
}
async function pollWorkbenchSession(sessionId: string): Promise<WorkbenchOrchestrationSession | null> {
  const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))
  /**
   * 轮询策略：基础 1500ms（约 40 次/分钟），落在后端 RateLimiterMiddleware
   * 默认 60 次/60 秒的限额内，避免「开始生成员工包」长时间运行被 429 截断。
   * 后端同时为 GET /api/workbench/sessions/{id} 单独抬高了上限作为兜底。
   */
  const baseIntervalMs = 1500
  const runningIntervalMs = 1000
  /** 总等待预算约 30 分钟（配套小程序等步骤可走多轮 Agent），墙钟时间而非轮询次数（应对动态退避）。 */
  const deadline = Date.now() + 30 * 60 * 1000
  let backoffMs = 0
  while (!pollStop.value) {
    try {
      const s = await api.workbenchGetSession(sessionId)
      const prevSteps = orchestrationSession.value?.steps
      const mergedSteps = mergeOrchStepsMonotonic(prevSteps, s.steps || [])
      orchestrationSession.value = { ...s, steps: mergedSteps }
      _trackStepMessages(mergedSteps)
      if (s.status === 'done' || s.status === 'error') {
        if (s.status === 'done') {
          const nonTerminal = (mergedSteps || []).filter(
            (x: OrchStepLike) =>
              x.status !== 'done' && x.status !== 'error' && x.status !== 'skipped',
          )
          if (nonTerminal.length > 0) {
            for (let i = 0; i < 3 && !pollStop.value; i++) {
              await delay(800)
              try {
                const s2 = await api.workbenchGetSession(sessionId)
                const merged2: OrchStepLike[] = mergeOrchStepsMonotonic(
                  orchestrationSession.value?.steps,
                  s2.steps || [],
                )
                orchestrationSession.value = { ...s2, steps: merged2 }
                _trackStepMessages(merged2)
                const stillPending = (merged2 || []).filter(
                  (x: OrchStepLike) =>
                    x.status !== 'done' && x.status !== 'error' && x.status !== 'skipped',
                )
                if (stillPending.length === 0) break
              } catch {
                break
              }
            }
          }
        }
        return orchestrationSession.value as typeof s
      }
      backoffMs = 0
    } catch (e) {
      const status = workbenchHttpStatus(e)
      // 429（限流）/ 503（短暂不可用）属于可恢复抖动：指数退避后继续轮询，
      // 而非把整个编排会话标记为失败。其余错误按原行为向上抛出。
      if (status === 429 || status === 503) {
        backoffMs = backoffMs ? Math.min(backoffMs * 2, 30000) : 5000
      } else {
        throw e
      }
    }
    if (Date.now() >= deadline) {
      const steps = Array.isArray(orchestrationSession.value?.steps) ? orchestrationSession.value.steps : []
      const stuckStep = steps.find((x) => x.status === 'running') || steps.slice().reverse().find((x) => x.status === 'done')
      const stuckLabel = stuckStep ? `「${String(stuckStep.label || stuckStep.id)}」` : ''
      throw new Error(`在${stuckLabel}步骤等待超时（约 30 分钟）。若会话仍在后端运行可刷新后从历史恢复；否则可重试。请检查后端日志、网络或 LLM 配置。`)
    }
    const sessStatus = orchestrationSession.value?.status
    const hasRunningStep = Array.isArray(orchestrationSession.value?.steps)
      && orchestrationSession.value.steps.some((x) => x.status === 'running')
    const tickMs =
      backoffMs || (sessStatus === 'running' || hasRunningStep ? runningIntervalMs : baseIntervalMs)
    await delay(tickMs)
  }
  return null
}
async function resumeCachedOrchestration() {
  const sid = String(orchestrationSessionId.value || '').trim()
  if (!sid || !finalizeLoading.value) return
  pollStop.value = false
  if (orchPhase.value !== 'estimating') {
    orchPhase.value = 'running'
    if (!orchTimingStartMs.value) orchTimingStartMs.value = Date.now()
    startOrchestrationElapsedTicker()
  }
  try {
    const final = await pollWorkbenchSession(sid)
    if (!final || pollStop.value) return
    orchestrationSession.value = final
    if (final.status === 'error') {
      finalizeError.value = final.error || '编排失败'
    }
  } catch (e: unknown) {
    const m = workbenchErrorMessage(e)
    finalizeError.value = m
  } finally {
    stopOrchestrationElapsedTicker()
    finalizeLoading.value = false
    orchPhase.value = 'idle'
    orchTimingStartMs.value = null
  }
}

  return {
    ...ctx, clearMakePanelsForCasualChat, retrieveKnowledgeForDirect, retryOrchStep, resetMakeComposer,
    dismissWorkflowLinkOffer, loadLinkMods, openWorkflowCanvasOnly, confirmWorkflowModLink, dismissPendingHandoff,
    buildMakeCompletionResult, scrollMakeFlowToEnd, openMakeCompletionPrimary, openMakeCompletionSecondary, closeEmployeeSixDimModal,
    dismissHomeBodyOverlays, openSixDimTestPreview, tryOpenEmployeeSixDimModal, persistManualLlmIfNeeded, pollWorkbenchSession,
    resumeCachedOrchestration,
  }
}

export type useWbRetrieveKnowledgeForDirectBinds = ReturnType<typeof useWbRetrieveKnowledgeForDirect>
