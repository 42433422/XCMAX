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

  it('部门英文 ID 显示为中文部门名（管理端 label → 企业层 label → 编制）', () => {
    const payload: EmployeeSsotPayload = {
      contacts: [
        {
          employee_id: 'emp-admin',
          display_name: '获客员工',
          department: 'ops_acquisition',
          source: 'installed',
          installed: true,
          runnable: true,
        },
        {
          employee_id: 'emp-enterprise',
          display_name: '办公员工',
          department: 'tools',
          source: 'installed',
          installed: true,
          runnable: true,
        },
        {
          employee_id: 'emp-unknown',
          display_name: '未知员工',
          department: '',
          source: 'planned',
          installed: false,
          runnable: false,
        },
      ],
      admin: {
        departments: [
          { id: 'ops_acquisition', key: 'ops_acquisition', label: 'O-A 获客部', employees: [] },
        ],
      },
      enterprise: {
        layers: [{ id: 'tools', label: '工具层' }],
      },
    }

    const rows = dutyEmployeesFromEmployeeSsot(payload)
    const byId = new Map(rows.map((row) => [row.id, row]))
    expect(byId.get('emp-admin')?.subtitle).toBe('O-A 获客部 · 可执行')
    expect(byId.get('emp-admin')?.area).toBe('O-A 获客部')
    expect(byId.get('emp-enterprise')?.subtitle).toBe('工具层 · 可执行')
    expect(byId.get('emp-unknown')?.subtitle).toBe('编制 · 未安装')
    expect(rows.every((row) => !/[a-z_]{4,} · /.test(row.subtitle))).toBe(true)
  })
})
