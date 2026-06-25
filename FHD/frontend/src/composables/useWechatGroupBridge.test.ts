import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWechatGroupBridge } from './useWechatGroupBridge'

describe('useWechatGroupBridge', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns expected API shape', () => {
    const bridge = useWechatGroupBridge()
    expect(Array.isArray(bridge.feed.value)).toBe(true)
    expect(bridge.loading.value).toBe(false)
    expect(bridge.syncing.value).toBe(false)
    expect(typeof bridge.loadFeed).toBe('function')
    expect(typeof bridge.syncGroups).toBe('function')
    expect(typeof bridge.formatFeedItem).toBe('function')
  })

  it('initializes feed as empty array', () => {
    const bridge = useWechatGroupBridge()
    expect(bridge.feed.value).toEqual([])
  })

  it('loadFeed does not throw and keeps loading false', async () => {
    const bridge = useWechatGroupBridge()
    await expect(bridge.loadFeed(1, 10, { sync: true })).resolves.toBeUndefined()
    expect(bridge.loading.value).toBe(false)
  })

  it('loadFeed works without arguments', async () => {
    const bridge = useWechatGroupBridge()
    await expect(bridge.loadFeed()).resolves.toBeUndefined()
  })

  it('syncGroups does not throw and keeps syncing false', async () => {
    const bridge = useWechatGroupBridge()
    await expect(bridge.syncGroups()).resolves.toBeUndefined()
    expect(bridge.syncing.value).toBe(false)
  })

  it('formatFeedItem returns the input unchanged', () => {
    const bridge = useWechatGroupBridge()
    const item = { id: 1, name: 'group' }
    expect(bridge.formatFeedItem(item)).toBe(item)
  })

  it('formatFeedItem handles null and primitive inputs', () => {
    const bridge = useWechatGroupBridge()
    expect(bridge.formatFeedItem(null)).toBeNull()
    expect(bridge.formatFeedItem(undefined)).toBeUndefined()
    expect(bridge.formatFeedItem('hello')).toBe('hello')
    expect(bridge.formatFeedItem(42)).toBe(42)
  })
})
