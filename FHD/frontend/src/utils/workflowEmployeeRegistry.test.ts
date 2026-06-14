import { describe, expect, it } from 'vitest'
import {
  loadWorkflowEmployeeRegistry,
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
})
