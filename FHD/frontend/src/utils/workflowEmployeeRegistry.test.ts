import { describe, expect, it } from 'vitest'
import { loadWorkflowEmployeeRegistry, mergeModManifestEntries, resolveLabel } from './workflowEmployeeRegistry'

describe('workflowEmployeeRegistry', () => {
  it('loads empty registry', async () => {
    const r = await loadWorkflowEmployeeRegistry()
    expect(r.schemaVersion).toBe(1)
    expect(r.employees).toEqual([])
  })

  it('merges mod manifest entries', () => {
    const merged = mergeModManifestEntries({ schemaVersion: 1, employees: [] }, [
      {
        id: 'demo-mod',
        name: 'Demo',
        workflow_employees: [{ id: 'wf-1', title: '工作流 · 测试员工' }],
      } as never,
    ])
    expect(merged.some((e) => e.id === 'wf-1')).toBe(true)
  })

  it('keeps directory-sourced employees that match office pack patterns', () => {
    const merged = mergeModManifestEntries({ schemaVersion: 1, employees: [] }, [
      {
        id: 'csv-generate-employee',
        directory_sourced: true,
        workflow_employees: [{ id: 'csv-generate-employee', label: 'CSV 生成员' }],
      },
      {
        id: 'excel-generate-employee',
        workflow_employees: [{ id: 'excel-generate-employee', label: 'Excel 生成员' }],
      },
    ])
    // 统一员工目录已是可用员工：不再被办公包后缀规则排除；非目录来源仍排除。
    expect(merged.map((e) => e.id)).toEqual(['csv-generate-employee'])
  })

  it('carries prompt_only from directory rows into registry entries', () => {
    const merged = mergeModManifestEntries({ schemaVersion: 1, employees: [] }, [
      {
        id: 'wb-expert-demo',
        directory_sourced: true,
        workflow_employees: [{ id: 'wb-expert-demo', label: '对话型专家', prompt_only: true }],
      },
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0].prompt_only).toBe(true)
  })

  it('resolveLabel returns entry label', () => {
    expect(resolveLabel({ id: 'a', label: 'A', kind: 'mod_extension', order: 1 })).toBe('A')
  })
})
