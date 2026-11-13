import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import { AUTO_ADVANCE_CHECKLIST_STAGES, type PhaseCheckKey } from './usePipelineGuide'
import type { WorkbenchCtx } from './workbenchContext'

type ChecklistDep = {
  viewingStageId: ComputedRef<string>
  currentStageGuide: ComputedRef<{ checklist: Array<{ key: PhaseCheckKey; text: string }> }>
  stageDraftDirty: ComputedRef<boolean>
}

/** 阶段清单完成度判断。 */
export function useWorkbenchChecklist(ctx: WorkbenchCtx, dep: ChecklistDep) {
  const {
    deps,
    guide,
    stageDraft,
    demandIntake,
    deliveryForm,
    paymentStatus,
    crmQuoteStatus,
    invoiceNo,
    contractForm,
  } = ctx
  const { stageDraftDirty, viewingStageId, currentStageGuide } = dep
  const { customerPipeline, currentStageId } = deps
  const { stageRank } = guide

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

  return {
    checklistItemDone,
    currentStageChecklistComplete,
    intakeSubmittedAwaitingAdvance,
  }
}