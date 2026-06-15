import { describe, it, expect } from 'vitest'
import { wechatGroupBridgeApi } from './wechatGroupBridge'

describe('wechatGroupBridgeApi', () => {
  it('syncGroups returns success', async () => {
    const result = await wechatGroupBridgeApi.syncGroups()
    expect(result).toEqual({ success: true })
  })

  it('syncGroups accepts body parameter', async () => {
    const result = await wechatGroupBridgeApi.syncGroups({ key: 'value' })
    expect(result).toEqual({ success: true })
  })

  it('getContactContext returns success with empty messages', async () => {
    const result = await wechatGroupBridgeApi.getContactContext('contact-1')
    expect(result).toEqual({ success: true, messages: [] })
  })

  it('getContactContext accepts options', async () => {
    const result = await wechatGroupBridgeApi.getContactContext(123, { refresh: true })
    expect(result).toEqual({ success: true, messages: [] })
  })
})
