import { computed, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loopString } from '@/composables/useLoopRuntimeConsole'

export function useWorkspaceDeskSelection(workspaceDesks: Ref<Array<{ empId: string }>>) {
  const router = useRouter()
  const route = useRoute()
  const selectedEmpId = ref<string | null>(null)

  watch(
    () => workspaceDesks.value.map((d) => d.empId).join('\0'),
    () => {
      const list = workspaceDesks.value
      if (!list.length) {
        selectedEmpId.value = null
        return
      }
      const cur = selectedEmpId.value
      if (!cur || !list.some((d) => d.empId === cur)) {
        selectedEmpId.value = list[0].empId
      }
    },
    { immediate: true }
  )

  function routeEmployeeId(): string {
    const raw = route.query.employee
    if (typeof raw === 'string') return raw.trim()
    if (Array.isArray(raw)) return String(raw[0] || '').trim()
    return ''
  }

  function syncWorkspaceEmployeeQuery(empId?: string | null) {
    const id = loopString(empId)
    const current = routeEmployeeId()
    if (id === current) return
    const nextQuery = { ...route.query }
    if (id) nextQuery.employee = id
    else delete nextQuery.employee
    void router.replace({ query: nextQuery })
  }

  const routeFocusedEmployeeId = computed(() => routeEmployeeId())
  const routeFocusedEmployeeInWorkspace = computed(() => {
    const id = routeFocusedEmployeeId.value
    return !!id && workspaceDesks.value.some((d) => d.empId === id)
  })

  watch(
    [() => route.query.employee, () => workspaceDesks.value.map((d) => d.empId).join('\0')],
    () => {
      const id = routeEmployeeId()
      if (!id) return
      if (workspaceDesks.value.some((d) => d.empId === id)) {
        selectedEmpId.value = id
      }
    },
    { immediate: true },
  )

  function selectDesk(empId: string) {
    selectedEmpId.value = empId
    syncWorkspaceEmployeeQuery(empId)
  }

  return {
    selectedEmpId,
    routeFocusedEmployeeId,
    routeFocusedEmployeeInWorkspace,
    selectDesk,
  }
}
