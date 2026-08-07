<template>
  <div class="page-view cs-page" id="view-internal-customer-service">
    <div class="page-content">
      <!-- 顶栏：标题 + 量化数据 + 操作 -->
      <header class="cs-topbar">
        <div class="cs-topbar-left">
          <h2>内部客服</h2>
          <div v-if="stats" class="cs-metrics">
            <span class="cs-metric"><em>{{ stats.pending }}</em> 待受理</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric"><em>{{ stats.processing }}</em> 处理中</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric"><em>{{ stats.resolved }}</em> 已回复</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric muted"><em>{{ stats.total }}</em> 累计</span>
          </div>
        </div>
        <div class="cs-topbar-actions">
          <button class="btn btn-sm btn-secondary" type="button" @click="openAddCustomerModal">添加客户</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="refresh">刷新</button>
        </div>
      </header>

      <CustomerFunnelBar
        :visible="!loadingEnterpriseUsers && enterpriseUsers.length > 0"
        :expanded="funnelExpanded"
        :funnel-loading="funnelLoading"
        :funnel-stages="funnelStages"
        :funnel-total-clients="funnelTotalClients"
        :funnel-stage-filter="funnelStageFilter"
        :stage-label="stageLabel"
        @update:expanded="(v) => (funnelExpanded = v)"
        @select-stage="toggleFunnelStageFilter"
        @clear-filter="() => (funnelStageFilter = '')"
      />

      <div v-if="loadingEnterpriseUsers" class="loading-hint">加载客户…</div>
      <div v-else-if="!enterpriseUsers.length" class="cs-empty">
        <p>暂无企业客户</p>
      </div>

      <div v-else class="cs-clients">
        <article
          v-for="u in filteredEnterpriseUsers"
          :key="u.id"
          class="cs-card"
          :class="{ 'is-open': expandedClientId === u.id }"
        >
          <!-- 收起：仅名字；展开：名字 + 工作台 -->
          <button type="button" class="cs-card-head" @click="toggleClient(u.id)">
            <span class="cs-card-name" :title="cardNameTitle(u)">{{ displayClientName(u) }}</span>
            <span v-if="!u.isEnterprise && u.hasPipeline" class="cs-card-badge">待设企业</span>
            <span
              v-if="getClientSummary(u.id).stage && getClientSummary(u.id).stage !== 'idle'"
              class="cs-card-stage"
            >{{ stageLabel(getClientSummary(u.id).stage) }}</span>
          </button>

          <div v-if="expandedClientId === u.id" class="cs-card-body">
            <CustomerEnterpriseCredsPanel
              :enterprise-creds="enterpriseCreds"
              :selected-user-id="selectedUserId"
              @copy="copyEnterpriseCredential"
              @issue="issueEnterpriseCredentials"
              @load="loadEnterpriseCredentials"
            />

            <CustomerPipelineProgressPanel
              :pipeline-stages="pipelineStages"
              :progress-percent="progressPercent(u.id)"
              :stage-draft="stageDraft"
              :stage-draft-dirty="stageDraftDirty"
              :current-stage-id="currentStageId"
              :viewing-stage-id="viewingStageId"
              :stage-label="stageLabel"
              :stage-rank="stageRank"
              :stepper-item-class="stepperItemClass"
              :stage-guide-for="stageGuideFor"
              :current-stage-guide="currentStageGuide"
              :checklist-item-done="(key: string) => checklistItemDone(key as PhaseCheckKey)"
              :customers="customerPipeline"
              :intake-audit-preview-rows="intakeAuditPreviewRows"
              :intake-audit-preview-code="intakeAuditPreviewCode"
              :intake-audit-preview-at="intakeAuditPreviewAt"
              :intake-audit-code="intakeAuditCode"
              :audit-code-error="auditCodeError"
              :crm-quote-status="crmQuoteStatus"
              :crm-quote-summary="crmQuoteSummary"
              :intake-submitted-awaiting-advance="intakeSubmittedAwaitingAdvance"
              :auto-stage-advancing="autoStageAdvancing"
              :show-intake-stage-shortcuts="showIntakeStageShortcuts"
              :show-quote-negotiate-actions="showQuoteNegotiateActions"
              :show-crm-linkage-panel="showCrmLinkagePanel"
              :show-crm-finalize-actions="showCrmFinalizeActions"
              :show-intake-funnel-warn="showIntakeFunnelWarn"
              :can-save-pipeline-stage="canSavePipelineStage"
              :save-stage-button-title="saveStageButtonTitle"
              :stage-saving="stageSaving"
              :pipeline-analyzing="pipelineAnalyzing"
              :intake-finalize-loading="intakeFinalizeLoading"
              :intake-link-loading="intakeLinkLoading"
              :audit-code-fetching="auditCodeFetching"
              :audit-code-redeeming="auditCodeRedeeming"
              :crm-sync-loading="crmSyncLoading"
              :crm-repair-loading="crmRepairLoading"
              :external-crm-push-loading="externalCrmPushLoading"
              :external-crm-pull-loading="externalCrmPullLoading"
              :external-crm-status-label="externalCrmStatusLabel"
              :external-crm-pull-status-label="externalCrmPullStatusLabel"
              :finance-ledger-items="financeLedgerItems"
              :finance-ledger-loading="financeLedgerLoading"
              :selected-user-id="selectedUserId"
              :group-script-action-label="groupScriptActionLabel"
              :group-script-for-stage="groupScriptForStage"
              :on-pick-stage="pickPipelineStageDraft"
              :on-save-stage="savePipelineStage"
              :on-open-intake-form="openOfficialIntakeForm"
              :on-copy-intake-url="copyIntakeFormUrl"
              :on-fetch-audit="fetchIntakeFormByAuditCode"
              :on-redeem-audit="redeemIntakeAuditCode"
              :on-analyze="analyzeCustomerProgress"
              :on-finalize="() => finalizeIntakeFromPipeline()"
              :on-sync-market="() => syncDemandFormFromMarket()"
              :on-sync-crm="syncCrmRecord"
              :on-repair-crm="repairCrmRecord"
              :on-push-crm="pushExternalCrm"
              :on-pull-crm="pullExternalCrm"
              :on-copy-script="copyGroupScript"
              @update:stageDraft="(v) => (stageDraft = v)"
              @update:intakeAuditCode="(v) => (intakeAuditCode = v)"
            />

            <CustomerDemandIntakePanel
              :show-intake-block="showIntakeBlock"
              :description="PHASE_GUIDES.intake.description"
              :demand-intake="demandIntake"
              :intake-link-loading="intakeLinkLoading"
              :intake-submission-summary="intakeSubmissionSummary"
              :intake-submitted-at="customerPipeline.intake_submitted_at"
              @generate="generateDemandIntake"
              @open-form="openOfficialIntakeForm"
              @copy-message="copyDemandMessage"
            />

            <CustomerContractPanel
              :show-contract-block="showContractBlock"
              :description="PHASE_GUIDES.contract_pending.description"
              :contract-form="contractForm"
              :contract-sample-pdf-url="contractSamplePdfUrl"
              :show-esign-panel="showEsignPanel"
              :selected-user-id="selectedUserId"
              :username="selectedEnterpriseUser?.username || ''"
              :party-a="contractForm.party_a_name || customerPipeline.erp_customer_name"
              @save-fields="saveContractFields"
              @generate="generateContract"
              @apply-pipeline="applyPipelineFromDoc"
            />

            <CustomerDeliveryPanel
              :show-delivery-block="showDeliveryBlock"
              :description="stageGuideFor(currentStageId).description"
              :current-stage-id="currentStageId"
              :delivery-form="deliveryForm"
              :client-desktop-os="clientDesktopOs"
              :client-need-mobile="clientNeedMobile"
              :software-delivery-sent-at="customerPipeline.software_delivery_sent_at"
              :delivery-signoff="customerPipeline.delivery_signoff"
              :stage-saving="stageSaving"
              :signoff-loading="signoffLoading"
              :payment-status="paymentStatus"
              :payment-status-label="paymentStatusLabel"
              :payment-out-trade-no="paymentOutTradeNo"
              :payment-verification="paymentVerification"
              :payment-verification-label="paymentVerificationLabel"
              :invoice-no="invoiceNo"
              @milestone-toggle="onMilestoneToggle"
              @save-plan="saveDeliveryPlan"
              @check-payment="checkPaymentAndInvoice"
              @request-signoff="requestDeliverySignoff"
              @confirm-signoff="confirmDeliverySignoff"
              @mark-delivered="() => savePipelineStage('delivered', { confirmMessage: '确认已全部交付并验收？' })"
            />

            <CustomerChangeRequestsPanel
              :show="stageRank(currentStageId) >= stageRank('signed')"
              :change-requests="changeRequests"
              :loading="changeRequestsLoading"
              :dispatching-id="changeRequestOpsDispatchingId"
              @change-status="onChangeRequestStatus"
              @dispatch-ops="dispatchChangeRequestOps"
            />
          </div>
        </article>
      </div>

      <CustomerAddCustomerModal
        :visible="addCustomerModal.visible"
        :loading="addCustomerModal.loading"
        :filter="addCustomerModal.filter"
        :saving-id="addCustomerModal.savingId"
        :picker-rows="addCustomerPickerRows"
        :is-customer-listed="isCustomerListed"
        @update:visible="(v) => (addCustomerModal.visible = v)"
        @update:filter="(v) => (addCustomerModal.filter = v)"
        @mark-enterprise="markUserEnterprise"
        @open-customer="focusListedCustomer"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '@/api'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { useServiceBridge } from '@/composables/useServiceBridge'

