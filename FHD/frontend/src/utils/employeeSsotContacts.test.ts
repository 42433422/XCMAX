import { describe, expect, it } from 'vitest'

import {
  dutyEmployeesFromEmployeeSsot,
  type EmployeeSsotPayload,
} from './employeeSsotContacts'

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

  it('normalizes contact routes, fallbacks, duplicates, and custom sources', () => {
    const payload: EmployeeSsotPayload = {
      employee_labels: { fallback: '后备员工' },
      employee_descriptions: { fallback: '后备说明' },
      contacts: [
        {
          employee_id: 'fallback',
          display_name: '',
          department: '',
          source: 'installed',
          installed: true,
          mobile_contact_route: '/api/admin/employees/fallback/messages/',
        },
        {
          employee_id: 'fallback',
          display_name: '重复员工',
        },
        {
          employee_id: 'remote-agent',
          display_name: '远程员工',
          department: '远程组',
          source: 'codex-cloud',
          runnable: false,
          contact_route: '/api/admin/employees/remote-agent/chat',
          pinned: true,
        },
        { employee_id: '', display_name: '无效员工' },
        { employee_id: 'builtin', display_name: '内置员工', source: 'builtin' },
      ],
    }

    const rows = dutyEmployeesFromEmployeeSsot(payload)
    expect(rows.map((row) => row.id)).toEqual(['fallback', 'remote-agent'])
    expect(rows[0]).toMatchObject({
      display_name: '后备员工',
      description: '后备说明',
      area: '编制',
      api_base_path: '/api/admin/employees/fallback',
      phone_channel: 'admin-duty',
      runnable: true,
    })
    expect(rows[1]).toMatchObject({
      subtitle: '远程组 · codex-cloud',
      status: 'codex-cloud',
      api_base_path: '/api/admin/employees/remote-agent',
      phone_channel: 'super',
      pinned: true,
    })
  })

  it('falls back to department duty state when unified contacts are absent', () => {
    const payload: EmployeeSsotPayload = {
      employee_labels: { runner: '执行员工', planned: '计划员工' },
      employee_descriptions: { planned: '等待安装' },
      admin: {
        on_duty_employee_ids: ['runner'],
        departments: [
          {
            id: 'ops',
            employees: [
              { id: 'runner' },
              { id: 'planned', on_duty: false },
              { id: '  ' },
            ],
          },
        ],
      },
    }

    expect(dutyEmployeesFromEmployeeSsot(payload)).toEqual([
      expect.objectContaining({
        id: 'runner',
        display_name: '执行员工',
        subtitle: 'ops · 可执行',
        status: 'on_duty',
        source: 'installed',
        installed: true,
      }),
      expect.objectContaining({
        id: 'planned',
        display_name: '计划员工',
        subtitle: 'ops · 未安装',
        description: '等待安装',
        status: 'planned',
        source: 'planned',
        runnable: false,
      }),
    ])
  })

  it('returns no contacts for empty or incomplete payloads', () => {
    expect(dutyEmployeesFromEmployeeSsot(null)).toEqual([])
    expect(dutyEmployeesFromEmployeeSsot({ contacts: [] })).toEqual([])
    expect(dutyEmployeesFromEmployeeSsot({ admin: { departments: [] } })).toEqual([])
  })
})
