import { describe, expect, it } from 'vitest'
import { strFromU8, unzipSync } from 'fflate'
import {
  buildEmployeePackManifestFromV2,
  buildEmployeePackManifestFromWorkflow,
  buildEmployeePackZipFromPanel,
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

  it('handles workflow manifest fallbacks and invalid workflow zip input', async () => {
    expect(buildEmployeePackManifestFromWorkflow('', {}, {}).error).toBe('Mod id 无效')

    const fallback = buildEmployeePackManifestFromWorkflow(
      'mod',
      { dependencies: { host: '>=2' }, description: '默认描述' },
      null,
      3,
    )
    expect(fallback.error).toBe('')
    expect(fallback.manifest?.id).toBe('mod-emp3')
    expect(fallback.manifest?.dependencies).toEqual({ host: '>=2' })

    expect(() => buildEmployeePackZipFromPanel({
      modId: '',
      workflowIndex: 0,
      modManifest: {},
      workflowJsonText: '{}',
    })).toThrow('缺少 Mod id')
    expect(() => buildEmployeePackZipFromPanel({
      modId: 'mod',
      workflowIndex: 0,
      modManifest: {},
      workflowJsonText: '{bad json',
    })).toThrow('workflow_employees JSON 无法解析')
    expect(() => buildEmployeePackZipFromPanel({
      modId: 'mod',
      workflowIndex: 0,
      modManifest: {},
      workflowJsonText: '[]',
    })).toThrow('workflow 条目须为 JSON 对象')

    const zip = buildEmployeePackZipFromPanel({
      modId: 'mod',
      workflowIndex: '2',
      modManifest: null,
      workflowJsonText: JSON.stringify({
        id: '生成 员',
        panel_title: '面板标题',
        panel_summary: '面板说明',
        capabilities: [' chat ', '', 123, 'run'],
      }),
    })
    expect(zip.packId).toBe('mod-emp2')
    const bytes = new Uint8Array(await zip.blob.arrayBuffer())
    const files = unzipSync(bytes)
    const manifest = JSON.parse(strFromU8(files['mod-emp2/manifest.json']))
    expect(manifest.employee.capabilities).toEqual(['chat', 'run'])
    expect(manifest.name).toBe('面板标题')
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

  it('builds v2 manifests with defaults, sanitized ids, capabilities, commerce fallback, and extra files', async () => {
    const { manifest, packId } = buildEmployeePackManifestFromV2({
      config: {
        identity: { id: '_Agent ID', name: '', version: '' },
        collaboration: { workflow: { workflow_id: 'not-a-number' } },
        workflow_employees: 'bad',
        perception: {},
        memory: {},
        cognition: {},
        actions: {},
        management: {},
        commerce: { industry: '金融', price: '5' },
      },
      packId: '_Pack ID',
      price: Number.NaN,
    })

    expect(packId).toBe('x_pack-id')
    expect(manifest.name).toBe('x_pack-id')
    expect(manifest.version).toBe('1.0.0')
    expect((manifest.employee as any).workflow_id).toBe(0)
    expect((manifest.employee as any).capabilities).toEqual([
      'perception',
      'memory',
      'cognition',
      'actions',
      'management',
      'collaboration',
    ])
    expect(manifest.workflow_employees).toEqual([])
    expect(manifest.commerce).toEqual({ industry: '金融', price: 5 })

    const zip = buildEmployeePackZipFromV2({
      config: manifest.employee_config_v2,
      packId,
      files: {
        '/docs/readme.txt': 'hello',
        '/bin/raw.dat': new Uint8Array([1, 2, 3]),
        '': 'skip me',
        '/nil.txt': null as unknown as string,
      },
    })
    const files = unzipSync(new Uint8Array(await zip.blob.arrayBuffer()))
    expect(strFromU8(files['x_pack-id/docs/readme.txt'])).toBe('hello')
    expect(files['x_pack-id/bin/raw.dat']).toEqual(new Uint8Array([1, 2, 3]))
    expect(strFromU8(files['x_pack-id/nil.txt'])).toBe('')
    expect(files['x_pack-id/manifest.json']).toBeTruthy()
    expect(files['__main__.py']).toBeTruthy()
  })
})
