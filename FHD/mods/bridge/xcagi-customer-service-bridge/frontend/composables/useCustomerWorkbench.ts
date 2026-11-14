import type { ComputedRef, Ref } from 'vue'
import type { ClientSummaries, EnterpriseUserRow, IntakeFormFields } from './internalCsTypes'
import { createWorkbenchContext } from './workbenchContext'
import { usePipelineStage } from './usePipelineStage'
import { useIntakeDemand } from './useIntakeDemand'
import { useContractDelivery } from './useContractDelivery'
import { usePaymentCrm } from './usePaymentCrm'
import { useWorkbenchChecklist } from './useWorkbenchChecklist'
import { useGroupScripts } from './useGroupScripts'

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

export type WorkbenchDeps = {
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
 * 内部客服「客户工作台」域薄编排器：创建共享上下文并委派给各子组合式，
 * 汇总返回与重组前完全一致的键集合。
 */
export function useCustomerWorkbench(deps: WorkbenchDeps) {
  const ctx = createWorkbenchContext(deps)

  const pipeline = usePipelineStage(ctx)
  const intake = useIntakeDemand(ctx)
  const contractDelivery = useContractDelivery(ctx)
  const paymentCrm = usePaymentCrm(ctx)
  const checklist = useWorkbenchChecklist(ctx, {
    viewingStageId: pipeline.viewingStageId,
    currentStageGuide: pipeline.currentStageGuide,
    stageDraftDirty: pipeline.stageDraftDirty,
  })
  const groupScripts = useGroupScripts(ctx)

  const { stageRank, stageLabel, stageGuideFor, stepperItemClass } = ctx.guide

  return {
    // 状态
    stageDraft: ctx.stageDraft,
    stageSaving: ctx.stageSaving,
    pipelineAnalyzing: ctx.pipelineAnalyzing,
    autoStageAdvancing: ctx.autoStageAdvancing,
    intakeFinalizeLoading: ctx.intakeFinalizeLoading,
    signoffLoading: ctx.signoffLoading,
    demandIntake: ctx.demandIntake,
    contractForm: ctx.contractForm,
    deliveryForm: ctx.deliveryForm,
    paymentStatus: ctx.paymentStatus,
    paymentOutTradeNo: ctx.paymentOutTradeNo,
    paymentVerification: ctx.paymentVerification,
    invoiceNo: ctx.invoiceNo,
    crmQuoteSummary: ctx.crmQuoteSummary,
    crmQuoteStatus: ctx.crmQuoteStatus,
    crmSyncLoading: ctx.crmSyncLoading,
    crmRepairLoading: ctx.crmRepairLoading,
    externalCrmPushLoading: ctx.externalCrmPushLoading,
    externalCrmPullLoading: ctx.externalCrmPullLoading,
    intakeQuickFormUrl: ctx.intakeQuickFormUrl,
    intakeLinkLoading: ctx.intakeLinkLoading,
    intakeAuditCode: ctx.intakeAuditCode,
    auditCodeFetching: ctx.auditCodeFetching,
    auditCodeRedeeming: ctx.auditCodeRedeeming,
    auditCodeError: ctx.auditCodeError,
    intakeAuditPreview: ctx.intakeAuditPreview,
    intakeAuditPreviewCode: ctx.intakeAuditPreviewCode,
    intakeAuditPreviewAt: ctx.intakeAuditPreviewAt,
    // 计算 / 函数（子组合式）
    ...pipeline,
    ...intake,
    ...paymentCrm,
    ...contractDelivery,
    ...checklist,
    ...groupScripts,
    // 指南
    stageRank,
    stageLabel,
    stageGuideFor,
    stepperItemClass,
  }
}