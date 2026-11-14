import { computed } from 'vue'
import { post } from '@/api'
import { appAlert } from '@/utils/appDialog'
import { CS_BRIDGE, type CrmBundle, type WorkbenchCtx } from './workbenchContext'

/** 支付到款核对、CRM 同步/修复、外部 CRM 推送拉取。 */
export function usePaymentCrm(ctx: WorkbenchCtx) {
  const {
    deps,
    guide,
    deliveryForm,
    contractForm,
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
  } = ctx
  const { selectedUserId, selectedEnterpriseUser, customerPipeline, currentStageId } = deps
  const { stageRank } = guide

  // ---- computed ----
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
        return `已回写为「${guide.stageLabel(String(raw.pipeline_stage || ''))}」`
      }
      return '阶段无变化'
    }
    return String(raw.error || raw.reason || '失败')
  })

  // ---- 到款核对 ----
  async function checkPaymentAndInvoice(force: boolean) {
    if (!selectedUserId.value) return
    if (contractForm.expected_out_trade_no.trim()) {
      await ctx.saveContractFields({ silent: true })
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
        ctx.applyPipelineFromDoc(d.pipeline)
        ctx.applyDeliveryFromDoc(d.pipeline)
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
  function applyCrmBundle(crm: CrmBundle | null | undefined) {
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
      ctx.applyDeliveryFromDoc({
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
      if (data?.pipeline) ctx.applyPipelineFromDoc(data.pipeline)
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
      if (data?.pipeline) ctx.applyPipelineFromDoc(data.pipeline, { resetDraft: true })
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
      if (payload.data?.pipeline) ctx.applyPipelineFromDoc(payload.data.pipeline)
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
      if (payload.data?.pipeline) ctx.applyPipelineFromDoc(payload.data.pipeline, { resetDraft: true })
      await appAlert(externalCrmPullStatusLabel.value || '已从外部 CRM 拉取阶段')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '拉取失败')
    } finally {
      externalCrmPullLoading.value = false
    }
  }

  // 填充跨域函数/计算槽
  ctx.applyCrmBundle = applyCrmBundle
  ctx.syncCrmRecord = syncCrmRecord
  ctx.externalCrmStatusLabel = externalCrmStatusLabel
  ctx.externalCrmPullStatusLabel = externalCrmPullStatusLabel

  return {
    paymentStatusLabel,
    paymentVerificationLabel,
    showCrmLinkagePanel,
    showCrmFinalizeActions,
    showIntakeFunnelWarn,
    externalCrmStatusLabel,
    externalCrmPullStatusLabel,
    checkPaymentAndInvoice,
    applyCrmBundle,
    syncCrmRecord,
    repairCrmRecord,
    pushExternalCrm,
    pullExternalCrm,
  }
}