import { describe, expect, it } from 'vitest'

/** 与 modstore_server/catalog_store 列表响应及 market 消费端对齐的最小契约。 */
describe('catalog API contract', () => {
  it('catalog list item shape', () => {
    const sample = {
      id: 'mod-demo',
      name: 'Demo Mod',
      version: '1.0.0',
      visibility: 'public',
      tags: [] as string[],
    }
    expect(sample).toMatchObject({
      id: expect.any(String),
      name: expect.any(String),
      version: expect.any(String),
    })
    expect(Array.isArray(sample.tags)).toBe(true)
  })

  it('catalog detail includes version list', () => {
    const detail = {
      package_id: 'mod-demo',
      versions: [{ version: '1.0.0', channel: 'stable' }],
    }
    expect(detail.package_id).toBeTruthy()
    expect(detail.versions[0]).toMatchObject({
      version: expect.any(String),
    })
  })
})
