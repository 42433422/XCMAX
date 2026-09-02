// 员工包列表加载：合并 /employees 与 v1 packages，并保证默认/JSON 报告员可用。
import { ref } from 'vue'
import { api } from '../../api'
import { JSON_REPORT_EMPLOYEE_ID, readEmployeeDisplayName } from '../../utils/tabularReadEmployees'
import { DEFAULT_EMPLOYEE_ID, type EmployeeOption } from './employeeExamTypes'

export function useEmployeeExamEmployees() {
  const employeeOptions = ref<EmployeeOption[]>([])
  const selectedEmployeeId = ref('')
  const loadingEmployees = ref(false)
  const employeesError = ref('')

  async function loadEmployees() {
    loadingEmployees.value = true
    employeesError.value = ''
    const merged = new Map<string, EmployeeOption>()
    try {
      const rows = await api.listEmployees()
      for (const e of Array.isArray(rows) ? rows : []) {
        const row = e as { id?: string; name?: string }
        const id = String(row.id || '').trim()
        if (!id) continue
        merged.set(id, { id, name: String(row.name || id).trim() || id })
      }
    } catch (e: unknown) {
      employeesError.value = `加载员工列表失败：${(e as Error)?.message || String(e)}`
    }
    try {
      const r = await api.listV1Packages('employee_pack', '', 120, 0)
      for (const p of r?.packages || []) {
        const row = p as { id?: string; name?: string }
        const id = String(row.id || '').trim()
        if (!id) continue
        const name = String(row.name || id).trim() || id
        const existing = merged.get(id)
        merged.set(id, existing ? { id, name: existing.name } : { id, name })
      }
    } catch {
      /* optional */
    }
    if (!merged.has(JSON_REPORT_EMPLOYEE_ID)) {
      merged.set(JSON_REPORT_EMPLOYEE_ID, {
        id: JSON_REPORT_EMPLOYEE_ID,
        name: readEmployeeDisplayName(JSON_REPORT_EMPLOYEE_ID),
      })
    }
    employeeOptions.value = [...merged.values()].sort((a, b) => {
      const order = [DEFAULT_EMPLOYEE_ID, JSON_REPORT_EMPLOYEE_ID]
      const ai = order.indexOf(a.id)
      const bi = order.indexOf(b.id)
      if (ai >= 0 || bi >= 0) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
      return a.name.localeCompare(b.name, 'zh-CN')
    })
    loadingEmployees.value = false
    if (!employeeOptions.value.length) {
      selectedEmployeeId.value = ''
      return
    }
    const cur = selectedEmployeeId.value.trim()
    if (!cur || !merged.has(cur)) {
      const preferred = merged.get(DEFAULT_EMPLOYEE_ID)
      selectedEmployeeId.value = preferred ? preferred.id : employeeOptions.value[0].id
    }
  }

  return {
    employeeOptions,
    selectedEmployeeId,
    loadingEmployees,
    employeesError,
    loadEmployees,
  }
}
