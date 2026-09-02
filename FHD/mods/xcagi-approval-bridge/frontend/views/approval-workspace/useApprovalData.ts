import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { authApi } from '@/api/auth'

/**
 * 拆分自 ApprovalWorkspaceView.vue 脚本（原第 294、299–346、348–382 行）；
 * 逻辑逐字迁移，行为不变。loadData 内的深链打开依赖 viewDetails，经 deps 注入以避免循环引用。
 */
export function useApprovalData(deps: { viewDetails: (requestId: number) => Promise<void> }) {
  const route = useRoute()

  // 统计数据
  const stats = ref({
    pending: 0,
    initiated: 0,
    approved: 0,
    rejected: 0
  })

  // 请求列表
  const pendingRequests = ref<ApprovalRequest[]>([])
  const initiatedRequests = ref<ApprovalRequest[]>([])

  const currentUserId = ref(0)
  const deepLinkOpened = ref(false)

  const getCurrentUserId = () => currentUserId.value

  const resolveCurrentUserId = async () => {
    const response = await authApi.validateSession()
    const envelope = response as Record<string, unknown>
    const data = (response.data && typeof response.data === 'object'
      ? response.data
      : {}) as Record<string, unknown>
    const candidate = [
      envelope.local_user_id,
      data.local_user_id,
      data.user_id,
      envelope.user_id,
    ].find((value) => Number.isInteger(Number(value)) && Number(value) > 0)
    if (!candidate) throw new Error('当前登录会话缺少本地用户 ID')
    currentUserId.value = Number(candidate)
  }

  // 加载数据
  const loadData = async () => {
    const userId = getCurrentUserId()

    try {
      const [pendingRes, myRes] = await Promise.all([
        approvalApi.getPendingApprovals(userId),
        approvalApi.getMyRequests(userId),
      ])

      if (pendingRes.success && pendingRes.data) {
        pendingRequests.value = pendingRes.data.requests || []
        stats.value.pending = pendingRequests.value.length
      }

      if (myRes.success && myRes.data) {
        const mine = myRes.data.requests || []
        initiatedRequests.value = mine
        stats.value.initiated = mine.length
        stats.value.approved = mine.filter((r: ApprovalRequest) => r.status === 'approved').length
        stats.value.rejected = mine.filter((r: ApprovalRequest) => r.status === 'rejected').length
      }
      const requestNo = String(route.query.request_no || '').trim(), requestId = Number(route.query.request_id || 0)
      if ((requestNo || requestId > 0) && !deepLinkOpened.value) {
        const target = [...pendingRequests.value, ...initiatedRequests.value]
          .find((item) => (requestId > 0 ? item.id === requestId : item.request_no === requestNo))
        if (target) {
          deepLinkOpened.value = true
          await deps.viewDetails(target.id)
        }
      }
    } catch (error) {
      console.error('加载审批数据失败:', error)
    }
  }

  return {
    stats, pendingRequests, initiatedRequests,
    currentUserId, deepLinkOpened, getCurrentUserId, resolveCurrentUserId, loadData,
  }
}
