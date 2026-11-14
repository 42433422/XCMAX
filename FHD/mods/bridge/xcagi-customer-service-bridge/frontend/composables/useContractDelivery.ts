import { computed } from 'vue'
import { get, post, put } from '@/api'
import { appAlert } from '@/utils/appDialog'
import { CS_BRIDGE, type WorkbenchCtx } from './workbenchContext'

/** 合同、交付计划、签收（e-sign）域。 */
export function useContractDelivery(ctx: WorkbenchCtx) {
  const {
    deps,
    guide,
    contractForm,
    deliveryForm,
    signoffLoading,
    paymentStatus,
    paymentOutTradeNo,
    paymentVerification,
    invoiceNo,
  } = ctx
  const { selectedUserId, selectedEnterpriseUser, customerPipeline, currentStageId } = deps
  const { stageRank } = guide

  // ---- computed ----
  const contractSamplePdfUrl = `${CS_BRIDGE}/user-cs/contract/sample-pdf`

  const showEsignPanel = computed(
    () =>
      stageRank(currentStageId.value) >= stageRank('contract_pending')
      && stageRank(currentStageId.value) <= stageRank('signed'),
  )

  const showContractBlock = computed(() => stageRank(currentStageId.value) >= stageRank('contract_pending'))
  const showDeliveryBlock = computed(() => stageRank(currentStageId.value) >= stageRank('signed'))

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
        ctx.applyPipelineFromDoc(p, { resetDraft: true })
        applyDeliveryFromDoc(p)
      }
      await appAlert(startDelivering ? '交付计划已保存，阶段已更新为「交付中」' : '交付进度已保存')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '保存交付计划失败')
    } finally {
      deliveryForm.saving = false
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
      await ctx.loadPipelineForCustomer()
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
      await ctx.loadPipelineForCustomer()
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
    } finally {
      contractForm.loading = false
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
      if (p) ctx.applyPipelineFromDoc(p, { resetDraft: true })
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
      if (p) ctx.applyPipelineFromDoc(p, { resetDraft: true })
      await appAlert('签收已确认，阶段已更新为「已交付」')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '确认签收失败')
    } finally {
      signoffLoading.value = false
    }
  }

  // 填充跨域函数槽
  ctx.applyDeliveryFromDoc = applyDeliveryFromDoc
  ctx.saveContractFields = saveContractFields

  return {
    contractSamplePdfUrl,
    showEsignPanel,
    showContractBlock,
    showDeliveryBlock,
    clientDesktopOs,
    clientNeedMobile,
    defaultMilestones,
    recomputeDeliveryProgress,
    onMilestoneToggle,
    saveDeliveryPlan,
    applyDeliveryFromDoc,
    loadContractFields,
    saveContractFields,
    generateContract,
    requestDeliverySignoff,
    confirmDeliverySignoff,
  }
}