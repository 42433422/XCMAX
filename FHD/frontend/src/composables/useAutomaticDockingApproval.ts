import { approvalApi } from '@/api/approval'
import { captureAuthSession } from '@/utils/authSessionCache'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { useApprovalMode } from './useApprovalMode'

export type DockingApprovalBatch = {
  success?: boolean; batch_id?: string; status?: string; approval_id?: number; approval_request_id?: string
}
type Outcome = { attempted: boolean; accepted: boolean; message?: string }
const attempts = new Map<string, Promise<Outcome>>()
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}

/** The UI preference submits the normal authorized approval, never bypasses its policy. */
export async function approveDockingIfAutomatic(batch: DockingApprovalBatch, isCurrent: () => boolean): Promise<Outcome> {
  const { state } = useApprovalMode()
  const identity = getRuntimeTenantStorageScopeInput()
  const userId = Number(identity?.localUserId), tenantId = Number(identity?.tenantId)
  const session = captureAuthSession()
  const active = () => isCurrent() && session() && state.enabled && state.mode === 'auto'
    && Number(getRuntimeTenantStorageScopeInput()?.localUserId) === userId && Number(getRuntimeTenantStorageScopeInput()?.tenantId) === tenantId
  if (!active() || !Number.isSafeInteger(userId) || userId <= 0 || !Number.isSafeInteger(tenantId) || tenantId <= 0
    || batch.success === false || batch.status !== 'awaiting_approval') return { attempted: false, accepted: false }
  if (!Number.isSafeInteger(batch.approval_id) || !batch.approval_id || !batch.approval_request_id || !batch.batch_id) {
    return { attempted: false, accepted: false, message: '审批标识不完整，请到审批工作台核对。' }
  }
  const key = JSON.stringify([tenantId, userId, batch.approval_id, batch.approval_request_id, batch.batch_id])
  const previous = attempts.get(key)
  if (previous) return previous
  // Retain unknown/denied attempts: an automatic retry could replay a committed operation.
  if (attempts.size >= 500) return { attempted: false, accepted: false, message: '本次会话自动审批已达上限，请到审批工作台核对。' }
  const attempt = (async (): Promise<Outcome> => {
    let submitted = false
    try {
      const details = record(await approvalApi.getRequestDetails(batch.approval_id!))
      const request = record(details.data), business = record(request.business_data)
      if (!active()) return { attempted: false, accepted: false }
      if (details.success !== true || request.id !== batch.approval_id || request.request_no !== batch.approval_request_id
        || request.applicant_id !== userId || request.business_type !== 'workflow_tool'
        || business.tool_id !== 'data_docking' || business.action !== 'auto_ingest'
        || record(business.params).batch_id !== batch.batch_id || request.status !== 'pending') {
        return { attempted: false, accepted: false, message: '审批身份、任务或状态不匹配，请核对原审批。' }
      }
      submitted = true
      const result = record(await approvalApi.approve(batch.approval_id!, userId, '自动审批模式：确认本次已保存模板的数据对接入库'))
      if (!active()) return { attempted: true, accepted: false }
      const receipt = record(result.data)
      if ((result.success === true || result.accepted === true) && receipt.id === batch.approval_id
        && receipt.request_no === batch.approval_request_id && receipt.status === 'approved') {
        return { attempted: true, accepted: true }
      }
      return { attempted: true, accepted: false, message: String(result.message || '自动审批未确认，请到审批工作台核对；不会自动重试。') }
    } catch {
      return { attempted: submitted, accepted: false, message: '自动审批结果待核对；不会自动重试，请查看原审批和入库进度。' }
    }
  })()
  attempts.set(key, attempt)
  return attempt
}
