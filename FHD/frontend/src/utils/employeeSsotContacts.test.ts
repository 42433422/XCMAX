import { describe, expect, it } from 'vitest'

import { dutyEmployeesFromEmployeeSsot, type EmployeeSsotPayload } from './employeeSsotContacts'

describe('dutyEmployeesFromEmployeeSsot', () => {
  it('prefers unified contacts with display_name and skips super builtins', () => {
    const payload: EmployeeSsotPayload = {
      contacts: [
        {
          employee_id: 'codex-super-employee',
          display_name: '超级员工-Codex',
          department: 'super',
          source: 'codex',
          installed: true,
          runnable: true,
        },
        {
          employee_id: 'daily-orchestrator',
          display_name: '每日编排员',
          department: 'platform-core',
          source: 'installed',
          installed: true,
          runnable: true,
          description: '已安装，可联系',
        },
        {
          employee_id: 'missing-pack',
          display_name: '缺包员工',
          department: 'platform-core',
          source: 'planned',
          installed: false,
          runnable: false,
        },
      ],
    }

    const rows = dutyEmployeesFromEmployeeSsot(payload)
    expect(rows.map((row) => row.id)).toEqual(['daily-orchestrator', 'missing-pack'])
    expect(rows[0]?.display_name).toBe('每日编排员')
    expect(rows[0]?.status).toBe('on_duty')
    expect(rows[1]?.status).toBe('planned')
  })
})