import CustomerFunnelBar from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerFunnelBar.vue'
import CustomerEnterpriseCredsPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerEnterpriseCredsPanel.vue'
import CustomerPipelineProgressPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerPipelineProgressPanel.vue'
import CustomerDemandIntakePanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerDemandIntakePanel.vue'
import CustomerContractPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerContractPanel.vue'
import CustomerDeliveryPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerDeliveryPanel.vue'
import CustomerChangeRequestsPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerChangeRequestsPanel.vue'
import CustomerAddCustomerModal from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerAddCustomerModal.vue'

import { useCustomerList } from '@mod-frontend/xcagi-customer-service-bridge/composables/useCustomerList'
import { useCustomerWorkbench, type CustomerPipelineState } from '@mod-frontend/xcagi-customer-service-bridge/composables/useCustomerWorkbench'
import { useChangeRequests } from '@mod-frontend/xcagi-customer-service-bridge/composables/useChangeRequests'
import { useEnterpriseCredentials } from '@mod-frontend/xcagi-customer-service-bridge/composables/useEnterpriseCredentials'
import { useFinanceLedger } from '@mod-frontend/xcagi-customer-service-bridge/composables/useFinanceLedger'
import {
  DEFAULT_PIPELINE_STAGES,
  PHASE_GUIDES,
  type PhaseCheckKey,
} from '@mod-frontend/xcagi-customer-service-bridge/composables/usePipelineGuide'
import type { ClientSummaries, EnterpriseUserRow } from '@mod-frontend/xcagi-customer-service-bridge/composables/internalCsTypes'

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
</script>

