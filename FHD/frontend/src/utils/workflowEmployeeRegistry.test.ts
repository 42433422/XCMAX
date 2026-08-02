import { describe, expect, it } from 'vitest'
import {
  invalidateWorkflowEmployeeRegistryCache,
  loadRegistryFromJson,
  loadWorkflowEmployeeRegistry,
  loadWorkflowEmployeeRegistryCached,
  mergeModManifestEntries,
  resolveLabel,
} from './workflowEmployeeRegistry'

describe('workflowEmployeeRegistry', () => {
  it('loads empty registry', async () => {
    const r = await loadWorkflowEmployeeRegistry()
    expect(r.schemaVersion).toBe(1)
    expect(r.employees).toEqual([])
  })

  it('merges mod manifest entries', () => {
    const merged = mergeModManifestEntries(
      { schemaVersion: 1, employees: [] },
      [
        {
          id: 'demo-mod',
          name: 'Demo',
          workflow_employees: [{ id: 'wf-1', title: '工作流 · 测试员工' }],
        } as never,
      ],
    )
    expect(merged.some((e) => e.id === 'wf-1')).toBe(true)
  })

  it('resolveLabel returns entry label', () => {
    expect(
      resolveLabel({ id: 'a', label: 'A', kind: 'mod_extension', order: 1 }),
    ).toBe('A')
  })

  it('caches the registry until explicitly invalidated', async () => {
    invalidateWorkflowEmployeeRegistryCache()
    const first = await loadWorkflowEmployeeRegistryCached()
    const second = await loadWorkflowEmployeeRegistryCached()
    expect(second).toBe(first)

    invalidateWorkflowEmployeeRegistryCache()
    const refreshed = await loadWorkflowEmployeeRegistryCached()
    expect(refreshed).not.toBe(first)
    await expect(loadRegistryFromJson()).resolves.toEqual({ schemaVersion: 1, employees: [] })
  })

  it('resolves translated labels and falls back when translation is missing', () => {
    const entry = {
      id: 'agent',
      label: '原始标签',
      labelI18nKey: 'employee.agent',
      kind: 'mod_extension' as const,
      order: 1,
    }
    expect(resolveLabel(entry, () => '员工')).toBe('员工')
    expect(resolveLabel(entry, (key) => key)).toBe('原始标签')
    expect(resolveLabel(entry)).toBe('原始标签')
  })

  it('fills carrier and host metadata without duplicating registry employees', () => {
    const original = {
      id: 'wf-existing',
      label: '已有员工',
      kind: 'mod_extension' as const,
      order: 1,
    }
    const merged = mergeModManifestEntries(
      { schemaVersion: 1, employees: [original] },
      [
        {
          id: 'workflow-pack',
          workflow_employees: [
            { id: 'wf-existing', label: '重复员工', enterprise_mod_id: 'erp-host' },
            { id: ' ', label: '无效员工' },
            { id: 'wf-new', label: '', host_mod_id: 'explicit-host' },
          ],
        } as never,
      ],
    )

    expect(merged).toHaveLength(2)
    expect(merged[0]).toMatchObject({
      id: 'wf-existing',
      carrierModId: 'workflow-pack',
      hostModId: 'erp-host',
    })
    expect(merged[1]).toMatchObject({
      id: 'wf-new',
      label: 'wf-new',
      carrierModId: 'workflow-pack',
      hostModId: 'explicit-host',
      source: 'mod_manifest',
    })
  })
})
