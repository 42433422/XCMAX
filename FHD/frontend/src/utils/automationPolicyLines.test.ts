import { describe, expect, it } from 'vitest'
import { parseAutomationPolicyDoc } from '../../../admin-console/src/utils/automationPolicyLines'

describe('parseAutomationPolicyDoc', () => {
  it('maps six-line SSOT into admin cards', () => {
    const doc = parseAutomationPolicyDoc({
      version: '2026-06-03',
      description: '六线映射',
      coverage: { lines_in_scope: 2, note: '含伙伴部' },
      lines: {
        ops_acquisition: {
          label: 'O-A 获客部',
          steps: {
            O1: { name: '获客引流', primary: ['site-content-editor'], support: ['seo-sitemap-curator'] },
          },
        },
        ops_partner: {
          label: 'O-B 伙伴部',
          steps: {
            B1: { name: '伙伴接入', primary: ['partner-officer'], support: [] },
          },
        },
      },
    })
    expect(doc.version).toBe('2026-06-03')
    expect(doc.linesInScope).toBe(2)
    expect(doc.lines).toHaveLength(2)
    expect(doc.lines[0].label).toBe('O-A 获客部')
    expect(doc.lines[0].steps[0]).toEqual({
      id: 'O1',
      name: '获客引流',
      primary: ['site-content-editor'],
      support: ['seo-sitemap-curator'],
    })
  })

  it('tolerates empty/invalid payloads', () => {
    const doc = parseAutomationPolicyDoc(null)
    expect(doc.lines).toEqual([])
    expect(doc.linesInScope).toBe(0)
  })
})
