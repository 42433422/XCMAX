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
  optional_mod_ids: ['wechat-contacts-ai-employee'],
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
    expect(isWorkflowCarrierModId('wechat-contacts-ai-employee')).toBe(true)
  })

  it('filters registry entries to enterprise package mods', () => {
    const stack = buildEnterpriseModStack(basePlan)
    const entries = [
      { id: 'a', label: 'A', kind: 'mod_extension' as const, order: 1, carrierModId: 'coating-industry', hostModId: 'coating-industry' },
      { id: 'b', label: 'B', kind: 'mod_extension' as const, order: 2, carrierModId: 'artifact-generate-ai-employee', hostModId: 'artifact-generate-ai-employee' },
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
      optional_mod_ids: ['wechat-contacts-ai-employee'],
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
})
