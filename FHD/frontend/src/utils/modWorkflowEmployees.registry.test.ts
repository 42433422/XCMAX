import { describe, expect, it, beforeEach } from 'vitest'
import { filterWorkflowRegistrySourceMods, isEmployeePackModEntry, isNonWorkflowDeskEmployeeId } from './modWorkflowEmployees'
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
    const merged = mergeRegistry({ schemaVersion: 1, employees: [] }, [
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
    ])
    expect(merged.map((e) => e.id)).toEqual(['label_print'])
    const withDeskPack = mergeRegistry({ schemaVersion: 1, employees: [] }, [
      {
        id: 'intake-dispatcher',
        type: 'employee_pack',
        name: '需求接入员',
        workflow_employees: [{ id: 'intake-dispatcher', label: '需求接入员' }],
      },
    ])
    expect(withDeskPack.map((e) => e.id)).toEqual(['intake-dispatcher'])
    expect(
      filterWorkflowRegistrySourceMods([
        {
          id: 'ppt-generate-employee',
          type: 'employee_pack',
          workflow_employees: [{ id: 'ppt-generate-employee', label: 'PPT' }],
        },
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]),
    ).toHaveLength(1)
  })

  it('excludes custom-phase employee carrier mods from registry', () => {
    const filtered = filterWorkflowRegistrySourceMods([
      {
        id: 'xcagi-core-workflow-employees',
        workflow_employees: [{ id: 'label_print', label: '标签打印' }],
      },
      {
        id: 'taiyangniao-pro',
        workflow_employees: [{ id: 'attendance_ai', label: '考勤助手' }],
      },
    ])
    expect(filtered.map((m) => m.id)).toEqual(['taiyangniao-pro'])
  })
})

import {
  buildModWorkflowPanelMeta, countManifestWorkflowEmployeeRows, findWorkflowEmployeeEntry,
  getActivePhoneAgentPollTarget, isWorkflowRegistrySourceMod, listPhoneAgentEmployeeIds,
  resolvePhoneChannelForEmployee, isPhoneAgentStatusEmployee,
} from './modWorkflowEmployees'

describe('manifest registry rules and phone discovery', () => {
  beforeEach(() => { employeeRegistryRules.value = null })
  it('handles absent, empty, bridge, workflow-prefix and ordinary manifests', () => {
    expect(isEmployeePackModEntry(undefined)).toBe(false)
    expect(filterWorkflowRegistrySourceMods(undefined)).toEqual([])
    for (const entry of [undefined, { id: '' }, { id: 'x-bridge' }, { id: 'ordinary' }]) {
      expect(isWorkflowRegistrySourceMod(entry)).toBe(false)
    }
    expect(isWorkflowRegistrySourceMod({ id: 'xcagi-workflow-employee-calls' })).toBe(true)
  })
  it('applies exclusion IDs and suffixes before configured prefixes and manifest fallbacks', () => {
    employeeRegistryRules.value = {
      exclude_mod_ids: ['desk-blocked'], exclude_id_suffixes: ['-bridge'], workflow_employee_id_prefixes: ['desk-'],
    }
    const manifests = [
      { id: 'desk-blocked' }, { id: 'desk-bridge' }, { id: 'desk-allowed' },
      { id: 'ordinary', workflow_employees: [{ id: 'worker', label: 'Worker' }] }, { id: 'empty' },
    ]
    expect(filterWorkflowRegistrySourceMods(manifests).map((row) => row.id)).toEqual(['desk-allowed', 'ordinary'])
    employeeRegistryRules.value = {}
    expect(isWorkflowRegistrySourceMod({ id: 'desk-allowed' })).toBe(false)
    expect(isWorkflowRegistrySourceMod(manifests[3])).toBe(true)
  })
  it('matches configured regexes and uses exact matching for invalid regex patterns', () => {
    employeeRegistryRules.value = { non_workflow_desk_employee_patterns: ['^office-', '['] }
    expect(isNonWorkflowDeskEmployeeId(' office-reader ')).toBe(true)
    expect(isNonWorkflowDeskEmployeeId('[')).toBe(true)
    expect(isNonWorkflowDeskEmployeeId('desk-worker')).toBe(false)
    expect(isNonWorkflowDeskEmployeeId('')).toBe(true)
  })
  it('deduplicates phone employees, ignores missing configurations and resolves channel aliases', () => {
    const mods = [{ id: 'empty' }, { id: 'calls', workflow_employees: [
      { id: '', label: 'Empty' }, { id: 'none', label: 'No API' },
      { id: 'wechat', label: 'WeChat', phone_agent_base_path: 'phone' },
      { id: 'real', label: 'Real', phone_agent_api_base: '/api/real', phone_channel: ' REAL ' },
      { id: 'adb', label: 'ADB', phone_agent_api_base: '/api/adb', phone_channel: 'adb' },
    ] }, { id: 'other', workflow_employees: [{ id: 'adb', label: 'Duplicate', phone_agent_base_path: 'x' }] }]
    expect(listPhoneAgentEmployeeIds(mods)).toEqual(['wechat', 'real', 'adb'])
    expect(listPhoneAgentEmployeeIds(undefined)).toEqual([])
    expect(resolvePhoneChannelForEmployee(mods, 'real')).toBe('adb')
    expect(resolvePhoneChannelForEmployee(mods, 'adb')).toBe('adb')
    expect(resolvePhoneChannelForEmployee(mods, 'wechat')).toBe('wechat')
    expect(resolvePhoneChannelForEmployee(mods, 'missing')).toBe('wechat')
    expect(isPhoneAgentStatusEmployee(mods, 'none')).toBe(false)
    expect(isPhoneAgentStatusEmployee(mods, 'missing')).toBe(false)
    expect(findWorkflowEmployeeEntry(mods, '')).toBeNull()
    expect(findWorkflowEmployeeEntry(mods, 'none')).toMatchObject({ modId: 'calls', modName: 'calls' })
    expect(countManifestWorkflowEmployeeRows(mods)).toBe(4)
    expect(getActivePhoneAgentPollTarget(mods, { none: true })).toBeNull()
    expect(getActivePhoneAgentPollTarget(undefined, {})).toBeNull()
  })
  it('omits blank employee rows and derives blank labels and mod names safely', () => {
    expect(buildModWorkflowPanelMeta([{ id: 'fallback', workflow_employees: [
      { id: ' ', label: 'Blank' }, { id: 'worker', label: ' ', panel_title: ' ', panel_summary: ' ' },
    ] }])).toEqual({ worker: { title: '工作流 · worker', summary: '由扩展「fallback」在 manifest 中声明的工作流员工「worker」。' } })
  })
})
