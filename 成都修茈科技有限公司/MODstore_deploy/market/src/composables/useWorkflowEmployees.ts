import { ref } from 'vue'
import { api } from '../api'
import { filterOutPlannedDutyEmployees } from '../utils/workbenchEmployeeFilter'
import { errMessage } from '../utils/errMessage'
import type { EmployeeRow } from '../views/workflow/workflowTypes'

/** WorkflowView 员工列表域（自 WorkflowView.vue 原样迁移） */
export function useWorkflowEmployees(deps: { flash: (msg: string, ok?: boolean) => void }) {
  const { flash } = deps

  const employees = ref<EmployeeRow[]>([])

  function pickEmployeeNameById(empId: unknown): string {
    const e = (employees.value || []).find((x) => String(x?.id) === String(empId))
    const name = e?.name
    return typeof name === 'string' ? name.trim() : ''
  }

  // 加载员工列表
  async function loadEmployees() {
    try {
      const [sqlRows, v1Rows] = await Promise.all([
        api.listEmployees().catch(() => []),
        api.listV1Packages('employee_pack', '', 120, 0).catch(() => ({ packages: [] })),
      ])
      const merged = new Map()
      for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
        const id = String(e?.id || '').trim()
        if (!id) continue
        merged.set(id, {
          id,
          name: String(e?.name || id).trim() || id,
          version: String(e?.version || '').trim(),
          description: typeof e?.description === 'string' ? e.description : '',
          industry: String(e?.industry || '').trim(),
          sourceLabel: '执行器目录',
        })
      }
      for (const p of v1Rows?.packages || []) {
        const id = String(p?.id || '').trim()
        if (!id) continue
        if (merged.has(id)) continue
        merged.set(id, {
          id,
          name: String(p?.name || id).trim() || id,
          version: String(p?.version || '').trim(),
          description: typeof p?.description === 'string' ? p.description : '',
          industry: String(p?.industry || '').trim(),
          sourceLabel: '本地包目录',
        })
      }
      employees.value = filterOutPlannedDutyEmployees([...merged.values()]).sort((a, b) =>
        String(a.name).localeCompare(String(b.name), 'zh-CN'),
      )
    } catch (e) {
      flash('加载员工失败: ' + errMessage(e), false)
      employees.value = []
    }
  }

  return { employees, loadEmployees, pickEmployeeNameById }
}
