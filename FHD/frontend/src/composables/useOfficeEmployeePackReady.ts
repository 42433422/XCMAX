import { ref, computed, onUnmounted } from 'vue'
import { OFFICE_EMPLOYEE_PKG_IDS } from '@/constants/officeEmployeePack'
import {
  fetchEmployeePlannerStatus,
  type EmployeePlannerStatus,
} from '@/utils/platformShellApi'

const DEFAULT_STATUS: EmployeePlannerStatus = {
  installed_employee_pack_count: 0,
  registered_tool_count: 0,
  registered_tool_names: [],
  office_catalog_count: OFFICE_EMPLOYEE_PKG_IDS.length,
  office_installed_count: 0,
  office_installed_ids: [],
  missing_office_pack_ids: [...OFFICE_EMPLOYEE_PKG_IDS],
  office_ready: false,
  runtime_missing_pack_ids: [],
}

export function useOfficeEmployeePackReady(pollMs = 0) {
  const status = ref<EmployeePlannerStatus>({ ...DEFAULT_STATUS })
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  const ready = computed(() => Boolean(status.value.office_ready))
  const missingIds = computed(() => [...(status.value.missing_office_pack_ids || [])])
  const toolCount = computed(() => Number(status.value.registered_tool_count || 0))

  async function refresh(force = true) {
    loading.value = true
    try {
      status.value = await fetchEmployeePlannerStatus(force)
    } catch {
      /* 离线保留上次状态 */
    } finally {
      loading.value = false
    }
  }

  function startPolling(intervalMs = 1500) {
    stopPolling()
    if (intervalMs <= 0) return
    timer = setInterval(() => {
      void refresh(true)
    }, intervalMs)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  if (pollMs > 0) {
    void refresh(true).then(() => startPolling(pollMs))
  }

  onUnmounted(stopPolling)

  return {
    status,
    loading,
    ready,
    missingIds,
    toolCount,
    refresh,
    startPolling,
    stopPolling,
  }
}
