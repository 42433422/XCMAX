import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '@/api'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { useServiceBridge } from '@/composables/useServiceBridge'

import { useCustomerList } from '@mod-frontend/xcagi-customer-service-bridge/composables/useCustomerList'
import { useCustomerWorkbench, type CustomerPipelineState } from '@mod-frontend/xcagi-customer-service-bridge/composables/useCustomerWorkbench'
import { useChangeRequests } from '@mod-frontend/xcagi-customer-service-bridge/composables/useChangeRequests'
import { useEnterpriseCredentials } from '@mod-frontend/xcagi-customer-service-bridge/composables/useEnterpriseCredentials'
import { useFinanceLedger } from '@mod-frontend/xcagi-customer-service-bridge/composables/useFinanceLedger'
import {
  DEFAULT_PIPELINE_STAGES,
  PHASE_GUIDES,
} from '@mod-frontend/xcagi-customer-service-bridge/composables/usePipelineGuide'
import type { ClientSummaries, EnterpriseUserRow } from '@mod-frontend/xcagi-customer-service-bridge/composables/internalCsTypes'

// 拆分自 InternalCustomerServiceView.vue script（原第 212–588 行）；逻辑逐字迁移，行为不变。
// 视图组件（CustomerFunnelBar 等 8 个）仍在入口 SFC 中导入。
export function useInternalCustomerService() {
  const route = useRoute()

  // ---- 顶栏量化数据 (useServiceBridge) ----
  const { stats, loadStats } = useServiceBridge()

  // ---- 客户列表共享状态 ----
  const enterpriseUsers = ref<EnterpriseUserRow[]>([])
  const loadingEnterpriseUsers = ref(false)
  const expandedClientId = ref<number | null>(null)
  const selectedUserId = ref<number | null>(null)
  const selectedEnterpriseUser = computed<EnterpriseUserRow | null>(() =>
    selectedUserId.value == null
      ? null
      : enterpriseUsers.value.find((u) => u.id === selectedUserId.value) ?? null,
  )
  const clientSummaries = reactive<ClientSummaries>({})

  const customerPipeline = reactive<CustomerPipelineState>({
    stage: 'idle',
    username: '',
    last_message_preview: '',
    intake_sent: false,
    intake_submitted_at: '',
    landing_contact_id: 0,
    intake_form: null,
    erp_customer_id: 0,
    erp_customer_name: '',
    crm_funnel_synced_at: '',
    crm_opportunity_id: 0,
    crm_quote_id: 0,
    crm_db_synced_at: '',
    crm_invoice_id: 0,
    external_crm_deal_id: '',
    external_crm_last_at: '',
    external_crm_last_error: '',
    external_crm_last_pull_at: '',
    external_crm_last_pull_error: '',
    enterprise_auto_provisioned_at: '',
    enterprise_login_username: '',
    enterprise_login_password: '',
    enterprise_credentials_issued_at: '',
    software_delivery_sent_at: '',
    software_delivery_os: '',
    delivery_signoff: null,
  })

  const pipelineStages = ref<Array<{ id: string; label: string }>>([...DEFAULT_PIPELINE_STAGES])
  const currentStageId = computed(() => customerPipeline.stage || 'idle')

  const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

  /** 加载企业客户列表（企业标记或已有 pipeline 档案的市场账号） */
  async function loadEnterpriseUsers() {
    loadingEnterpriseUsers.value = true
    try {
      const [adminRes, clientsRes] = await Promise.all([
        xcmaxAdminApi.listUsers(),
        get<{ data?: { clients?: Array<{ market_user_id: number }> } }>(`${CS_BRIDGE}/user-cs/clients`),
      ])
      const data = adminRes as {
        users?: Array<{ id: number; username: string; email?: string; is_enterprise?: boolean }>
        data?: { users?: Array<{ id: number; username: string; email?: string; is_enterprise?: boolean }> }
      }
      const users = data.users || data.data?.users || []
      const pipelineIds = new Set(
        (clientsRes?.data?.clients || [])
          .map((c) => Number(c.market_user_id))
          .filter((id) => id > 0),
      )
      enterpriseUsers.value = users
        .filter((u) => Boolean(u.is_enterprise) || pipelineIds.has(u.id))
        .map((u) => {
          const isEnterprise = Boolean(u.is_enterprise)
          const hasPipeline = pipelineIds.has(u.id)
          return {
            id: u.id,
            username: u.username,
            email: u.email,
            isEnterprise,
            hasPipeline,
            is_enterprise: isEnterprise,
            has_pipeline: hasPipeline,
          }
        })
        .sort((a, b) => a.username.localeCompare(b.username, 'zh-CN'))
    } catch {
      enterpriseUsers.value = []
    } finally {
      loadingEnterpriseUsers.value = false
    }
  }

  function selectEnterprise(userId: number) {
    selectedUserId.value = userId
  }

  // ---- 子域 composables 编排 ----
  const creds = useEnterpriseCredentials(customerPipeline, selectedUserId, selectedEnterpriseUser)
  const ledger = useFinanceLedger(selectedUserId)
  const changeRequestsApi = useChangeRequests(selectedUserId, selectedEnterpriseUser)

  const workbench = useCustomerWorkbench({
    selectedUserId,
    selectedEnterpriseUser,
    clientSummaries,
    customerPipeline,
    pipelineStages,
    currentStageId,
    syncEnterpriseCredsFromPipeline: creds.syncEnterpriseCredsFromPipeline,
    loadEnterpriseUsers,
    loadChangeRequestsForCustomer: changeRequestsApi.loadChangeRequestsForCustomer,
    loadFinanceLedger: ledger.loadFinanceLedger,
  })

  const list = useCustomerList({
    selectedUserId,
    selectedEnterpriseUser,
    customerPipeline,
    clientSummaries,
    expandedClientId,
    enterpriseUsers,
    loadingEnterpriseUsers,
    loadEnterpriseUsers,
    loadClientSummary: workbench.loadClientSummary,
    loadPipelineForCustomer: workbench.loadPipelineForCustomer,
    selectEnterprise,
  })

  // ---- 从 composables 解构绑定 ----
  // useCustomerWorkbench
  const {
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
    externalCrmStatusLabel,
    externalCrmPullStatusLabel,
    intakeQuickFormUrl,
    intakeLinkLoading,
    intakeAuditCode,
    auditCodeFetching,
    auditCodeRedeeming,
    auditCodeError,
    intakeAuditPreview,
    intakeAuditPreviewCode,
    intakeAuditPreviewAt,
    stageDraftDirty,
    viewingStageId,
    canSavePipelineStage,
    saveStageButtonTitle,
    showIntakeStageShortcuts,
    showQuoteNegotiateActions,
    showCrmLinkagePanel,
    showCrmFinalizeActions,
    showIntakeFunnelWarn,
    showEsignPanel,
    groupScriptActionLabel,
    currentStageGuide,
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
    stageRank,
    stageLabel,
    stageGuideFor,
    stepperItemClass,
    checklistItemDone,
    onMilestoneToggle,
    saveDeliveryPlan,
    checkPaymentAndInvoice,
    loadClientSummary,
    loadPipelineForCustomer,
    pickPipelineStageDraft,
    savePipelineStage,
    analyzeCustomerProgress,
    applyPipelineFromDoc,
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
    syncDemandIntakeClientNameFromPipeline,
    loadIntakeNoticeMessage,
  } = workbench

  // useEnterpriseCredentials
  const {
    enterpriseCreds,
    syncEnterpriseCredsFromPipeline,
    loadEnterpriseCredentials,
    issueEnterpriseCredentials,
    copyEnterpriseCredential,
  } = creds

  // useFinanceLedger
  const { financeLedgerItems, financeLedgerLoading } = ledger

  // useChangeRequests
  const {
    changeRequests,
    changeRequestsLoading,
    changeRequestOpsDispatchingId,
    onChangeRequestStatus,
    dispatchChangeRequestOps,
  } = changeRequestsApi

  // useCustomerList
  const {
    funnelExpanded,
    funnelLoading,
    funnelStages,
    funnelTotalClients,
    funnelStageFilter,
    loadPipelineFunnel,
    toggleFunnelStageFilter,
    getClientSummary,
    displayClientName,
    cardNameTitle,
    filteredEnterpriseUsers,
    loadAllClientSummaries,
    addCustomerModal,
    addCustomerPickerRows,
    isCustomerListed,
    openAddCustomerModal,
    markUserEnterprise,
    focusListedCustomer,
  } = list

  // ---- 视图级辅助 ----
  function progressPercent(userId: number) {
    const stages = pipelineStages.value
    const stage = expandedClientId.value === userId ? customerPipeline.stage : getClientSummary(userId).stage
    const idx = stages.findIndex((s) => s.id === stage)
    if (idx <= 0) return 4
    return Math.round(((idx + 1) / stages.length) * 100)
  }

  function parseMarketUserIdFromRoute(): number | null {
    const raw = route.query.market_user_id
    const n = Number(Array.isArray(raw) ? raw[0] : raw)
    return Number.isFinite(n) && n > 0 ? n : null
  }

  async function toggleClient(userId: number) {
    if (expandedClientId.value === userId) {
      expandedClientId.value = null
      selectedUserId.value = null
      return
    }
    expandedClientId.value = userId
    await selectEnterprise(userId)
    demandIntake.messageText = ''
    demandIntake.signedFormUrl = ''
    intakeQuickFormUrl.value = ''
    intakeAuditCode.value = ''
    auditCodeError.value = ''
    intakeAuditPreview.value = null
    intakeAuditPreviewCode.value = ''
    intakeAuditPreviewAt.value = ''
    await loadPipelineForCustomer()
    syncDemandIntakeClientNameFromPipeline()
    syncEnterpriseCredsFromPipeline()
    void loadEnterpriseCredentials()
    if (customerPipeline.stage === 'intake' || customerPipeline.stage === 'intake_done') {
      void loadIntakeFormLink()
    }
    await loadContractFields()
  }

  async function refresh() {
    await Promise.all([loadStats(), loadEnterpriseUsers(), loadPipelineFunnel()])
    await loadAllClientSummaries()
    if (expandedClientId.value) {
      await loadPipelineForCustomer()
    }
  }

  watch(currentStageId, (stage) => {
    if (stageRank(stage) >= stageRank('contract_pending')) void loadContractFields()
  })

  watch(
    () => currentStageId.value,
    (stage) => {
      if ((stage === 'intake' || stage === 'intake_done') && selectedUserId.value) {
        void loadIntakeFormLink()
        if (stage === 'intake') void loadIntakeNoticeMessage()
      }
    },
  )

  watch(intakeAuditCode, () => {
    auditCodeError.value = ''
    intakeAuditPreview.value = null
    intakeAuditPreviewCode.value = ''
    intakeAuditPreviewAt.value = ''
  })

  watch(
    () => route.query.market_user_id,
    () => {
      const id = parseMarketUserIdFromRoute()
      if (id != null) void toggleClient(id)
    },
  )

  onMounted(async () => {
    await refresh()
    const fromRoute = parseMarketUserIdFromRoute()
    if (fromRoute != null) await toggleClient(fromRoute)
  })

  return {
    stats,
    loadingEnterpriseUsers,
    enterpriseUsers,
    selectedUserId,
    selectedEnterpriseUser,
    customerPipeline,
    pipelineStages,
    currentStageId,
    funnelExpanded,
    funnelLoading,
    funnelStages,
    funnelTotalClients,
    funnelStageFilter,
    toggleFunnelStageFilter,
    filteredEnterpriseUsers,
    expandedClientId,
    toggleClient,
    getClientSummary,
    displayClientName,
    cardNameTitle,
    enterpriseCreds,
    copyEnterpriseCredential,
    issueEnterpriseCredentials,
    loadEnterpriseCredentials,
    stageDraft,
    stageDraftDirty,
    viewingStageId,
    stageRank,
    stageLabel,
    stageGuideFor,
    stepperItemClass,
    currentStageGuide,
    checklistItemDone,
    intakeAuditPreviewRows,
    intakeAuditPreviewCode,
    intakeAuditPreviewAt,
    intakeAuditCode,
    auditCodeError,
    crmQuoteStatus,
    crmQuoteSummary,
    intakeSubmittedAwaitingAdvance,
    autoStageAdvancing,
    showIntakeStageShortcuts,
    showQuoteNegotiateActions,
    showCrmLinkagePanel,
    showCrmFinalizeActions,
    showIntakeFunnelWarn,
    canSavePipelineStage,
    saveStageButtonTitle,
    stageSaving,
    pipelineAnalyzing,
    intakeFinalizeLoading,
    intakeLinkLoading,
    auditCodeFetching,
    auditCodeRedeeming,
    crmSyncLoading,
    crmRepairLoading,
    externalCrmPushLoading,
    externalCrmPullLoading,
    externalCrmStatusLabel,
    externalCrmPullStatusLabel,
    financeLedgerItems,
    financeLedgerLoading,
    groupScriptActionLabel,
    groupScriptForStage,
    pickPipelineStageDraft,
    savePipelineStage,
    openOfficialIntakeForm,
    copyIntakeFormUrl,
    fetchIntakeFormByAuditCode,
    redeemIntakeAuditCode,
    analyzeCustomerProgress,
    finalizeIntakeFromPipeline,
    syncDemandFormFromMarket,
    syncCrmRecord,
    repairCrmRecord,
    pushExternalCrm,
    pullExternalCrm,
    copyGroupScript,
    showIntakeBlock,
    PHASE_GUIDES,
    demandIntake,
    intakeSubmissionSummary,
    generateDemandIntake,
    copyDemandMessage,
    showContractBlock,
    contractForm,
    contractSamplePdfUrl,
    showEsignPanel,
    saveContractFields,
    generateContract,
    applyPipelineFromDoc,
    showDeliveryBlock,
    deliveryForm,
    clientDesktopOs,
    clientNeedMobile,
    paymentStatus,
    paymentStatusLabel,
    paymentOutTradeNo,
    paymentVerification,
    paymentVerificationLabel,
    invoiceNo,
    onMilestoneToggle,
    saveDeliveryPlan,
    checkPaymentAndInvoice,
    requestDeliverySignoff,
    confirmDeliverySignoff,
    signoffLoading,
    changeRequests,
    changeRequestsLoading,
    changeRequestOpsDispatchingId,
    onChangeRequestStatus,
    dispatchChangeRequestOps,
    addCustomerModal,
    addCustomerPickerRows,
    isCustomerListed,
    openAddCustomerModal,
    markUserEnterprise,
    focusListedCustomer,
    progressPercent,
    refresh,
  }
}
