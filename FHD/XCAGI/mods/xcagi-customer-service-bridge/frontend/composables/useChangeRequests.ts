import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { get, post, put } from '@/api'
import { appAlert } from '@/utils/appDialog'

type ChangeRequestRow = {
  id: string
  ticket_no?: string
  change_type_label?: string
  title?: string
  description?: string
  status?: string
  status_label?: string
  ops_dispatch_job_id?: string
  ops_dispatched_at?: string
  ops_dispatch_error?: string
}

/**
 * 客户变更工单（外部客服门户）状态簇：列表加载、状态更新、派发运维任务。
 * 仅依赖所选客户 id 与用户名。
 */
export function useChangeRequests(
  selectedUserId: Ref<number | null>,
  selectedEnterpriseUser: ComputedRef<{ username?: string } | null>,
) {
  const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

  const changeRequests = ref<Array<ChangeRequestRow>>([])
  const changeRequestsLoading = ref(false)
  const changeRequestOpsDispatchingId = ref('')

  async function loadChangeRequestsForCustomer() {
    if (!selectedUserId.value) return
    changeRequestsLoading.value = true
    try {
      const res = await get<{
        success?: boolean
        data?: { requests?: typeof changeRequests.value }
      }>(`${CS_BRIDGE}/user-cs/change-requests`, { market_user_id: selectedUserId.value })
      changeRequests.value = res?.success ? (res.data?.requests || []) : []
    } catch {
      changeRequests.value = []
    } finally {
      changeRequestsLoading.value = false
    }
  }

  async function onChangeRequestStatus(
    cr: { id: string },
    status: string,
  ) {
    if (!selectedUserId.value || !cr.id) return
    try {
      const res = await put<{ success?: boolean; error?: string }>(
        `${CS_BRIDGE}/user-cs/change-requests/${encodeURIComponent(cr.id)}/status`,
        {
          market_user_id: selectedUserId.value,
          status,
        },
      )
      if (!res?.success) {
        await appAlert(res?.error || '更新失败')
        return
      }
      await loadChangeRequestsForCustomer()
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '更新失败')
    }
  }

  async function dispatchChangeRequestOps(cr: { id: string; ticket_no?: string }) {
    if (!selectedUserId.value) return
    changeRequestOpsDispatchingId.value = cr.id
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/change-requests/${cr.id}/ops-dispatch`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
        contact_name: selectedEnterpriseUser.value?.username || '',
      })
      const payload = res as {
        success?: boolean
        error?: string
        data?: { job_id?: string; request?: Record<string, unknown> }
      }
      if (!payload?.success) {
        await appAlert(payload?.error || '派发失败')
        await loadChangeRequestsForCustomer()
        return
      }
      await loadChangeRequestsForCustomer()
      const jobId = payload.data?.job_id || ''
      await appAlert(jobId ? `已派发运维任务 job_id=${jobId}` : '已派发运维任务')
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '派发失败')
    } finally {
      changeRequestOpsDispatchingId.value = ''
    }
  }

  return {
    changeRequests,
    changeRequestsLoading,
    changeRequestOpsDispatchingId,
    loadChangeRequestsForCustomer,
    onChangeRequestStatus,
    dispatchChangeRequestOps,
  }
}