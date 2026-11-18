import { ref, computed, type Ref } from 'vue'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog'
import {
  FINAL_STATUSES, isFinalStatus, getStatusLabel, formatRequestTitle, buildWorkflowExecutionAlert,
} from './awHelpers'

/**
 * 拆分自 ApprovalWorkspaceView.vue 脚本（原第 316–320、425–554 行）；
 * 逻辑逐字迁移，行为不变。审批动作与列表/详情状态联动，相关 ref 经 deps 注入。
 */
export function useApprovalActions(deps: {
  getCurrentUserId: () => number
  loadData: () => Promise<void>
  closeDetails: () => void
  initiatedRequests: Ref<ApprovalRequest[]>
  selectedRequest: Ref<ApprovalRequest | null>
  canApprove: Ref<boolean>
  showDetails: Ref<boolean>
}) {
  const {
    getCurrentUserId, loadData, closeDetails,
    initiatedRequests, selectedRequest, canApprove, showDetails,
  } = deps

  // 清理
  const cleanupLoading = ref(false)
  const actioningId = ref(0)
  const batchActioning = ref(false)
  const completedInitiatedCount = computed(
    () => initiatedRequests.value.filter((r) => isFinalStatus(r.status)).length
  )

  const approveMessage = (request?: ApprovalRequest) => request?.business_type === 'workflow_tool'
    ? '批准后系统将按审批工作流执行后续业务操作，执行结果会记录在审批详情中。\n\n请输入审批意见：'
    : '请输入审批意见：'

  // 审批操作
  const approve = async (requestId: number, request?: ApprovalRequest) => {
    if (actioningId.value) return
    const opinion = await appPrompt(approveMessage(request), '同意', { title: '审批通过' })
    if (opinion === null || !String(opinion).trim()) return

    const userId = getCurrentUserId()
    actioningId.value = requestId
    try {
      const res = await approvalApi.approve(requestId, userId, String(opinion).trim())
      if (res.success) {
        const updatedRequest = res.data as ApprovalRequest | undefined
        const workflowExecution = updatedRequest?.workflow_execution
        await appAlert(`审批通过！${buildWorkflowExecutionAlert(workflowExecution)}`)
        await loadData()
        if (workflowExecution && updatedRequest) {
          selectedRequest.value = updatedRequest
          canApprove.value = false
          showDetails.value = true
        } else {
          closeDetails()
        }
      } else if (res.accepted === true) {
        // 202：审批已放行，执行交给调度器，不是失败。
        await appAlert(res.message || '审批已通过，执行已交给调度器')
        await loadData()
        closeDetails()
      } else {
        // 失败也要刷新：避免列表停留在旧状态，用户反复点击同一个失效单。
        await loadData()
        if (res.expired) {
          await appAlert(res.message || '该审批已失效，已自动关闭，请重新发起任务。')
          closeDetails()
        } else {
          await appAlert('审批失败：' + (res.message || '未知错误'))
        }
      }
    } catch (error) {
      console.error('审批失败:', error)
      await appAlert('审批失败，请重试')
    } finally {
      actioningId.value = 0
    }
  }

  /** 批量通过：同一审批意见依次提交，失败项保留在列表中等待重试。 */
  const approveMany = async (ids: number[]) => {
    if (batchActioning.value || !ids.length) return
    const opinion = await appPrompt(
      `将批量通过 ${ids.length} 条审批，请填写统一审批意见：`,
      '同意',
      { title: '批量通过' },
    )
    if (opinion === null || !String(opinion).trim()) return
    const userId = getCurrentUserId()
    batchActioning.value = true
    let done = 0
    const failed: string[] = []
    try {
      for (const id of ids) {
        try {
          const res = await approvalApi.approve(id, userId, String(opinion).trim())
          if (res.success) done += 1
          else failed.push(`#${id} ${res.message || '审批失败'}`)
        } catch {
          failed.push(`#${id} 审批失败`)
        }
      }
      await appAlert(
        `批量通过完成：成功 ${done} 条${failed.length ? `，失败 ${failed.length} 条\n${failed.join('\n')}` : ''}`,
      )
      await loadData()
      closeDetails()
    } finally {
      batchActioning.value = false
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
