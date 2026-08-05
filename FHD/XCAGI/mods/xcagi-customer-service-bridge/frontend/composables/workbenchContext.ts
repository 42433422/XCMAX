import { reactive, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { usePipelineGuide } from './usePipelineGuide'
import type { WorkbenchDeps } from './useCustomerWorkbench'

export const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

export type Milestone = { id: string; label: string; weight: number; done: boolean }

export type DemandIntakeState = {
  brief: string
  clientName: string
  formUrl: string
  signedFormUrl: string
  messageText: string
  loading: boolean
}

export type ContractFormState = {
  party_a_name: string
  party_a_credit_code: string
  total_amount_number: string
  expected_out_trade_no: string
  sign_date: string
  main_function_list: string
  loading: boolean
  savingFields: boolean
  filename: string
  downloadUrl: string
}

export type DeliveryFormState = {
  expected_delivery_at: string
  milestones: Milestone[]
  progress_percent: number
  saving: boolean
  checkingPayment: boolean
}

export type CrmBundle = {
  opportunity?: Record<string, unknown>
  quote?: Record<string, unknown>
  invoice?: { id?: number; invoice_no?: string }
  delivery?: { expected_delivery_at?: string; milestones_json?: string; progress_percent?: number }
}

/**
 * 工作台共享上下文：集中持有全部响应式状态、guide，以及跨子组合式交叉调用的函数槽。
 * 函数槽由各 owner 子组合式在初始化时填充，运行期（用户操作）才被调用，顺序安全。
 */
export type WorkbenchCtx = {
  deps: WorkbenchDeps
  guide: ReturnType<typeof usePipelineGuide>
  // ---- 状态 ----
  stageDraft: Ref<string>
  stageSaving: Ref<boolean>
  pipelineAnalyzing: Ref<boolean>
  autoStageAdvancing: Ref<boolean>
  intakeFinalizeLoading: Ref<boolean>
  signoffLoading: Ref<boolean>
  intakeAutoFinalizeAttempted: Ref<number>
  demandIntake: DemandIntakeState
  contractForm: ContractFormState
  deliveryForm: DeliveryFormState
  paymentStatus: Ref<string>
  paymentOutTradeNo: Ref<string>
  paymentVerification: Ref<string>
  invoiceNo: Ref<string>
  crmQuoteSummary: Ref<string>
  crmQuoteStatus: Ref<string>
  crmSyncLoading: Ref<boolean>
  crmRepairLoading: Ref<boolean>
  externalCrmPushLoading: Ref<boolean>
  externalCrmPullLoading: Ref<boolean>
  intakeQuickFormUrl: Ref<string>
  intakeLinkLoading: Ref<boolean>
  intakeAuditCode: Ref<string>
  auditCodeFetching: Ref<boolean>
  auditCodeRedeeming: Ref<boolean>
  auditCodeError: Ref<string>
  intakeAuditPreview: Ref<Record<string, unknown> | null>
  intakeAuditPreviewCode: Ref<string>
  intakeAuditPreviewAt: Ref<string>
  // ---- 跨域计算（由 payment-crm 填充） ----
  externalCrmStatusLabel: ComputedRef<string>
  externalCrmPullStatusLabel: ComputedRef<string>
  // ---- 跨域函数槽 ----
  applyPipelineFromDoc: (p: Record<string, unknown>, opts?: { resetDraft?: boolean }) => void
  applyDeliveryFromDoc: (p: Record<string, unknown>) => void
  applyCrmBundle: (crm: CrmBundle | null | undefined) => void
  syncSummaryFromPipeline: (userId: number, loginUsername?: string) => void
  loadClientSummary: (userId: number, username?: string) => Promise<void>
  loadPipelineForCustomer: () => Promise<void>
  maybeAutoAdvancePipelineStage: () => Promise<void>
  syncDemandIntakeClientNameFromPipeline: () => void
  intakePrefillGreetingName: () => string
  saveContractFields: (opts?: { silent?: boolean }) => Promise<void>
  syncDemandFormFromMarket: () => Promise<void>
  finalizeIntakeFromPipeline: (opts?: { silent?: boolean }) => Promise<void>
  syncCrmRecord: () => Promise<void>
}

export function createWorkbenchContext(deps: WorkbenchDeps): WorkbenchCtx {
  const guide = usePipelineGuide(deps.pipelineStages, deps.currentStageId)
  const ctx = {
    deps,
    guide,
    stageDraft: ref('idle'),
    stageSaving: ref(false),
    pipelineAnalyzing: ref(false),
    autoStageAdvancing: ref(false),
    intakeFinalizeLoading: ref(false),
    signoffLoading: ref(false),
    intakeAutoFinalizeAttempted: ref(0),
    demandIntake: reactive({
      brief: '',
      clientName: '',
      formUrl: 'https://xiu-ci.com/contact.html',
      signedFormUrl: '',
      messageText: '',
      loading: false,
    }),
    contractForm: reactive({
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
    }),
    deliveryForm: reactive({
      expected_delivery_at: '',
      milestones: [] as Milestone[],
      progress_percent: 0,
      saving: false,
      checkingPayment: false,
    }),
    paymentStatus: ref(''),
    paymentOutTradeNo: ref(''),
    paymentVerification: ref(''),
    invoiceNo: ref(''),
    crmQuoteSummary: ref(''),
    crmQuoteStatus: ref(''),
    crmSyncLoading: ref(false),
    crmRepairLoading: ref(false),
    externalCrmPushLoading: ref(false),
    externalCrmPullLoading: ref(false),
    intakeQuickFormUrl: ref(''),
    intakeLinkLoading: ref(false),
    intakeAuditCode: ref(''),
    auditCodeFetching: ref(false),
    auditCodeRedeeming: ref(false),
    auditCodeError: ref(''),
    intakeAuditPreview: ref<Record<string, unknown> | null>(null),
    intakeAuditPreviewCode: ref(''),
    intakeAuditPreviewAt: ref(''),
  } as unknown as WorkbenchCtx
  return ctx
}