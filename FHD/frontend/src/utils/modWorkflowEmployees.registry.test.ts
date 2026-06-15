import { describe, expect, it, beforeEach } from 'vitest'
import {
  filterWorkflowRegistrySourceMods,
  isEmployeePackModEntry,
  isNonWorkflowDeskEmployeeId,
} from './modWorkflowEmployees'
import { mergeModManifestEntries as mergeRegistry } from './workflowEmployeeRegistry'
import { employeeRegistryRules } from '@/stores/hostConfig'

describe('workflow registry mod/employee separation', () => {
  beforeEach(() => {
    employeeRegistryRules.value = null
  })
  it('treats office employee_pack as non-workflow source', () => {
    expect(
      isEmployeePackModEntry({
        id: 'ppt-generate-employee',
        type: 'employee_pack',
        workflow_employees: [{ id: 'ppt-generate-employee', label: 'PPT' }],
      }),
    ).toBe(true)
    expect(
      isEmployeePackModEntry({
        id: 'xcagi-host-foundation-employee',
        type: 'employee_pack',
      }),
    ).toBe(true)
  })

  it('allows desk-type employee_pack into workflow registry', () => {
    expect(
      isEmployeePackModEntry({
        id: 'intake-dispatcher',
        type: 'employee_pack',
        workflow_employees: [{ id: 'intake-dispatcher', label: '需求接入员' }],
      }),
    ).toBe(false)
  })

  it('filters office and host ids from desk registry', () => {
    expect(isNonWorkflowDeskEmployeeId('host_foundation')).toBe(true)
    expect(isNonWorkflowDeskEmployeeId('ppt-generate-employee')).toBe(true)
    expect(isNonWorkflowDeskEmployeeId('label_print')).toBe(false)
  })

  it('mergeModManifestEntries ignores employee_pack rows', () => {
    const merged = mergeRegistry(
      { schemaVersion: 1, employees: [] },
      [
        {
          id: 'ppt-generate-employee',
          type: 'employee_pack',
          name: 'PPT 生成员',
          workflow_employees: [{ id: 'ppt-generate-employee', label: 'PPT' }],
        },
        {
          id: 'xcagi-workflow-employee-label-print',
          name: '标签打印',
          workflow_employees: [{ id: 'label_print', label: '标签打印' }],
        },
      ],
    )
    expect(merged.map((e) => e.id)).toEqual(['label_print'])
    const withDeskPack = mergeRegistry(
      { schemaVersion: 1, employees: [] },
      [
        {
          id: 'intake-dispatcher',
          type: 'employee_pack',
          name: '需求接入员',
          workflow_employees: [{ id: 'intake-dispatcher', label: '需求接入员' }],
        },
      ],
    )
    expect(withDeskPack.map((e) => e.id)).toEqual(['intake-dispatcher'])
    expect(filterWorkflowRegistrySourceMods([
      {
        id: 'ppt-generate-employee',
        type: 'employee_pack',
        workflow_employees: [{ id: 'ppt-generate-employee', label: 'PPT' }],
      },
      { id: 'xcagi-workflow-employee-label-print', workflow_employees: [{ id: 'label_print', label: 'L' }] },
    ])).toHaveLength(1)
  })

  it('excludes custom-phase employee carrier mods from registry', () => {
    const filtered = filterWorkflowRegistrySourceMods([
      {
        id: 'xcagi-core-workflow-employees',
        workflow_employees: [{ id: 'label_print', label: '标签打印' }],
      },
      {
        id: 'wechat-contacts-ai-employee',
        workflow_employees: [{ id: 'wechat_contacts', label: '微信' }],
      },
      {
        id: 'taiyangniao-pro',
        workflow_employees: [{ id: 'attendance_ai', label: '考勤助手' }],
      },
    ])
    expect(filtered.map((m) => m.id)).toEqual(['taiyangniao-pro'])
  })
})