<style scoped>
.cs-page { --cs-accent: #4a6cf7; --cs-border: #e8ecf2; --cs-bg: #f6f8fb; }
.page-content { max-width: 960px; margin: 0 auto; padding: 0 4px; }

.cs-topbar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 0 20px; border-bottom: 1px solid var(--cs-border); margin-bottom: 20px;
}
.cs-topbar-left { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; min-width: 0; }
.cs-topbar h2 { margin: 0; font-size: 18px; font-weight: 600; color: #1a1a2e; white-space: nowrap; }
.cs-metrics { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 13px; color: #64748b; }
.cs-metric em { font-style: normal; font-weight: 700; color: var(--cs-accent); font-size: 15px; margin-right: 2px; }
.cs-metric.muted em { color: #94a3b8; font-weight: 600; }
.cs-metric-sep { color: #cbd5e1; user-select: none; }
.cs-topbar-actions { display: flex; gap: 6px; flex-shrink: 0; }
.btn-ghost { background: transparent; border: 1px solid var(--cs-border); color: #64748b; }
.btn-ghost:hover { border-color: var(--cs-accent); color: var(--cs-accent); }

.cs-clients {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  align-items: start;
}
.cs-card {
  background: #fff; border: 1px solid var(--cs-border); border-radius: 10px;
  overflow: hidden; transition: border-color 0.15s, box-shadow 0.15s;
}
.cs-card.is-open {
  grid-column: 1 / -1;
  border-color: #b8c9ff;
  box-shadow: 0 2px 16px rgba(74, 108, 247, 0.08);
}

.cs-card-head {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; min-height: 44px; padding: 10px 14px;
  border: none; background: none; cursor: pointer; text-align: center;
}
.cs-card-head:hover { background: #f8fafc; }
.cs-card.is-open .cs-card-head {
  justify-content: flex-start;
  border-bottom: 1px solid #f1f5f9;
}
.cs-card-name { font-size: 14px; font-weight: 600; color: #1e293b; }
.cs-card-stage { font-size: 12px; color: var(--cs-accent); font-weight: 400; margin-left: auto; }

.cs-card-body { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }

.cs-esign-panel-wrap {
  margin-top: 12px;
}
.cs-esign-panel {
  margin-top: 12px; padding-top: 12px; border-top: 1px dashed #e2e8f0;
}
.cs-ops-job { font-size: 11px; margin-left: 6px; }

.cs-empty { text-align: center; padding: 48px 16px; color: #94a3b8; }
.loading-hint, .empty-hint { font-size: 12px; color: #94a3b8; margin: 0; }
.cs-card-badge { font-size: 10px; color: #b45309; background: #fff7ed; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }
.cs-tag { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: #f3f4f6; color: #6b7280; }
.cs-tag--ok { background: #ecfdf5; color: #047857; }
.btn-link { background: none; border: none; color: var(--color-primary, #2563eb); cursor: pointer; padding: 0; font-size: inherit; text-decoration: underline; }
</style>