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
// 原超大 SFC 已拆分至 ./internal-customer-service/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装（视图组件在此导入）。
import CustomerFunnelBar from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerFunnelBar.vue'
import CustomerEnterpriseCredsPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerEnterpriseCredsPanel.vue'
import CustomerPipelineProgressPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerPipelineProgressPanel.vue'
import CustomerDemandIntakePanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerDemandIntakePanel.vue'
import CustomerContractPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerContractPanel.vue'
import CustomerDeliveryPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerDeliveryPanel.vue'
import CustomerChangeRequestsPanel from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerChangeRequestsPanel.vue'
import CustomerAddCustomerModal from '@mod-frontend/xcagi-customer-service-bridge/components/CustomerAddCustomerModal.vue'

import type { PhaseCheckKey } from '@mod-frontend/xcagi-customer-service-bridge/composables/usePipelineGuide'
import { useInternalCustomerService } from './internal-customer-service/useInternalCustomerService'

const {
  stats, loadingEnterpriseUsers, enterpriseUsers, selectedUserId, selectedEnterpriseUser,
  customerPipeline, pipelineStages, currentStageId,
  funnelExpanded, funnelLoading, funnelStages, funnelTotalClients, funnelStageFilter,
  toggleFunnelStageFilter, filteredEnterpriseUsers, expandedClientId, toggleClient,
  getClientSummary, displayClientName, cardNameTitle,
  enterpriseCreds, copyEnterpriseCredential, issueEnterpriseCredentials, loadEnterpriseCredentials,
  stageDraft, stageDraftDirty, viewingStageId, stageRank, stageLabel, stageGuideFor,
  stepperItemClass, currentStageGuide, checklistItemDone,
  intakeAuditPreviewRows, intakeAuditPreviewCode, intakeAuditPreviewAt, intakeAuditCode, auditCodeError,
  crmQuoteStatus, crmQuoteSummary, intakeSubmittedAwaitingAdvance, autoStageAdvancing,
  showIntakeStageShortcuts, showQuoteNegotiateActions, showCrmLinkagePanel, showCrmFinalizeActions,
  showIntakeFunnelWarn, canSavePipelineStage, saveStageButtonTitle, stageSaving, pipelineAnalyzing,
  intakeFinalizeLoading, intakeLinkLoading, auditCodeFetching, auditCodeRedeeming,
  crmSyncLoading, crmRepairLoading, externalCrmPushLoading, externalCrmPullLoading,
  externalCrmStatusLabel, externalCrmPullStatusLabel, financeLedgerItems, financeLedgerLoading,
  groupScriptActionLabel, groupScriptForStage,
  pickPipelineStageDraft, savePipelineStage, openOfficialIntakeForm, copyIntakeFormUrl,
  fetchIntakeFormByAuditCode, redeemIntakeAuditCode, analyzeCustomerProgress,
  finalizeIntakeFromPipeline, syncDemandFormFromMarket, syncCrmRecord, repairCrmRecord,
  pushExternalCrm, pullExternalCrm, copyGroupScript,
  showIntakeBlock, PHASE_GUIDES, demandIntake, intakeSubmissionSummary,
  generateDemandIntake, copyDemandMessage,
  showContractBlock, contractForm, contractSamplePdfUrl, showEsignPanel,
  saveContractFields, generateContract, applyPipelineFromDoc,
  showDeliveryBlock, deliveryForm, clientDesktopOs, clientNeedMobile,
  paymentStatus, paymentStatusLabel, paymentOutTradeNo, paymentVerification, paymentVerificationLabel,
  invoiceNo, onMilestoneToggle, saveDeliveryPlan, checkPaymentAndInvoice,
  requestDeliverySignoff, confirmDeliverySignoff, signoffLoading,
  changeRequests, changeRequestsLoading, changeRequestOpsDispatchingId, onChangeRequestStatus,
  dispatchChangeRequestOps,
  addCustomerModal, addCustomerPickerRows, isCustomerListed, openAddCustomerModal,
  markUserEnterprise, focusListedCustomer,
  progressPercent, refresh,
} = useInternalCustomerService()
</script>

<style scoped src="./internal-customer-service/internal-customer-service.css"></style>
