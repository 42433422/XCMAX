import { computed } from 'vue'
import { get, post } from '@/api'
import { appAlert } from '@/utils/appDialog'
import {
  formatAuditCodeFromLandingId,
  intakeFormPreviewRows,
} from './useCustomerServiceFormat'
import { CS_BRIDGE, type WorkbenchCtx } from './workbenchContext'

type IntakeStageForm = {
  name?: string
  company?: string
  email?: string
  phone?: string
  message?: string
  landing_contact_id?: unknown
}

/** 需求采集：官网表单链接、话术、审核码拉取/兑换、finalize。 */
export function useIntakeDemand(ctx: WorkbenchCtx) {
  const {
    deps,
    guide,
    demandIntake,
    intakeQuickFormUrl,
    intakeLinkLoading,
    intakeAuditCode,
    auditCodeFetching,
    auditCodeRedeeming,
    auditCodeError,
    intakeAuditPreview,
    intakeAuditPreviewCode,
    intakeAuditPreviewAt,
    intakeFinalizeLoading,
  } = ctx
  const {
    selectedUserId,
    selectedEnterpriseUser,
    customerPipeline,
    currentStageId,
    loadEnterpriseUsers,
  } = deps
  const { stageRank, stageLabel } = guide

  // ---- computed ----
  const showIntakeStageShortcuts = computed(
    () => currentStageId.value === 'intake' || currentStageId.value === 'intake_done',
  )

  const showQuoteNegotiateActions = computed(() => {
    const id = currentStageId.value
    return id === 'intake_done' || id === 'quoted' || id === 'negotiating'
  })

  const showIntakeBlock = computed(() => stageRank(currentStageId.value) >= stageRank('connected'))

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
        ctx.applyPipelineFromDoc(p)
        ctx.syncSummaryFromPipeline(selectedUserId.value)
      }
      await loadEnterpriseUsers()
      await ctx.maybeAutoAdvancePipelineStage()
      await ctx.loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
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
        ctx.applyPipelineFromDoc(p)
        if (p.enterprise_auto_provisioned_at) {
          await loadEnterpriseUsers()
          ctx.syncSummaryFromPipeline(selectedUserId.value)
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
        ctx.applyPipelineFromDoc(p, { resetDraft: true })
        ctx.syncSummaryFromPipeline(selectedUserId.value)
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
      if (selectedUserId.value) ctx.syncSummaryFromPipeline(selectedUserId.value)
      await ctx.loadPipelineForCustomer()
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

  // 填充跨域函数槽
  ctx.syncDemandIntakeClientNameFromPipeline = syncDemandIntakeClientNameFromPipeline
  ctx.intakePrefillGreetingName = intakePrefillGreetingName
  ctx.syncDemandFormFromMarket = syncDemandFormFromMarket
  ctx.finalizeIntakeFromPipeline = finalizeIntakeFromPipeline

  return {
    showIntakeStageShortcuts,
    showQuoteNegotiateActions,
    showIntakeBlock,
    intakeSubmissionSummary,
    intakeAuditPreviewRows,
    intakePrefillGreetingName,
    syncDemandIntakeClientNameFromPipeline,
    loadIntakeFormLink,
    openOfficialIntakeForm,
    copyIntakeFormUrl,
    loadIntakeNoticeMessage,
    fetchIntakeFormByAuditCode,
    redeemIntakeAuditCode,
    syncDemandFormFromMarket,
    finalizeIntakeFromPipeline,
    generateDemandIntake,
    copyDemandMessage,
  }
}