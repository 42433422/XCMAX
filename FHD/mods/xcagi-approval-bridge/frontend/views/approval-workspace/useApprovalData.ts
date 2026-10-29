import { computed, onScopeDispose, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { authApi } from '@/api/auth'
import { productReadScopeKey } from '@/utils/productReadAccountScope'

export function useApprovalData(deps: { viewDetails: (requestId: number) => Promise<void>; closeDetails: () => void }) {
  const route = useRoute()
  const accountScope = () => productReadScopeKey('xcagi-approval-bridge')
  let active = true, resolvedAccountScope = '', dashboardRequest = 0, sessionRequest = 0
  const isCurrentAccount = (scope: string) => active && scope === accountScope()

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
  const fullListType = ref<'pending' | 'initiated' | ''>('')
  const fullListPage = ref(1)
  const fullListPageCount = ref(1)
  const fullListItems = ref<ApprovalRequest[]>([])
  const fullListLoading = ref(false)
  const fullListError = ref('')
  const visiblePendingRequests = computed(() => fullListType.value === 'pending' ? fullListItems.value : pendingRequests.value)
  const visibleInitiatedRequests = computed(() => fullListType.value === 'initiated' ? fullListItems.value : initiatedRequests.value)
  let fullListRequest = 0

  const loadFullListPage = async (page = fullListPage.value) => {
    const type = fullListType.value, scope = accountScope(), userId = getCurrentUserId()
    if (!active || !userId || !type || !Number.isSafeInteger(page) || page < 1 || page > fullListPageCount.value) return
    const request = ++fullListRequest
    const isCurrent = () => request === fullListRequest && type === fullListType.value && isCurrentAccount(scope) && userId === getCurrentUserId()
    fullListLoading.value = true
    fullListError.value = ''
    try {
      const result = await (type === 'pending' ? approvalApi.getPendingApprovals : approvalApi.getMyRequests)(userId, page, 50)
      if (!isCurrent()) return
      if (!result.success) throw new Error(result.message || '审批列表加载失败')
      const pagination = 'pagination' in result ? result.pagination : undefined
      fullListPageCount.value = Math.max(1, Math.ceil((pagination?.total ?? result.data.requests.length) / 50))
      if (page > fullListPageCount.value) {
        await loadFullListPage(fullListPageCount.value)
        return
      }
      fullListPage.value = page
      fullListItems.value = result.data.requests
    } catch (error) {
      if (isCurrent()) fullListError.value = error instanceof Error ? error.message : '审批列表加载失败，请重试'
    } finally {
      if (isCurrent()) fullListLoading.value = false
    }
  }

  const viewAll = async (type: 'pending' | 'initiated') => {
    fullListType.value = type
    fullListPage.value = fullListPageCount.value = 1
    fullListItems.value = []
    await loadFullListPage(1)
  }

  const closeFullList = () => {
    fullListRequest++
    fullListType.value = ''
    fullListItems.value = []
    fullListLoading.value = false
    fullListError.value = ''
  }

  const currentUserId = ref(0)
  const deepLinkOpened = ref(false)

  const getCurrentUserId = () => isCurrentAccount(resolvedAccountScope) ? currentUserId.value : 0

  const resolveCurrentUserId = async () => {
    const scope = accountScope()
    const response = await authApi.validateSession()
    if (!isCurrentAccount(scope)) return
    const envelope = response as unknown as Record<string, unknown>
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
    resolvedAccountScope = scope
  }

  // 加载数据
  const loadData = async () => {
    const userId = getCurrentUserId(), scope = accountScope(), request = ++dashboardRequest
    if (!active || !userId) return
    const isCurrent = () => request === dashboardRequest && isCurrentAccount(scope) && userId === getCurrentUserId()

    try {
      const [pendingRes, myRes] = await Promise.all([
        approvalApi.getPendingApprovals(userId),
        approvalApi.getMyRequests(userId),
      ])
      if (!isCurrent()) return
      if (!pendingRes.success || !myRes.success) throw new Error(pendingRes.message || myRes.message || '审批列表加载失败，请重试')

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
      if (isCurrent() && fullListType.value) await loadFullListPage()
    } catch (error) {
      if (isCurrent()) fullListError.value = error instanceof Error ? error.message : '审批列表加载失败，请重试'
    }
  }

  const reloadAccount = async () => {
    const scope = accountScope(), request = ++sessionRequest
    const isCurrent = () => request === sessionRequest && isCurrentAccount(scope)
    fullListLoading.value = true
    fullListError.value = ''
    try {
      await resolveCurrentUserId()
      if (isCurrent()) await loadData()
    } catch (error) {
      if (isCurrent()) fullListError.value = error instanceof Error ? error.message : '登录会话无效，请重新登录后重试'
    } finally {
      if (isCurrent()) fullListLoading.value = false
    }
  }

  watch(accountScope, () => {
    closeFullList()
    dashboardRequest++
    currentUserId.value = 0
    resolvedAccountScope = ''
    pendingRequests.value = initiatedRequests.value = []
    stats.value = { pending: 0, initiated: 0, approved: 0, rejected: 0 }
    deepLinkOpened.value = false
    deps.closeDetails()
    void reloadAccount()
  }, { flush: 'sync' })
  onScopeDispose(() => { active = false; fullListRequest++; dashboardRequest++; sessionRequest++ })

  return {
    stats, pendingRequests, initiatedRequests,
    fullListType, fullListPage, fullListPageCount, fullListLoading, fullListError,
    visiblePendingRequests, visibleInitiatedRequests, viewAll, loadFullListPage, closeFullList,
    currentUserId, deepLinkOpened, getCurrentUserId, reloadAccount, loadData,
  }
}
