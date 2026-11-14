import { computed } from 'vue'
import { get, post } from '@/api'
import { appAlert } from '@/utils/appDialog'
import { DEFAULT_PIPELINE_STAGES } from './usePipelineGuide'
import { displayNameFromPipeline } from './useCustomerServiceFormat'
import type { IntakeFormFields } from './internalCsTypes'
import { CS_BRIDGE, type WorkbenchCtx } from './workbenchContext'

/** 商机 pipeline 阶段：草稿、加载、保存、分析、回写本地文档。 */
export function usePipelineStage(ctx: WorkbenchCtx) {
  const {
    deps,
    guide,
    stageDraft,
    stageSaving,
    pipelineAnalyzing,
    autoStageAdvancing,
    intakeAutoFinalizeAttempted,
  } = ctx
  const {
    selectedUserId,
    selectedEnterpriseUser,
    clientSummaries,
    customerPipeline,
    pipelineStages,
    currentStageId,
    syncEnterpriseCredsFromPipeline,
    loadChangeRequestsForCustomer,
    loadFinanceLedger,
  } = deps
  const { stageRank, stageLabel, stageGuideFor } = guide

  // ---- computed ----
  const stageDraftDirty = computed(() => stageDraft.value !== currentStageId.value)

  const viewingStageId = computed(() =>
    stageDraftDirty.value ? stageDraft.value : currentStageId.value,
  )

  const canSavePipelineStage = computed(
    () => Boolean(selectedUserId.value) && stageDraftDirty.value && !stageSaving.value,
  )

  const saveStageButtonTitle = computed(() => {
    if (!selectedUserId.value) return '请先展开客户卡片'
    if (stageSaving.value) return '正在保存'
    if (!stageDraftDirty.value) return '请先在进度条或下拉框选择不同于当前阶段的选项'
    return `保存为「${stageLabel(stageDraft.value)}」`
  })

  const currentStageGuide = computed(() => stageGuideFor(viewingStageId.value))

  const nextPipelineStage = computed(() => {
    const stages = pipelineStages.value
    const idx = stageRank(currentStageId.value)
    if (idx < 0 || idx >= stages.length - 1) return null
    return stages[idx + 1]
  })

  // ---- 摘要同步 ----
  function syncSummaryFromPipeline(userId: number, loginUsername?: string) {
    const login = String(
      loginUsername || selectedEnterpriseUser.value?.username || '',
    ).trim()
    clientSummaries[userId] = {
      stage: customerPipeline.stage,
      last_message_preview: customerPipeline.last_message_preview,
      intake_sent: customerPipeline.intake_sent,
      display_name: displayNameFromPipeline(
        {
          intake_form: customerPipeline.intake_form,
          erp_customer_name: customerPipeline.erp_customer_name,
          username: customerPipeline.username,
        },
        login,
      ),
    }
  }

  async function loadClientSummary(userId: number, username?: string) {
    const login = String(username || '').trim()
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/pipeline`, { market_user_id: userId, username: login })
      const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline || {}
      clientSummaries[userId] = {
        stage: String(p.stage || 'idle'),
        last_message_preview: String(p.last_message_preview || ''),
        intake_sent: Boolean(p.intake_sent),
        display_name: displayNameFromPipeline(p, login),
      }
    } catch {
      clientSummaries[userId] = {
        stage: 'idle',
        last_message_preview: '',
        intake_sent: false,
        display_name: '',
      }
    }
  }

  // ---- pipeline 加载/保存 ----
  async function fetchPipelineFromServer(opts: { autoAdvance?: boolean } = {}): Promise<{
    pipeline: Record<string, unknown>
    stages: typeof DEFAULT_PIPELINE_STAGES
    advanced: boolean
    crm?: Record<string, unknown>
  } | null> {
    if (!selectedUserId.value) return null
    const res = await get(`${CS_BRIDGE}/user-cs/pipeline`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      auto_advance: Boolean(opts.autoAdvance),
    })
    const data = (res as {
      data?: {
        pipeline?: Record<string, unknown>
        stages?: typeof DEFAULT_PIPELINE_STAGES
        advanced?: boolean
        crm?: Record<string, unknown>
      }
    })?.data
    if (!data?.pipeline) return null
    return {
      pipeline: data.pipeline,
      stages: data.stages?.length ? data.stages : DEFAULT_PIPELINE_STAGES,
      advanced: Boolean(data.advanced),
      crm: data.crm,
    }
  }

  async function maybeAutoAdvancePipelineStage() {
    if (!selectedUserId.value || stageSaving.value || autoStageAdvancing.value) return
    autoStageAdvancing.value = true
    try {
      const data = await fetchPipelineFromServer({ autoAdvance: true })
      if (!data) return
      pipelineStages.value = data.stages
      applyPipelineFromDoc(data.pipeline)
      syncSummaryFromPipeline(selectedUserId.value)
      if (data.advanced) {
        await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
      }
    } catch (e) {
      console.warn('[cs] auto-advance pipeline failed', e)
    } finally {
      autoStageAdvancing.value = false
    }
  }

  async function maybeAutoFinalizeIntakeOnOpen() {
    if (!selectedUserId.value) return
    if (!customerPipeline.intake_submitted_at || customerPipeline.crm_funnel_synced_at) return
    if (intakeAutoFinalizeAttempted.value === selectedUserId.value) return
    intakeAutoFinalizeAttempted.value = selectedUserId.value
    await ctx.finalizeIntakeFromPipeline({ silent: true })
  }

  async function loadPipelineForCustomer() {
    if (!selectedUserId.value) return
    try {
      await ctx.syncDemandFormFromMarket()
      const data = await fetchPipelineFromServer({ autoAdvance: true })
      if (!data) return
      pipelineStages.value = data.stages
      applyPipelineFromDoc(data.pipeline)
      ctx.applyCrmBundle(data.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
      syncSummaryFromPipeline(selectedUserId.value)
      if (data.advanced) {
        await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
      } else if (
        String(data.pipeline.stage || '') === 'intake'
        && data.pipeline.intake_submitted_at
      ) {
        await maybeAutoAdvancePipelineStage()
      }
      await maybeAutoFinalizeIntakeOnOpen()
      await loadChangeRequestsForCustomer()
      await loadFinanceLedger()
    } catch {
      pipelineStages.value = DEFAULT_PIPELINE_STAGES
    }
  }

  function pickPipelineStageDraft(stageId: string) {
    if (stageSaving.value) return
    stageDraft.value = stageId
  }

  async function savePipelineStage(
    targetStage?: string,
    opts: { silent?: boolean; confirmMessage?: string; auto?: boolean } = {},
  ) {
    if (!selectedUserId.value) return
    const stage = (targetStage ?? stageDraft.value).trim()
    if (stage === currentStageId.value) return
    if (!opts.silent) {
      const label = stageLabel(stage)
      const ok = window.confirm(
        opts.confirmMessage
          ?? `将当前客户阶段改为「${label}」？\n可前进或回退，不影响已保存的客户档案。`,
      )
      if (!ok) {
        stageDraft.value = currentStageId.value
        return
      }
    }
    stageDraft.value = stage
    stageSaving.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/pipeline/stage`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        stage,
        manual: !opts.auto,
        note: opts.auto ? 'checklist_complete' : '',
      })
      const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
      if (!payload?.success) {
        await appAlert(payload?.error || '保存失败')
        return
      }
      const p = payload.data?.pipeline
      if (p) {
        applyPipelineFromDoc(p, { resetDraft: true })
        ctx.applyDeliveryFromDoc(p)
        syncSummaryFromPipeline(selectedUserId.value)
      } else {
        await loadPipelineForCustomer()
      }
      if (
        stageRank(stage) >= stageRank('intake_done')
        && (!customerPipeline.crm_opportunity_id || !customerPipeline.crm_quote_id)
      ) {
        await ctx.syncCrmRecord()
      }
      await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '保存阶段失败')
    } finally {
      stageSaving.value = false
    }
  }

  async function analyzeCustomerProgress(_options: { skipSync?: boolean } = {}) {
    if (!selectedUserId.value) return
    pipelineAnalyzing.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/analyze`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        intake_sent: customerPipeline.intake_sent || Boolean(ctx.demandIntake.messageText),
      })
      const data = (res as {
        data?: {
          pipeline?: Record<string, unknown>
          crm?: { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> }
        }
      })?.data
      const p = data?.pipeline
      if (p) {
        applyPipelineFromDoc(p, { resetDraft: false })
        ctx.applyDeliveryFromDoc(p)
        ctx.applyCrmBundle(data?.crm)
        syncSummaryFromPipeline(selectedUserId.value)
      }
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
    } finally {
      pipelineAnalyzing.value = false
    }
  }

  // ---- pipeline 文档写入 ----
  function applyPipelineFromDoc(p: Record<string, unknown>, opts: { resetDraft?: boolean } = {}) {
    const prevStage = customerPipeline.stage
    const newStage = String(p.stage || 'idle')
    customerPipeline.stage = newStage
    const pendingDraft = stageDraft.value !== prevStage && stageDraft.value !== newStage
    if (opts.resetDraft || !pendingDraft || stageDraft.value === newStage) {
      stageDraft.value = newStage
    }
    customerPipeline.last_message_preview = String(p.last_message_preview || '')
    customerPipeline.intake_sent = Boolean(p.intake_sent)
    customerPipeline.intake_submitted_at = String(p.intake_submitted_at || '')
    customerPipeline.landing_contact_id = Number(p.landing_contact_id || 0)
    const rawForm = p.intake_form
    customerPipeline.intake_form = rawForm && typeof rawForm === 'object'
      ? { ...(rawForm as IntakeFormFields) }
      : null
    customerPipeline.erp_customer_id = Number(p.erp_customer_id || 0)
    customerPipeline.erp_customer_name = String(p.erp_customer_name || '')
    customerPipeline.crm_funnel_synced_at = String(p.crm_funnel_synced_at || '')
    customerPipeline.crm_opportunity_id = Number(p.crm_opportunity_id || 0)
    customerPipeline.crm_quote_id = Number(p.crm_quote_id || 0)
    customerPipeline.crm_db_synced_at = String(p.crm_db_synced_at || '')
    customerPipeline.external_crm_deal_id = String(p.external_crm_deal_id || '')
    customerPipeline.external_crm_last_at = String(p.external_crm_last_at || '')
    customerPipeline.external_crm_last_error = String(p.external_crm_last_error || '')
    customerPipeline.external_crm_last_pull_at = String(p.external_crm_last_pull_at || '')
    customerPipeline.external_crm_last_pull_error = String(p.external_crm_last_pull_error || '')
    customerPipeline.username = String(p.username || customerPipeline.username || '')
    customerPipeline.enterprise_auto_provisioned_at = String(p.enterprise_auto_provisioned_at || '')
    customerPipeline.enterprise_login_username = String(
      p.enterprise_login_username || p.username || customerPipeline.enterprise_login_username || '',
    )
    customerPipeline.enterprise_login_password = String(
      p.enterprise_login_password || customerPipeline.enterprise_login_password || '',
    )
    customerPipeline.enterprise_credentials_issued_at = String(
      p.enterprise_credentials_issued_at || customerPipeline.enterprise_credentials_issued_at || '',
    )
    syncEnterpriseCredsFromPipeline()
    ctx.syncDemandIntakeClientNameFromPipeline()
    customerPipeline.software_delivery_sent_at = String(p.software_delivery_sent_at || '')
    customerPipeline.software_delivery_os = String(p.software_delivery_os || '')
    ;(customerPipeline as unknown as { external_crm_last_result?: unknown }).external_crm_last_result =
      p.external_crm_last_result
    ;(customerPipeline as unknown as { external_crm_last_pull_result?: unknown }).external_crm_last_pull_result =
      p.external_crm_last_pull_result
    const ds = p.delivery_signoff
    customerPipeline.delivery_signoff =
      ds && typeof ds === 'object' ? { ...(ds as { id?: number; status?: string }) } : null
    ctx.applyDeliveryFromDoc(p)
    const qd = p.quote_draft
    if (qd && typeof qd === 'object') {
      ctx.crmQuoteStatus.value = String((qd as { status?: string }).status || '')
      ctx.crmQuoteSummary.value = String((qd as { summary?: string }).summary || '')
    }
  }

  // 填充跨域函数槽
  ctx.applyPipelineFromDoc = applyPipelineFromDoc
  ctx.syncSummaryFromPipeline = syncSummaryFromPipeline
  ctx.loadClientSummary = loadClientSummary
  ctx.loadPipelineForCustomer = loadPipelineForCustomer
  ctx.maybeAutoAdvancePipelineStage = maybeAutoAdvancePipelineStage

  return {
    stageDraftDirty,
    viewingStageId,
    canSavePipelineStage,
    saveStageButtonTitle,
    currentStageGuide,
    nextPipelineStage,
    syncSummaryFromPipeline,
    loadClientSummary,
    loadPipelineForCustomer,
    pickPipelineStageDraft,
    savePipelineStage,
    analyzeCustomerProgress,
    applyPipelineFromDoc,
  }
}