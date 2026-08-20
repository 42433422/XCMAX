import { describe, expect, it } from 'vitest'
import { buildEnterpriseModStack, isWorkflowCarrierModId } from '@/constants/enterpriseModStack'
import type { IndustryBaselinePlan } from '@/constants/platformShell'
import {
  filterModsForEnterpriseWorkflowRegistry,
  filterWorkflowRegistryEntriesForEnterpriseStack,
  workflowRegistryEntryBelongsToStack,
} from './workflowEmployeeScope'
import { mergeModManifestEntries } from './workflowEmployeeRegistry'

const basePlan: IndustryBaselinePlan = {
  industry_id: '涂料',
  industry_package: { mod_id: 'coating-industry', product_name: '涂料行业包' },
  groups: [],
  required_mod_ids: ['xcagi-erp-domain-bridge'],
  optional_mod_ids: [],
  industry_mod_ids: ['coating-industry'],
  account_custom_mod_ids: [],
  custom_mod_ids: ['coating-industry'],
  missing_required_mod_ids: [],
  missing_optional_mod_ids: [],
  missing_industry_mod_ids: [],
  baseline_ready: true,
  industry_mod_ready: true,
}

describe('workflowEmployeeScope', () => {
  it('does not treat arbitrary market employee packs as workflow carriers', () => {
    expect(isWorkflowCarrierModId('artifact-generate-ai-employee')).toBe(false)
    expect(isWorkflowCarrierModId('wechat-contacts-ai-employee')).toBe(false)
  })

  it('filters registry entries to enterprise package mods', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const entries = [
      {
        id: 'a',
        label: 'A',
        kind: 'mod_extension' as const,
        order: 1,
        carrierModId: 'coating-industry',
        hostModId: 'coating-industry',
      },
      {
        id: 'b',
        label: 'B',
        kind: 'mod_extension' as const,
        order: 2,
        carrierModId: 'artifact-generate-ai-employee',
        hostModId: 'artifact-generate-ai-employee',
      },
    ]
    const filtered = filterWorkflowRegistryEntriesForEnterpriseStack(entries, stack)
    expect(filtered.map((e) => e.id)).toEqual(['a'])
    expect(workflowRegistryEntryBelongsToStack(entries[1], stack)).toBe(false)
  })

  it('keeps stack isolation after enterprise host reassignment', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const entry = {
      id: 'artifact_generate',
      label: '产物生成员工',
      kind: 'mod_extension' as const,
      order: 1,
      carrierModId: 'artifact-generate-ai-employee',
      hostModId: 'coating-industry',
    }
    expect(workflowRegistryEntryBelongsToStack(entry, stack)).toBe(false)
  })

  it('merges only enterprise stack mods for attendance industry', () => {
    const attendancePlan: IndustryBaselinePlan = {
      industry_id: '考勤',
      industry_package: { mod_id: 'attendance-industry', product_name: '考勤行业包' },
      groups: [],
      required_mod_ids: ['xcagi-erp-domain-bridge', 'xcagi-planner-excel-tools'],
      optional_mod_ids: [],
      industry_mod_ids: ['attendance-industry'],
      account_custom_mod_ids: ['taiyangniao-pro'],
      custom_mod_ids: ['attendance-industry', 'taiyangniao-pro'],
      missing_required_mod_ids: [],
      missing_optional_mod_ids: [],
      missing_industry_mod_ids: [],
      baseline_ready: true,
      industry_mod_ready: true,
    }
    const stack = buildEnterpriseModStack(attendancePlan)
    const mods = [
      {
        id: 'taiyangniao-pro',
        workflow_employees: [{ id: 'attendance_ai', label: '考勤ai助手' }],
      },
      {
        id: 'artifact-generate-ai-employee',
        workflow_employees: [{ id: 'artifact_generate', label: '产物生成员工' }],
      },
      {
        id: 'xcagi-erp-domain-bridge',
        workflow_employees: [],
      },
    ]
    const scoped = filterModsForEnterpriseWorkflowRegistry(mods, stack)
    expect(scoped.map((m) => m.id)).toEqual(['taiyangniao-pro'])
    const merged = mergeModManifestEntries({ schemaVersion: 1, employees: [] }, scoped)
    expect(merged.map((e) => e.id)).toEqual(['attendance_ai'])
    expect(workflowRegistryEntryBelongsToStack(merged[0], stack)).toBe(true)
  })

  it('returns false when entry has no carrier and no mod id', () => {
    const stack = buildEnterpriseModStack(basePlan)
    expect(workflowRegistryEntryBelongsToStack({ carrierModId: '', hostModId: '' }, stack)).toBe(false)
  })

  it('returns false for custom phase employee carrier mod id', () => {
    const stack = buildEnterpriseModStack(basePlan)
    expect(
      workflowRegistryEntryBelongsToStack(
        {
          carrierModId: 'xcagi-workflow-employee-custom',
          hostModId: 'xcagi-workflow-employee-custom',
        },
        stack,
      ),
    ).toBe(false)
  })

  it('returns true for workflow carrier mod when stack is null', () => {
    expect(
      workflowRegistryEntryBelongsToStack(
        {
          carrierModId: 'xcagi-workflow-employee-attendance',
          hostModId: 'xcagi-workflow-employee-attendance',
        },
        null,
      ),
    ).toBe(true)
  })

  it('returns true for host bridge mod when stack is null', () => {
    expect(
      workflowRegistryEntryBelongsToStack({ carrierModId: 'xcagi-erp-domain-bridge', hostModId: 'xcagi-erp-domain-bridge' }, null),
    ).toBe(true)
  })

  it('returns false for unknown carrier mod when stack is null', () => {
    expect(workflowRegistryEntryBelongsToStack({ carrierModId: 'some-random-mod', hostModId: 'some-random-mod' }, null)).toBe(false)
  })

  it('filterModsForEnterpriseWorkflowRegistry filters source mods when stack is null', () => {
    const mods = [
      {
        id: 'xcagi-workflow-employee-attendance',
        workflow_employees: [{ id: 'att_ai', label: '考勤' }],
      },
      {
        id: 'xcagi-host-foundation-employee',
        type: 'employee_pack',
        workflow_employees: [{ id: 'gen_ai', label: '生成' }],
      },
    ]
    const scoped = filterModsForEnterpriseWorkflowRegistry(mods, null)
    expect(scoped.map((m) => m.id)).toEqual(['xcagi-workflow-employee-attendance'])
  })

  it('filterModsForEnterpriseWorkflowRegistry handles undefined mods', () => {
    const stack = buildEnterpriseModStack(basePlan)
    expect(filterModsForEnterpriseWorkflowRegistry(undefined, stack)).toEqual([])
  })

  it('filterModsForEnterpriseWorkflowRegistry skips mods with empty id', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const mods = [
      { id: '', workflow_employees: [{ id: 'e1', label: 'E1' }] },
      { id: 'coating-industry', workflow_employees: [{ id: 'e2', label: 'E2' }] },
    ]
    const scoped = filterModsForEnterpriseWorkflowRegistry(mods, stack)
    expect(scoped.map((m) => m.id)).toEqual(['coating-industry'])
  })

  it('filterModsForEnterpriseWorkflowRegistry skips mods with empty workflow_employees', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const mods = [
      { id: 'coating-industry', workflow_employees: [] },
      { id: 'xcagi-erp-domain-bridge', workflow_employees: [{ id: 'e1', label: 'E1' }] },
    ]
    const scoped = filterModsForEnterpriseWorkflowRegistry(mods, stack)
    expect(scoped.map((m) => m.id)).toEqual(['xcagi-erp-domain-bridge'])
  })

  it('filterModsForEnterpriseWorkflowRegistry skips employee pack entries', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const mods = [
      {
        id: 'xcagi-host-foundation-employee',
        type: 'employee_pack',
        workflow_employees: [{ id: 'e1', label: 'E1' }],
      },
      { id: 'coating-industry', workflow_employees: [{ id: 'e2', label: 'E2' }] },
    ]
    // coating-industry is in stack.packageModIds but the employee pack is not in stack
    // Actually, since stack contains coating-industry in packageModIds, coating-industry should be included
    const scoped = filterModsForEnterpriseWorkflowRegistry(mods, stack)
    // xcagi-host-foundation-employee is an employee pack, so it's filtered out
    expect(scoped.map((m) => m.id)).toEqual(['coating-industry'])
  })
})
