import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useServiceBridgeInstance } from './useServiceBridgeInstance'

const LS_MARKET_USER_JSON = 'xcagi_market_user_json'
const LS_INSTANCE_ID = 'xcagi_service_bridge_instance_id'
const LS_INSTANCE_NAME = 'xcagi_service_bridge_instance_name'

describe('useServiceBridgeInstance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns expected API shape', () => {
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId).toBeDefined()
    expect(inst.instanceName).toBeDefined()
    expect(inst.isSunbirdChannel).toBeDefined()
    expect(typeof inst.persistInstanceSnapshot).toBe('function')
  })

  it('instanceId defaults to enterprise-local when no market user and no cache', () => {
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('instanceName defaults to 本企业 when no brand and no market user', () => {
    const inst = useServiceBridgeInstance()
    expect(inst.instanceName.value).toBe('本企业')
  })

  it('isSunbirdChannel is false when no client primary ERP mod installed', () => {
    const inst = useServiceBridgeInstance()
    expect(inst.isSunbirdChannel.value).toBe(false)
  })

  it('instanceId uses market user id when present', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: 42, username: 'alice' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-42')
  })

  it('instanceId uses market user username when id missing', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ username: 'bob' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-bob')
  })

  it('instanceId prefers id over username', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: 'uid-99', username: 'charlie' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-uid-99')
  })

  it('instanceId uses cached localStorage value when no market user', () => {
    localStorage.setItem(LS_INSTANCE_ID, 'cached-instance-id')
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('cached-instance-id')
  })

  it('instanceId prefers market user over cached value', () => {
    localStorage.setItem(LS_INSTANCE_ID, 'cached-instance-id')
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: 7 }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-7')
  })

  it('instanceId handles invalid JSON in market user', () => {
    localStorage.setItem(LS_MARKET_USER_JSON, 'not-json')
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('instanceId handles non-object JSON in market user', () => {
    localStorage.setItem(LS_MARKET_USER_JSON, '"string-value"')
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('instanceId handles empty market user object', () => {
    localStorage.setItem(LS_MARKET_USER_JSON, '{}')
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('instanceId handles market user with empty id and username', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: '', username: '' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('instanceId handles market user with whitespace-only id', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: '   ', username: 'dave' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-dave')
  })

  it('instanceName uses cached localStorage value when no brand', () => {
    localStorage.setItem(LS_INSTANCE_NAME, 'Cached Brand')
    const inst = useServiceBridgeInstance()
    expect(inst.instanceName.value).toBe('Cached Brand')
  })

  it('instanceName uses market username when no brand and no cache', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ username: 'eve' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceName.value).toBe('eve')
  })

  it('persistInstanceSnapshot writes to localStorage', () => {
    const inst = useServiceBridgeInstance()
    inst.persistInstanceSnapshot()
    expect(localStorage.getItem(LS_INSTANCE_ID)).toBe('enterprise-local')
    expect(localStorage.getItem(LS_INSTANCE_NAME)).toBe('本企业')
  })

  it('persistInstanceSnapshot writes with market user', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: 100, username: 'frank' }),
    )
    const inst = useServiceBridgeInstance()
    inst.persistInstanceSnapshot()
    expect(localStorage.getItem(LS_INSTANCE_ID)).toBe('enterprise-100')
  })

  it('marketUserKey handles null input', () => {
    // 通过 instanceId 间接测试 marketUserKey(null)
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-local')
  })

  it('marketUserKey handles undefined id', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: undefined, username: 'grace' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-grace')
  })

  it('marketUserKey handles null id', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: null, username: 'heidi' }),
    )
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-heidi')
  })

  it('marketUserKey handles numeric id', () => {
    localStorage.setItem(
      LS_MARKET_USER_JSON,
      JSON.stringify({ id: 0, username: 'ivan' }),
    )
    // id=0 → String(0).trim() = '0' which is truthy as a string
    const inst = useServiceBridgeInstance()
    expect(inst.instanceId.value).toBe('enterprise-0')
  })
})
