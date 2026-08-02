import { describe, expect, it } from 'vitest'
import { buildChatSoftwareCapabilities, resolveChatSoftwareRouteKey } from './chatCapabilityCatalog'

describe('chatCapabilityCatalog', () => {
  it('exposes the host navigation and guarded tool contract', () => {
    const catalog = buildChatSoftwareCapabilities()
    expect(catalog.version).toBe(1)
    expect(catalog.navigation).toEqual(expect.arrayContaining([
      expect.objectContaining({ route_key: 'chat' }),
      expect.objectContaining({ route_key: 'customers' }),
    ]))
    expect(catalog.control_contract).toEqual(expect.arrayContaining([
      expect.stringContaining('confirmation'),
    ]))
  })

  it('accepts only registered route keys', () => {
    expect(resolveChatSoftwareRouteKey('customers')).toBe('customers')
    expect(resolveChatSoftwareRouteKey('https://example.com')).toBe('')
    expect(resolveChatSoftwareRouteKey('../admin')).toBe('')
  })
})
