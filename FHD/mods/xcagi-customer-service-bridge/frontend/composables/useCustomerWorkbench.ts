import { computed, reactive, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { get, post, put } from '@/api'
import { appAlert } from '@/utils/appDialog'
import {
  AUTO_ADVANCE_CHECKLIST_STAGES,
  DEFAULT_PIPELINE_STAGES,
  usePipelineGuide,
  type PhaseCheckKey,
} from './usePipelineGuide'
import {
  displayNameFromPipeline,
  formatAuditCodeFromLandingId,
  intakeFormPreviewRows,
} from './useCustomerServiceFormat'
import type {
  ClientSummaries,
  EnterpriseUserRow,
  IntakeFormFields,
} from './internalCsTypes'

const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

/** 客户 pipeline 完整状态（外层入口创建 reactive，工作台读写） */
export type CustomerPipelineState = {
  stage: string
  username: string
  last_message_preview: string
  intake_sent: boolean
  intake_submitted_at: string
  landing_contact_id: number
  intake_form: IntakeFormFields | null
  erp_customer_id: number
  erp_customer_name: string
  crm_funnel_synced_at: string
  crm_opportunity_id: number
  crm_quote_id: number
  crm_db_synced_at: string
  crm_invoice_id: number
  external_crm_deal_id: string
  external_crm_last_at: string
  external_crm_last_error: string
  external_crm_last_pull_at: string
  external_crm_last_pull_error: string
  enterprise_auto_provisioned_at: string
  enterprise_login_username: string
  enterprise_login_password: string
  enterprise_credentials_issued_at: string
  software_delivery_sent_at: string
  software_delivery_os: string
  delivery_signoff: { id?: number; status?: string } | null
}

type IntakeStageForm = {
  name?: string
  company?: string
  email?: string
  phone?: string
  message?: string
  landing_contact_id?: unknown
}

type WorkbenchDeps = {
  selectedUserId: Ref<number | null>
  selectedEnterpriseUser: ComputedRef<EnterpriseUserRow | null>
  clientSummaries: ClientSummaries
  customerPipeline: CustomerPipelineState
  pipelineStages: Ref<Array<{ id: string; label: string }>>
  currentStageId: ComputedRef<string>
  syncEnterpriseCredsFromPipeline: () => void
  loadEnterpriseUsers: () => Promise<void>
  loadChangeRequestsForCustomer: () => Promise<void>
  loadFinanceLedger: () => Promise<void>
}

/**
 * 内部客服「客户工作台」域：商机 pipeline 阶段、交付计划、合同、需求采集、
 * 支付/CRM/签收、群组话术等全部状态与逻辑。
 * 与客户列表（useCustomerList）、企业凭据（useEnterpriseCredentials）、
 * 财务台账（useFinanceLedger）、变更工单（useChangeRequests）通过注入依赖协作。
 */
export function useCustomerWorkbench(deps: WorkbenchDeps) {
  const {
    selectedUserId,
    selectedEnterpriseUser,
    clientSummaries,
    customerPipeline,
    pipelineStages,
    currentStageId,
    syncEnterpriseCredsFromPipeline,
    loadEnterpriseUsers,
    loadChangeRequestsForCustomer,
    loadFinanceLedger,
  } = deps

  const guide = usePipelineGuide(pipelineStages, currentStageId)
  const { stageRank, stageLabel, stageGuideFor, stepperItemClass } = guide

  // ---- pipeline 操作状态 ----
  const stageDraft = ref('idle')
  const stageSaving = ref(false)
  const pipelineAnalyzing = ref(false)
  const autoStageAdvancing = ref(false)
  const intakeFinalizeLoading = ref(false)
  const signoffLoading = ref(false)
  const intakeAutoFinalizeAttempted = ref(0)

  const demandIntake = reactive({
    brief: '',
    clientName: '',
    formUrl: 'https://xiu-ci.com/contact.html',
    signedFormUrl: '',
    messageText: '',
    loading: false,
  })

  const contractForm = reactive({
    party_a_name: '',
    party_a_credit_code: '',
    total_amount_number: '',
    expected_out_trade_no: '',
    sign_date: '',
    main_function_list: '',
    loading: false,
    savingFields: false,
    filename: '',
    downloadUrl: '',
  })

  const deliveryForm = reactive({
    expected_delivery_at: '',
    milestones: [] as Array<{ id: string; label: string; weight: number; done: boolean }>,
    progress_percent: 0,
    saving: false,
    checkingPayment: false,
  })

  const paymentStatus = ref('')
  const paymentOutTradeNo = ref('')
  const paymentVerification = ref('')
  const invoiceNo = ref('')

  const crmQuoteSummary = ref('')
  const crmQuoteStatus = ref('')
  const crmSyncLoading = ref(false)
  const crmRepairLoading = ref(false)
  const externalCrmPushLoading = ref(false)
  const externalCrmPullLoading = ref(false)

  // ---- 需求采集 / 官网表单 ----
  const intakeQuickFormUrl = ref('')
  const intakeLinkLoading = ref(false)
  const intakeAuditCode = ref('')
  const auditCodeFetching = ref(false)
  const auditCodeRedeeming = ref(false)
  const auditCodeError = ref('')
  const intakeAuditPreview = ref<Record<string, unknown> | null>(null)
  const intakeAuditPreviewCode = ref('')
  const intakeAuditPreviewAt = ref('')

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

  const showIntakeStageShortcuts = computed(
    () => currentStageId.value === 'intake' || currentStageId.value === 'intake_done',
  )

  const showQuoteNegotiateActions = computed(() => {
    const id = currentStageId.value
    return id === 'intake_done' || id === 'quoted' || id === 'negotiating'
  })

  const showCrmLinkagePanel = computed(
    () => stageRank(currentStageId.value) >= stageRank('intake_done'),
  )

  const showCrmFinalizeActions = computed(() => {
    const id = currentStageId.value
    if (!['intake_done', 'quoted', 'negotiating'].includes(id)) return false
    return Boolean(
      !customerPipeline.crm_opportunity_id
      || !customerPipeline.crm_quote_id
      || !(customerPipeline.erp_customer_id || customerPipeline.erp_customer_name),
    )
  })

  const showIntakeFunnelWarn = computed(
    () =>
      Boolean(customerPipeline.intake_submitted_at)
      && !customerPipeline.crm_funnel_synced_at
      && stageRank(currentStageId.value) >= stageRank('intake_done'),
  )

  const externalCrmStatusLabel = computed(() => {
    const raw = (customerPipeline as unknown as { external_crm_last_result?: Record<string, unknown> })
      .external_crm_last_result
    if (!raw || typeof raw !== 'object') return ''
    if (raw.skipped) return String(raw.reason || '已跳过')
    if (raw.ok) return String(raw.provider || '成功')
    return String(raw.error || raw.reason || '失败')
  })

  const externalCrmPullStatusLabel = computed(() => {
    const raw = (customerPipeline as unknown as { external_crm_last_pull_result?: Record<string, unknown> })
      .external_crm_last_pull_result
    if (!raw || typeof raw !== 'object') return ''
    if (raw.skipped) return String(raw.reason || '已跳过')
    if (raw.ok) {
      if (raw.stage_changed) {
        return `已回写为「${stageLabel(String(raw.pipeline_stage || ''))}」`
      }
      return '阶段无变化'
    }
    return String(raw.error || raw.reason || '失败')
  })

  const showEsignPanel = computed(
    () =>
      stageRank(currentStageId.value) >= stageRank('contract_pending')
      && stageRank(currentStageId.value) <= stageRank('signed'),
  )

  const groupScriptActionLabel = computed(() => {
    if (currentStageId.value === 'intake_done') return '需求确认'
    if (currentStageId.value === 'negotiating') return '议价'
    return '报价'
  })

  const currentStageGuide = computed(() => stageGuideFor(viewingStageId.value))

  const nextPipelineStage = computed(() => {
    const stages = pipelineStages.value
    const idx = stageRank(currentStageId.value)
    if (idx < 0 || idx >= stages.length - 1) return null
    return stages[idx + 1]
  })

  const currentStageChecklistComplete = computed(() => {
    const items = currentStageGuide.value.checklist
    if (!items.length) return true
    return items.every((item) => checklistItemDoneFactual(item.key))
  })

  const intakeSubmittedAwaitingAdvance = computed(
    () =>
      currentStageId.value === 'intake'
      && Boolean(customerPipeline.intake_submitted_at)
      && checklistItemDoneFactual('form_done'),
  )

  const showIntakeBlock = computed(() => stageRank(currentStageId.value) >= stageRank('connected'))
  const showContractBlock = computed(() => stageRank(currentStageId.value) >= stageRank('contract_pending'))
  const showDeliveryBlock = computed(() => stageRank(currentStageId.value) >= stageRank('signed'))

  const paymentStatusLabel = computed(() => {
    const s = paymentStatus.value
    if (s === 'paid') return '已到款（已出账）'
    if (s === 'confirmed') return '已确认到款'
    if (s === 'detected') return '检测到款话术'
    return '待付款'
  })

  const paymentVerificationLabel = computed(() => {
    const v = paymentVerification.value
    if (v === 'gateway') return '市场订单已核实'
    if (v === 'chat_heuristic') return '群聊话术（未核实订单库）'
    if (v === 'manual') return '人工强制确认'
    return ''
  })

  const clientDesktopOs = computed(() => {
    const form = customerPipeline.intake_form
    const direct = String(form?.desktop_os || '').trim()
    if (direct === 'mac' || direct === 'win') return direct
    const msg = String(form?.message || '')
    const m = msg.match(/使用系统[：:]\s*(mac\s*os|macos|mac|windows|win)/i)
    if (!m) return ''
    const raw = m[1].toLowerCase()
    if (raw.startsWith('mac')) return 'mac'
    if (raw.startsWith('win')) return 'win'
    return ''
  })

  const clientNeedMobile = computed(() => {
    const form = customerPipeline.intake_form
    if (form && typeof form.need_mobile === 'boolean') return form.need_mobile
    const msg = String(form?.message || '')
    const m = msg.match(/手机端[：:]\s*(需要|不需要)/)
    if (m) return m[1] === '需要'
    return true
  })

  const contractSamplePdfUrl = `${CS_BRIDGE}/user-cs/contract/sample-pdf`

  const intakeSubmissionSummary = computed(() => {
    if (!customerPipeline.intake_form || !customerPipeline.intake_submitted_at) return null
    return intakeFormPreviewRows(customerPipeline.intake_form as Record<string, unknown>, {
      auditCode: formatAuditCodeFromLandingId(customerPipeline.landing_contact_id),
      submittedAt: customerPipeline.intake_submitted_at,
    })
  })

  const intakeAuditPreviewRows = computed(() => {
    if (!intakeAuditPreview.value) return null
    const sub = intakeAuditPreview.value as IntakeStageForm
    const form = {
      name: sub.name,
      company: sub.company,
      email: sub.email,
      phone: sub.phone,
      message: sub.message,
      landing_contact_id: sub.landing_contact_id,
    }
    return intakeFormPreviewRows(form, {
      auditCode: intakeAuditPreviewCode.value || String(sub.landing_contact_id || ''),
      submittedAt: intakeAuditPreviewAt.value || String(sub.landing_contact_id || ''),
    })
  })

  // ---- 名称/摘要助手 ----
  function matchedCompanyName(): string {
    const form = customerPipeline.intake_form
    return (
      String(form?.company || '').trim()
      || String(customerPipeline.erp_customer_name || '').trim()
    )
  }

  function intakePrefillGreetingName(): string {
    const manual = demandIntake.clientName.trim()
    const login = (selectedEnterpriseUser.value?.username || customerPipeline.username || '').trim()
    if (manual && (!login || manual.toLowerCase() !== login.toLowerCase())) {
      return manual
    }
    const company = matchedCompanyName()
    if (company) return company
    const contact = String(customerPipeline.intake_form?.name || '').trim()
    if (contact && (!login || contact.toLowerCase() !== login.toLowerCase())) return contact
    return login
  }

  function syncDemandIntakeClientNameFromPipeline() {
    const name = intakePrefillGreetingName()
    const login = (selectedEnterpriseUser.value?.username || '').trim()
    if (name && (!login || name.toLowerCase() !== login.toLowerCase())) {
      demandIntake.clientName = name
    }
  }

  // ---- 清单 ----
  function checklistItemDoneFactual(key: PhaseCheckKey): boolean {
    switch (key) {
      case 'bind':
        return false
      case 'sync':
        return false
      case 'messages':
        return false
      case 'connected_welcome':
        return false
      case 'intake_sent':
        return customerPipeline.intake_sent || Boolean(demandIntake.messageText)
      case 'form_done':
        return Boolean(customerPipeline.intake_submitted_at)
          || stageRank(currentStageId.value) >= stageRank('intake_done')
      case 'erp_linked':
        return Boolean(customerPipeline.erp_customer_id || customerPipeline.erp_customer_name)
      case 'crm_record':
        if (currentStageId.value === 'negotiating') {
          return Boolean(customerPipeline.crm_opportunity_id && customerPipeline.crm_quote_id)
            && (crmQuoteStatus.value === 'negotiating' || crmQuoteStatus.value === 'sent')
        }
        if (stageRank(currentStageId.value) >= stageRank('quoted')) {
          return Boolean(customerPipeline.crm_opportunity_id && customerPipeline.crm_quote_id)
        }
        return Boolean(customerPipeline.crm_opportunity_id)
      case 'delivery_plan':
        return Boolean(deliveryForm.expected_delivery_at) && deliveryForm.milestones.length > 0
      case 'delivery_progress':
        return deliveryForm.progress_percent >= 100
          || stageRank(currentStageId.value) >= stageRank('delivered')
      case 'payment_received':
        return ['detected', 'confirmed', 'paid'].includes(paymentStatus.value)
      case 'invoice_issued':
        return Boolean(customerPipeline.crm_invoice_id) || Boolean(invoiceNo.value)
      case 'contract_draft':
        return Boolean(contractForm.filename)
      default:
        return false
    }
  }

  function checklistItemDone(key: PhaseCheckKey): boolean {
    const viewing = viewingStageId.value
    const current = currentStageId.value

    if (stageDraftDirty.value && stageDraft.value !== current) {
      return false
    }

    if (!stageDraftDirty.value && viewing === current && AUTO_ADVANCE_CHECKLIST_STAGES.has(current)) {
      return false
    }

    if (stageRank(current) > stageRank(viewing)) {
      return true
    }

    return checklistItemDoneFactual(key)
  }

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

  // ---- 交付计划 ----
  function defaultMilestones() {
    return [
      { id: 'scope', label: '需求与范围确认', weight: 10, done: false },
      { id: 'design', label: '方案与原型设计', weight: 15, done: false },
      { id: 'dev', label: '定制开发实现', weight: 40, done: false },
      { id: 'qa', label: '联调与测试', weight: 20, done: false },
      { id: 'accept', label: '验收与交付上线', weight: 15, done: false },
    ]
  }

  function recomputeDeliveryProgress() {
    const ms = deliveryForm.milestones
    let total = 0
    let done = 0
    for (const m of ms) {
      total += Number(m.weight) || 0
      if (m.done) done += Number(m.weight) || 0
    }
    deliveryForm.progress_percent = total > 0 ? Math.min(100, Math.round((done * 100) / total)) : 0
  }

  function onMilestoneToggle() {
    recomputeDeliveryProgress()
  }

  function applyDeliveryFromDoc(p: Record<string, unknown>) {
    const d = p.delivery
    if (d && typeof d === 'object') {
      const block = d as Record<string, unknown>
      deliveryForm.expected_delivery_at = String(block.expected_delivery_at || '').slice(0, 10)
      const ms = block.milestones
      if (Array.isArray(ms) && ms.length) {
        deliveryForm.milestones = ms.map((m) => ({
          id: String((m as { id?: string }).id || ''),
          label: String((m as { label?: string }).label || ''),
          weight: Number((m as { weight?: number }).weight) || 0,
          done: Boolean((m as { done?: boolean }).done),
        }))
      } else if (!deliveryForm.milestones.length) {
        deliveryForm.milestones = defaultMilestones()
      }
      deliveryForm.progress_percent = Number(block.progress_percent) || 0
    } else if (!deliveryForm.milestones.length) {
      deliveryForm.milestones = defaultMilestones()
    }
    const pay = p.payment
    if (pay && typeof pay === 'object') {
      const pb = pay as Record<string, unknown>
      paymentStatus.value = String(pb.status || '')
      paymentOutTradeNo.value = String(pb.out_trade_no || pb.expected_out_trade_no || '')
      paymentVerification.value = String(pb.verification || '')
    }
    const inv = p.invoice
    if (inv && typeof inv === 'object') {
      invoiceNo.value = String((inv as { invoice_no?: string }).invoice_no || '')
      customerPipeline.crm_invoice_id = Number((inv as { id?: number }).id || p.crm_invoice_id || 0)
    } else {
      customerPipeline.crm_invoice_id = Number(p.crm_invoice_id || 0)
    }
  }

  async function saveDeliveryPlan(startDelivering: boolean) {
    if (!selectedUserId.value) return
    deliveryForm.saving = true
    recomputeDeliveryProgress()
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/delivery/plan`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        expected_delivery_at: deliveryForm.expected_delivery_at,
        milestones: deliveryForm.milestones,
        start_delivery: startDelivering,
        stage: startDelivering ? 'delivering' : undefined,
      })
      const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
      if (!payload?.success) {
        await appAlert(payload?.error || '保存失败')
        return
      }
      const p = payload.data?.pipeline
      if (p) {
        applyPipelineFromDoc(p, { resetDraft: true })
        applyDeliveryFromDoc(p)
      }
      await appAlert(startDelivering ? '交付计划已保存，阶段已更新为「交付中」' : '交付进度已保存')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '保存交付计划失败')
    } finally {
      deliveryForm.saving = false
    }
  }

  async function checkPaymentAndInvoice(force: boolean) {
    if (!selectedUserId.value) return
    if (contractForm.expected_out_trade_no.trim()) {
      await saveContractFields({ silent: true })
    }
    deliveryForm.checkingPayment = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/delivery/check-payment`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        force_confirm: force,
      })
      const payload = res as {
        success?: boolean
        data?: {
          pipeline?: Record<string, unknown>
          payment_detected?: boolean
          invoice_created?: boolean
          invoice?: { invoice_no?: string }
          market_payment?: { ok?: boolean; source?: string; error?: string }
          error?: string
        }
      }
      const d = payload.data
      if (d?.pipeline) {
        applyPipelineFromDoc(d.pipeline)
        applyDeliveryFromDoc(d.pipeline)
      }
      const mp = d?.market_payment
      const mpHint = mp?.ok
        ? (mp.source ? `（订单库：${mp.source}）` : '')
        : (mp?.error ? `（市场查询：${mp.error}）` : '')
      if (d?.invoice_created && d.invoice?.invoice_no) {
        await appAlert(`已生成账单：${d.invoice.invoice_no}${mpHint}`)
      } else if (d?.payment_detected) {
        await appAlert(`到款已确认，账单处理完成${mpHint}`)
      } else {
        await appAlert(
          d?.error
            || `未核实到款${mpHint}。请填写「关联市场订单号」并保存合同字段，或让客户在修茈市场完成支付后重试；线下转账可点「强制确认到款」。`,
        )
      }
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '检查到款失败')
    } finally {
      deliveryForm.checkingPayment = false
    }
  }

  // ---- CRM ----
  function applyCrmBundle(crm: {
    opportunity?: Record<string, unknown>
    quote?: Record<string, unknown>
    invoice?: { id?: number; invoice_no?: string }
    delivery?: { expected_delivery_at?: string; milestones_json?: string; progress_percent?: number }
  } | null | undefined) {
    const opp = crm?.opportunity
    const quote = crm?.quote
    if (opp && typeof opp === 'object') {
      customerPipeline.crm_opportunity_id = Number(opp.id || 0)
      if (!customerPipeline.landing_contact_id && opp.landing_contact_id) {
        customerPipeline.landing_contact_id = Number(opp.landing_contact_id)
      }
      if (!customerPipeline.erp_customer_name && opp.company) {
        customerPipeline.erp_customer_name = String(opp.company)
      }
    }
    if (quote && typeof quote === 'object') {
      customerPipeline.crm_quote_id = Number(quote.id || 0)
      crmQuoteStatus.value = String(quote.status || '')
      crmQuoteSummary.value = String(quote.summary || '')
    }
    const inv = crm?.invoice
    if (inv && typeof inv === 'object') {
      invoiceNo.value = String(inv.invoice_no || '')
      customerPipeline.crm_invoice_id = Number(inv.id || 0)
    }
    const del = crm?.delivery
    if (del && typeof del === 'object' && stageRank(currentStageId.value) >= stageRank('signed')) {
      let milestones: unknown[] = []
      try {
        milestones = JSON.parse(String(del.milestones_json || '[]'))
      } catch {
        milestones = []
      }
      applyDeliveryFromDoc({
        delivery: {
          expected_delivery_at: del.expected_delivery_at,
          milestones,
          progress_percent: del.progress_percent,
        },
      })
    }
  }

  async function syncCrmRecord() {
    if (!selectedUserId.value) return
    crmSyncLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/crm/sync`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const data = (res as { data?: { pipeline?: Record<string, unknown>; crm?: Record<string, unknown> } })?.data
      if (data?.pipeline) applyPipelineFromDoc(data.pipeline)
      applyCrmBundle(data?.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : 'CRM 同步失败')
    } finally {
      crmSyncLoading.value = false
    }
  }

  async function repairCrmRecord() {
    if (!selectedUserId.value) return
    crmRepairLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/pipeline/repair-crm`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const body = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown>; crm?: Record<string, unknown> } }
      if (body.success === false) {
        throw new Error(body.error || 'CRM/ERP 修复失败')
      }
      const data = body.data
      if (data?.pipeline) applyPipelineFromDoc(data.pipeline, { resetDraft: true })
      applyCrmBundle(data?.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
      await appAlert('CRM/ERP 已修复并写回 pipeline')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : 'CRM/ERP 修复失败')
    } finally {
      crmRepairLoading.value = false
    }
  }

  async function pushExternalCrm() {
    if (!selectedUserId.value) return
    externalCrmPushLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/crm/push-external`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
      if (!payload?.success) {
        await appAlert(payload?.error || '推送失败')
        return
      }
      if (payload.data?.pipeline) applyPipelineFromDoc(payload.data.pipeline)
      await appAlert(externalCrmStatusLabel.value || '已提交外部 CRM 推送')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '推送失败')
    } finally {
      externalCrmPushLoading.value = false
    }
  }

  async function pullExternalCrm() {
    if (!selectedUserId.value) return
    externalCrmPullLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/crm/pull-external`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const payload = res as {
        success?: boolean
        error?: string
        data?: { pipeline?: Record<string, unknown> }
      }
      if (!payload?.success) {
        await appAlert(payload?.error || '拉取失败')
        return
      }
      if (payload.data?.pipeline) applyPipelineFromDoc(payload.data.pipeline, { resetDraft: true })
      await appAlert(externalCrmPullStatusLabel.value || '已从外部 CRM 拉取阶段')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '拉取失败')
    } finally {
      externalCrmPullLoading.value = false
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
    await finalizeIntakeFromPipeline({ silent: true })
  }

  async function loadPipelineForCustomer() {
    if (!selectedUserId.value) return
    try {
      await syncDemandFormFromMarket()
      const data = await fetchPipelineFromServer({ autoAdvance: true })
      if (!data) return
      pipelineStages.value = data.stages
      applyPipelineFromDoc(data.pipeline)
      applyCrmBundle(data.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
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
        applyDeliveryFromDoc(p)
        syncSummaryFromPipeline(selectedUserId.value)
      } else {
        await loadPipelineForCustomer()
      }
      if (
        stageRank(stage) >= stageRank('intake_done')
        && (!customerPipeline.crm_opportunity_id || !customerPipeline.crm_quote_id)
      ) {
        await syncCrmRecord()
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
        intake_sent: customerPipeline.intake_sent || Boolean(demandIntake.messageText),
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
        applyDeliveryFromDoc(p)
        applyCrmBundle(data?.crm)
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
    syncDemandIntakeClientNameFromPipeline()
    customerPipeline.software_delivery_sent_at = String(p.software_delivery_sent_at || '')
    customerPipeline.software_delivery_os = String(p.software_delivery_os || '')
    ;(customerPipeline as unknown as { external_crm_last_result?: unknown }).external_crm_last_result =
      p.external_crm_last_result
    ;(customerPipeline as unknown as { external_crm_last_pull_result?: unknown }).external_crm_last_pull_result =
      p.external_crm_last_pull_result
    const ds = p.delivery_signoff
    customerPipeline.delivery_signoff =
      ds && typeof ds === 'object' ? { ...(ds as { id?: number; status?: string }) } : null
    applyDeliveryFromDoc(p)
    const qd = p.quote_draft
    if (qd && typeof qd === 'object') {
      crmQuoteStatus.value = String((qd as { status?: string }).status || '')
      crmQuoteSummary.value = String((qd as { summary?: string }).summary || '')
    }
  }

  // ---- 签收 ----
  async function requestDeliverySignoff() {
    if (!selectedUserId.value) return
    signoffLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/delivery/signoff/request`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
      if (p) applyPipelineFromDoc(p, { resetDraft: true })
      await appAlert('已发起签收请求')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '发起签收失败')
    } finally {
      signoffLoading.value = false
    }
  }

  async function confirmDeliverySignoff() {
    if (!selectedUserId.value) return
    const sid = Number(customerPipeline.delivery_signoff?.id || 0)
    if (!sid) return
    signoffLoading.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/delivery/signoff/confirm`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        signoff_id: sid,
      })
      const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
      if (p) applyPipelineFromDoc(p, { resetDraft: true })
      await appAlert('签收已确认，阶段已更新为「已交付」')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '确认签收失败')
    } finally {
      signoffLoading.value = false
    }
  }

  // ---- 需求采集 / 官网表单 ----
  async function loadIntakeFormLink() {
    if (!selectedUserId.value) return
    intakeLinkLoading.value = true
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/demand-form/link`, {
        market_user_id: selectedUserId.value,
        client_name: intakePrefillGreetingName(),
        brief: demandIntake.brief.trim(),
      })
      const url = String((res as { data?: { form_url?: string } })?.data?.form_url || '')
      if (url) {
        intakeQuickFormUrl.value = url
        if (!demandIntake.signedFormUrl) demandIntake.signedFormUrl = url
      }
    } catch {
      /* ignore */
    } finally {
      intakeLinkLoading.value = false
    }
  }

  async function ensureIntakeFormUrl(): Promise<string> {
    if (intakeQuickFormUrl.value) return intakeQuickFormUrl.value
    if (demandIntake.signedFormUrl) {
      intakeQuickFormUrl.value = demandIntake.signedFormUrl
      return intakeQuickFormUrl.value
    }
    await loadIntakeFormLink()
    return intakeQuickFormUrl.value || demandIntake.signedFormUrl || ''
  }

  async function openOfficialIntakeForm() {
    const url = await ensureIntakeFormUrl()
    if (!url) {
      await appAlert('请先填写业务背景并生成话术，或稍候链接生成完成')
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  async function copyIntakeFormUrl() {
    const url = await ensureIntakeFormUrl()
    if (!url) {
      await appAlert('暂无表单链接，请稍候重试')
      return
    }
    try {
      await navigator.clipboard.writeText(url)
      await appAlert('已复制官网表单链接')
    } catch {
      await appAlert('复制失败')
    }
  }

  async function loadIntakeNoticeMessage() {
    if (!selectedUserId.value) return
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/demand-form/notice-message`, {
        market_user_id: selectedUserId.value,
        client_name: intakePrefillGreetingName(),
        brief: demandIntake.brief.trim(),
      })
      const data = (res as { data?: { message?: string; form_url?: string } })?.data
      if (data?.message) demandIntake.messageText = data.message
      if (data?.form_url) {
        intakeQuickFormUrl.value = data.form_url
        demandIntake.signedFormUrl = data.form_url
      }
    } catch {
      /* ignore */
    }
  }

  async function fetchIntakeFormByAuditCode() {
    if (!selectedUserId.value) return
    const code = intakeAuditCode.value.trim()
    if (!code) {
      auditCodeError.value = '请填写客户提交的审核码'
      return
    }
    auditCodeError.value = ''
    auditCodeFetching.value = true
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/demand-form/by-audit-code`, {
        audit_code: code,
        market_user_id: selectedUserId.value,
      })
      const ok = Boolean((res as { success?: boolean })?.success)
      if (!ok) {
        auditCodeError.value = String((res as { error?: string })?.error || '获取失败')
        intakeAuditPreview.value = null
        return
      }
      const sub = (res as { data?: { submission?: Record<string, unknown> } })?.data?.submission
      if (!sub || typeof sub !== 'object') {
        auditCodeError.value = '未返回表单内容'
        intakeAuditPreview.value = null
        return
      }
      intakeAuditPreview.value = sub
      intakeAuditPreviewCode.value = String(sub.audit_code || code).trim()
      intakeAuditPreviewAt.value = String(sub.submitted_at || sub.created_at || '').trim()
    } catch (e) {
      auditCodeError.value = e instanceof Error ? e.message : String(e)
      intakeAuditPreview.value = null
    } finally {
      auditCodeFetching.value = false
    }
  }

  async function redeemIntakeAuditCode() {
    if (!selectedUserId.value) return
    const code = intakeAuditCode.value.trim()
    if (!code) {
      auditCodeError.value = '请填写客户提交的审核码'
      return
    }
    if (!intakeAuditPreview.value) {
      await fetchIntakeFormByAuditCode()
      if (!intakeAuditPreview.value) return
    }
    auditCodeError.value = ''
    auditCodeRedeeming.value = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/demand-form/redeem-code`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        audit_code: code,
      })
      const ok = Boolean((res as { success?: boolean })?.success)
      if (!ok) {
        auditCodeError.value = String((res as { error?: string })?.error || '校验失败')
        return
      }
      const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
      if (p) {
        applyPipelineFromDoc(p)
        syncSummaryFromPipeline(selectedUserId.value)
      }
      await loadEnterpriseUsers()
      await maybeAutoAdvancePipelineStage()
      await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
      const nextLabel = stageLabel(customerPipeline.stage)
      const renamed = customerPipeline.username || selectedEnterpriseUser.value?.username || ''
      const entHint = renamed ? `；客户名已更新为「${renamed}」` : ''
      await appAlert(`已关联需求单，当前阶段：${nextLabel}${entHint}`)
      intakeAuditCode.value = ''
      intakeAuditPreview.value = null
      intakeAuditPreviewCode.value = ''
      intakeAuditPreviewAt.value = ''
    } catch (e) {
      auditCodeError.value = e instanceof Error ? e.message : String(e)
    } finally {
      auditCodeRedeeming.value = false
    }
  }

  async function syncDemandFormFromMarket() {
    if (!selectedUserId.value) return
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/demand-form/status`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
      if (p) {
        applyPipelineFromDoc(p)
        if (p.enterprise_auto_provisioned_at) {
          await loadEnterpriseUsers()
          syncSummaryFromPipeline(selectedUserId.value)
        }
      }
    } catch {
      /* 轮询失败时仍用本地 pipeline */
    }
  }

  async function finalizeIntakeFromPipeline(opts: { silent?: boolean } = {}) {
    if (!selectedUserId.value) return
    intakeFinalizeLoading.value = true
    try {
      await syncDemandFormFromMarket()
      const res = await post(`${CS_BRIDGE}/user-cs/demand-form/finalize`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const payload = res as {
        success?: boolean
        error?: string
        data?: { pipeline?: Record<string, unknown>; finalize?: Record<string, unknown> }
      }
      if (!payload?.success) {
        if (!opts.silent) await appAlert(payload?.error || '同步失败')
        return
      }
      const p = payload.data?.pipeline
      if (p) {
        applyPipelineFromDoc(p, { resetDraft: true })
        syncSummaryFromPipeline(selectedUserId.value)
      }
      if (opts.silent) return
      const erpName = customerPipeline.erp_customer_name
      const msg = erpName ? `已关联 ERP 客户：${erpName}` : '已同步 CRM 漏斗'
      await appAlert(msg)
    } catch (e) {
      if (!opts.silent) await appAlert(e instanceof Error ? e.message : '同步 CRM 失败')
    } finally {
      intakeFinalizeLoading.value = false
    }
  }

  async function generateDemandIntake() {
    if (!demandIntake.brief.trim()) return
    demandIntake.loading = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/demand-intake`, {
        brief: demandIntake.brief.trim(),
        client_name: intakePrefillGreetingName(),
        form_url: demandIntake.formUrl.trim(),
        channel: 'internal',
        market_user_id: selectedUserId.value ?? undefined,
      })
      const payload = (res as { data?: { ok?: boolean; items?: Array<Record<string, string>>; error?: string } })?.data
      if (!payload?.ok) {
        await appAlert(payload?.error || '生成失败')
        return
      }
      demandIntake.messageText = String(payload.items?.[0]?.message_text || '')
      const signed = String(
        (payload as { form_url?: string }).form_url
          || payload.items?.[0]?.form_url
          || '',
      )
      if (signed) {
        demandIntake.signedFormUrl = signed
        intakeQuickFormUrl.value = signed
      }
      customerPipeline.intake_sent = true
      customerPipeline.stage = 'intake'
      if (selectedUserId.value) syncSummaryFromPipeline(selectedUserId.value)
      await loadPipelineForCustomer()
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
    } finally {
      demandIntake.loading = false
    }
  }

  async function copyDemandMessage() {
    if (!demandIntake.messageText) return
    try {
      await navigator.clipboard.writeText(demandIntake.messageText)
      await appAlert('已复制')
    } catch {
      await appAlert('复制失败')
    }
  }

  // ---- 合同 ----
  async function loadContractFields() {
    if (!selectedUserId.value) return
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/contract/fields`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const values = (res as { data?: { values?: Record<string, string> } })?.data?.values || {}
      contractForm.party_a_name = values.party_a_name || selectedEnterpriseUser.value?.username || ''
      contractForm.party_a_credit_code = values.party_a_credit_code || ''
      contractForm.total_amount_number = values.total_amount_number || ''
      contractForm.expected_out_trade_no =
        values.expected_out_trade_no || values.out_trade_no || ''
      contractForm.sign_date = values.sign_date?.slice(0, 10) || ''
      contractForm.main_function_list = values.main_function_list || ''
    } catch {
      /* ignore */
    }
  }

  function contractFieldValues() {
    return {
      party_a_name: contractForm.party_a_name.trim(),
      party_a_credit_code: contractForm.party_a_credit_code.trim(),
      total_amount_number: contractForm.total_amount_number.trim(),
      expected_out_trade_no: contractForm.expected_out_trade_no.trim(),
      sign_date: contractForm.sign_date,
      main_function_list: contractForm.main_function_list.trim(),
    }
  }

  async function saveContractFields(opts?: { silent?: boolean }) {
    if (!selectedUserId.value) return
    contractForm.savingFields = true
    try {
      const res = await put(`${CS_BRIDGE}/user-cs/contract/fields`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        values: contractFieldValues(),
      })
      const payload = res as { success?: boolean; error?: string; data?: Record<string, string> }
      if (!payload?.success) {
        if (!opts?.silent) await appAlert(payload?.error || '保存失败')
        return
      }
      await loadPipelineForCustomer()
      if (!opts?.silent) await appAlert('合同字段已保存（含关联订单号，将用于到款核对）')
    } catch (e) {
      if (!opts?.silent) await appAlert(e instanceof Error ? e.message : '保存合同字段失败')
    } finally {
      contractForm.savingFields = false
    }
  }

  async function generateContract() {
    if (!selectedUserId.value) return
    if (!contractForm.party_a_name.trim() || !contractForm.total_amount_number.trim()) {
      await appAlert('请填写甲方名称和合同金额')
      return
    }
    contractForm.loading = true
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/contract/generate`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        values: contractFieldValues(),
      })
      const data = (res as { data?: Record<string, string> })?.data
      if (!data?.filename) {
        await appAlert('生成失败')
        return
      }
      contractForm.filename = String(data.filename)
      contractForm.downloadUrl = String(data.download_url || '')
      await loadPipelineForCustomer()
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
    } finally {
      contractForm.loading = false
    }
  }

  // ---- 群组话术 ----
  function groupClientDisplayName() {
    const n = intakePrefillGreetingName().trim()
    return n || '您好'
  }

  function groupScriptForStage(): string {
    const name = groupClientDisplayName()
    if (currentStageId.value === 'intake_done') {
      return (
        `${name}，您好！\n\n` +
        '我们已收到并核对您提交的需求信息。请确认目前理解的范围是否准确：\n' +
        '· 实施范围：（请按档案补充）\n' +
        '· 期望交付时间：（请补充）\n' +
        '· 需对接的系统：（请补充）\n\n' +
        '若无补充，我们将在 1 个工作日内于本群发送正式报价方案；有变更请直接在本群回复即可。'
      )
    }
    if (currentStageId.value === 'negotiating') {
      return (
        `${name}，感谢您的反馈。\n\n` +
        '关于价格与交付条件，我们可以在以下范围内协调（请按实际情况修改后发送）：\n' +
        '· 可调整项：范围精简 / 分期交付 / 付款方式等\n' +
        '· 当前方案报价：（请填写金额与说明）\n\n' +
        '您看这样是否可行？确认后我们更新方案并进入合同签署流程。'
      )
    }
    return (
      `${name}，您好！\n\n` +
      '根据目前确认的需求范围，我方初步报价如下（请按实际情况填写后发送）：\n' +
      '· 实施范围：\n' +
      '· 费用：    元（含税/不含税请说明）\n' +
      '· 周期：约    周\n\n' +
      '详细说明见上文/附件。如需调整范围或预算，请在本群直接回复，我们再议。'
    )
  }

  async function copyGroupScript(text: string) {
    if (!text.trim()) return
    try {
      await navigator.clipboard.writeText(text)
      await appAlert('已复制话术')
    } catch {
      await appAlert('复制失败')
    }
  }

  return {
    // 状态
    stageDraft,
    stageSaving,
    pipelineAnalyzing,
    autoStageAdvancing,
    intakeFinalizeLoading,
    signoffLoading,
    demandIntake,
    contractForm,
    deliveryForm,
    paymentStatus,
    paymentOutTradeNo,
    paymentVerification,
    invoiceNo,
    crmQuoteSummary,
    crmQuoteStatus,
    crmSyncLoading,
    crmRepairLoading,
    externalCrmPushLoading,
    externalCrmPullLoading,
    intakeQuickFormUrl,
    intakeLinkLoading,
    intakeAuditCode,
    auditCodeFetching,
    auditCodeRedeeming,
    auditCodeError,
    intakeAuditPreview,
    intakeAuditPreviewCode,
    intakeAuditPreviewAt,
    // 计算
    stageDraftDirty,
    viewingStageId,
    canSavePipelineStage,
    saveStageButtonTitle,
    showIntakeStageShortcuts,
    showQuoteNegotiateActions,
    showCrmLinkagePanel,
    showCrmFinalizeActions,
    showIntakeFunnelWarn,
    externalCrmStatusLabel,
    externalCrmPullStatusLabel,
    showEsignPanel,
    groupScriptActionLabel,
    currentStageGuide,
    nextPipelineStage,
    currentStageChecklistComplete,
    intakeSubmittedAwaitingAdvance,
    showIntakeBlock,
    showContractBlock,
    showDeliveryBlock,
    paymentStatusLabel,
    paymentVerificationLabel,
    clientDesktopOs,
    clientNeedMobile,
    contractSamplePdfUrl,
    intakeSubmissionSummary,
    intakeAuditPreviewRows,
    // 指南
    stageRank,
    stageLabel,
    stageGuideFor,
    stepperItemClass,
    // 函数
    checklistItemDone,
    defaultMilestones,
    recomputeDeliveryProgress,
    onMilestoneToggle,
    saveDeliveryPlan,
    checkPaymentAndInvoice,
    syncSummaryFromPipeline,
    loadClientSummary,
    loadPipelineForCustomer,
    pickPipelineStageDraft,
    savePipelineStage,
    analyzeCustomerProgress,
    applyPipelineFromDoc,
    applyDeliveryFromDoc,
    applyCrmBundle,
    requestDeliverySignoff,
    confirmDeliverySignoff,
    syncCrmRecord,
    repairCrmRecord,
    pushExternalCrm,
    pullExternalCrm,
    loadIntakeFormLink,
    openOfficialIntakeForm,
    copyIntakeFormUrl,
    fetchIntakeFormByAuditCode,
    redeemIntakeAuditCode,
    syncDemandFormFromMarket,
    finalizeIntakeFromPipeline,
    generateDemandIntake,
    copyDemandMessage,
    loadContractFields,
    saveContractFields,
    generateContract,
    groupScriptForStage,
    copyGroupScript,
    intakePrefillGreetingName,
    syncDemandIntakeClientNameFromPipeline,
    loadIntakeNoticeMessage,
  }
}