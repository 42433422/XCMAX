import { ref, computed, onScopeDispose, watch, type Ref } from 'vue'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import {
  FINAL_STATUSES, isFinalStatus, getStatusLabel, formatRequestTitle, buildWorkflowExecutionAlert,
} from './awHelpers'

export function useApprovalActions(deps: {
  getCurrentUserId: () => number
  loadData: () => Promise<void>
  closeDetails: () => void
  viewDetails: (requestId: number) => Promise<void>
  initiatedRequests: Ref<ApprovalRequest[]>
}) {
  const {
    getCurrentUserId, loadData, closeDetails, viewDetails, initiatedRequests,
  } = deps

  // 清理
  const cleanupLoading = ref(false)
  const actioningId = ref(0)
  const batchActioning = ref(false)
  let active = true
  const accountScope = () => JSON.stringify([getAuthSessionEpoch(), productReadScopeKey('xcagi-approval-bridge')])
  watch(accountScope, () => { actioningId.value = 0; batchActioning.value = false }, { flush: 'sync' })
  onScopeDispose(() => { active = false })
  const completedInitiatedCount = computed(
    () => initiatedRequests.value.filter((r) => isFinalStatus(r.status)).length
  )

  const approveMessage = (request?: ApprovalRequest) => request?.business_type === 'workflow_tool'
    ? '批准后系统将按审批工作流执行后续业务操作，执行结果会记录在审批详情中。\n\n请输入审批意见：'
    : '请输入审批意见：'

  // 审批操作
  const approve = async (requestId: number, request?: ApprovalRequest) => {
    if (actioningId.value) return
    const scope = accountScope(), userId = getCurrentUserId()
    const current = () => active && scope === accountScope() && userId === getCurrentUserId()
    if (!userId) return
    const opinion = await appPrompt(approveMessage(request), '同意', { title: '审批通过' })
    if (!current() || opinion === null || !String(opinion).trim()) return

    actioningId.value = requestId
    try {
      const res = await approvalApi.approve(requestId, userId, String(opinion).trim())
      if (!current()) return
      if (res.success || res.accepted === true) {
        const updatedRequest = res.data as ApprovalRequest | undefined
        const workflowExecution = updatedRequest?.workflow_execution
        await appAlert(`${res.success ? '审批通过！' : res.message || '审批已受理，执行结果待核对。'}${buildWorkflowExecutionAlert(workflowExecution)}`)
        if (!current()) return
        await loadData()
        if (!current()) return
        if (workflowExecution) await viewDetails(requestId)
        else closeDetails()
      } else {
        // 失败也要刷新：避免列表停留在旧状态，用户反复点击同一个失效单。
        await loadData()
        if (!current()) return
        if (res.expired) {
          await appAlert(res.message || '该审批已失效，已自动关闭，请重新发起任务。')
          closeDetails()
        } else {
          await appAlert('审批失败：' + (res.message || '未知错误'))
        }
      }
    } catch (error) {
      if (current()) { console.error('审批失败:', error); await appAlert('审批结果读取失败，请刷新原审批核对。') }
    } finally {
      if (current()) actioningId.value = 0
    }
  }

  /** 批量通过：同一审批意见依次提交，失败项保留在列表中等待重试。 */
  const approveMany = async (ids: number[]) => {
    if (batchActioning.value || !ids.length) return
    const scope = accountScope(), userId = getCurrentUserId()
    const current = () => active && scope === accountScope() && userId === getCurrentUserId()
    if (!userId) return
    const opinion = await appPrompt(
      `将批量通过 ${ids.length} 条审批，请填写统一审批意见：`,
      '同意',
      { title: '批量通过' },
    )
    if (!current() || opinion === null || !String(opinion).trim()) return
    batchActioning.value = true
    let done = 0, accepted = 0
    const failed: string[] = []
    try {
      for (const id of ids) {
        if (!current()) return
        try {
          const res = await approvalApi.approve(id, userId, String(opinion).trim())
          if (!current()) return
          if (res.success) done += 1
          else if (res.accepted === true) accepted += 1
          else failed.push(`#${id} ${res.message || '审批失败'}`)
        } catch {
          failed.push(`#${id} 审批失败`)
        }
      }
      if (!current()) return
      await appAlert(
        `批量审批：通过 ${done} 条${accepted ? `，已受理待核对 ${accepted} 条` : ''}${failed.length ? `，失败 ${failed.length} 条\n${failed.join('\n')}` : ''}`,
      )
      if (!current()) return
      await loadData()
      if (current()) closeDetails()
    } finally {
      if (current()) batchActioning.value = false
    }
  }

  const reject = async (requestId: number) => {
    const reason = await appPrompt('请输入拒绝原因（必填，会记录在审批记录中）：', '', { title: '拒绝审批' })
    if (reason === null || !String(reason).trim()) return

    const userId = getCurrentUserId()
    actioningId.value = requestId
    try {
      const res = await approvalApi.reject(requestId, userId, String(reason).trim())
      if (res.success) {
        await appAlert('已拒绝')
        loadData()
        closeDetails()
      } else {
        await appAlert('拒绝失败：' + res.message)
      }
    } catch (error) {
      console.error('拒绝失败:', error)
      await appAlert('拒绝失败，请重试')
    } finally {
      actioningId.value = 0
    }
  }

  // 删除单条已完成记录
  const deleteSingle = async (item: ApprovalRequest) => {
    if (!isFinalStatus(item.status)) {
      await appAlert('进行中的审批不能直接删除，请先撤回')
      return
    }
    const ok = await appConfirm(
      `确定删除这条审批记录吗？\n\n${formatRequestTitle(item)}\n状态：${getStatusLabel(item.status)}\n\n删除后不可恢复。`,
      { title: '删除确认', confirmText: '删除', cancelText: '取消' }
    )
    if (!ok) return

    const userId = getCurrentUserId()
    try {
      const res = await approvalApi.deleteRequest(item.id, userId)
      if (res.success) {
        initiatedRequests.value = initiatedRequests.value.filter((r) => r.id !== item.id)
        await loadData()
      } else {
        await appAlert('删除失败：' + (res.message || '未知错误'))
      }
    } catch (error) {
      console.error('删除失败:', error)
      await appAlert('删除失败，请重试')
    }
  }

  // 批量清理已完成记录
  const cleanupCompleted = async () => {
    if (cleanupLoading.value) return
    const userId = getCurrentUserId()

    cleanupLoading.value = true
    try {
      // 1) 先 dry-run 获取精确待清理数量
      const preview = await approvalApi.cleanupCompleted(userId, {
        statuses: [...FINAL_STATUSES],
        dryRun: true
      })
      const matched = preview.success ? preview.data?.matched ?? 0 : 0
      if (!preview.success) {
        await appAlert('清理检查失败：' + (preview.message || '未知错误'))
        return
      }
      if (matched === 0) {
        await appAlert('暂无可清理的已完成记录')
        return
      }

      // 2) 二次确认
      const ok = await appConfirm(
        `将永久删除 ${matched} 条已完成（通过 / 拒绝 / 撤回 / 取消）的审批记录，删除后不可恢复，确定继续吗？`,
        { title: '清理确认', confirmText: `删除 ${matched} 条`, cancelText: '取消' }
      )
      if (!ok) return

      // 3) 真正执行
      const res = await approvalApi.cleanupCompleted(userId, {
        statuses: [...FINAL_STATUSES],
        dryRun: false
      })
      if (res.success) {
        const deleted = res.data?.deleted ?? 0
        await appAlert(`已清理 ${deleted} 条记录`)
        await loadData()
      } else {
        await appAlert('清理失败：' + (res.message || '未知错误'))
      }
    } catch (error) {
      console.error('清理失败:', error)
      await appAlert('清理失败，请重试')
    } finally {
      cleanupLoading.value = false
    }
  }

  return {
    cleanupLoading, actioningId, batchActioning, completedInitiatedCount,
    approve, approveMany, reject, deleteSingle, cleanupCompleted,
  }
}
