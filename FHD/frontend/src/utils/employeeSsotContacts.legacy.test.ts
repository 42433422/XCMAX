import { describe, expect, it } from 'vitest'
import { dutyEmployeesFromEmployeeSsot } from './employeeSsotContacts'

describe('legacy employee catalog display', () => {
  it('renders department-only catalogs with explicit duty state taking priority over the summary list', () => {
    const rows = dutyEmployeesFromEmployeeSsot({
      contacts: [],
      employee_labels: { analyst: '分析员', writer: '文案员' },
      employee_descriptions: { analyst: '分析报表' },
      admin: {
        on_duty_employee_ids: ['analyst', 'writer'],
        departments: [
          { id: 'office', label: '办公', employees: [{ id: 'analyst' }, { id: 'writer', on_duty: false }, { id: ' ' }] },
          { id: 'tools', employees: [{ id: 'chart', on_duty: true }] },
          { employees: [{ id: 'planned' }] },
          { label: '空部门' },
        ],
      },
    })
    expect(rows.map(row => row.id)).toEqual(['analyst', 'writer', 'chart', 'planned'])
    expect(rows[0]).toMatchObject({ display_name: '分析员', area: '办公', subtitle: '办公 · 可执行', description: '分析报表', source: 'installed', installed: true, runnable: true })
    expect(rows[1]).toMatchObject({ display_name: '文案员', subtitle: '办公 · 未安装', description: '编制内但未安装员工包', source: 'planned', installed: false, runnable: false })
    expect(rows[2]).toMatchObject({ display_name: 'chart', area: 'tools', description: '已安装，可联系', api_base_path: '/api/admin/employees/chart' })
    expect(rows[3]).toMatchObject({ area: '编制', status: 'planned' })
  })

  it('defaults missing duty summaries to planned display without dropping employees', () => {
    const rows = dutyEmployeesFromEmployeeSsot({ admin: { departments: [{ employees: [{ id: 'new-hire' }] }] } })
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: 'new-hire', status: 'planned', subtitle: '编制 · 未安装', installed: false, runnable: false })
  })
})
