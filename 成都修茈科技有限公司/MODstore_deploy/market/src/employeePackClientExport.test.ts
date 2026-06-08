import { describe, expect, it } from 'vitest'
import {
  buildEmployeePackManifestFromV2,
  buildEmployeePackManifestFromWorkflow,
  buildEmployeePackZipFromV2,
  normalizeModId,
} from './employeePackClientExport'

describe('employeePackClientExport', () => {
  it('normalizes valid mod ids and rejects unsafe ids', () => {
    expect(normalizeModId(' Sales.Agent_1 ')).toBe('sales.agent_1')
    expect(normalizeModId('-bad')).toBeNull()
    expect(normalizeModId('bad space')).toBeNull()
  })

  it('builds an employee pack manifest from a workflow entry', () => {
    const result = buildEmployeePackManifestFromWorkflow(
      'sales-mod',
      { name: '销售 Mod', version: '2.0.0' },
      { id: 'assistant', label: '销售助手', capabilities: ['chat'] },
    )

    expect(result.error).toBe('')
    expect(result.manifest?.id).toBe('sales-mod-assistant')
    const employeeOut = (result.manifest as Record<string, any> | null)?.employee as
      | { label?: string }
      | undefined
    expect(employeeOut?.label).toBe('销售助手')
  })

  it('builds v2 manifests and zips from employee config', () => {
    const { manifest, packId } = buildEmployeePackManifestFromV2({
      config: {
        identity: { id: 'agent-1', name: 'Agent 1', version: '1.0.0' },
        collaboration: { workflow: { workflow_id: 7 } },
        cognition: {},
      },
      industry: '零售',
      price: 12,
    })
    const zip = buildEmployeePackZipFromV2({ config: manifest.employee_config_v2, packId })

    expect(packId).toBe('agent-1')
    expect(manifest.commerce).toEqual({ industry: '零售', price: 12 })
    expect(zip.blob.type).toBe('application/zip')
  })
})
