import { describe, expect, it } from 'vitest'
import { shouldTryWechatShipmentPreview } from './wechatShipmentDetect'

describe('wechatShipmentDetect', () => {
  it('returns false for empty text', () => {
    expect(shouldTryWechatShipmentPreview('')).toBe(false)
  })

  it('detects shipment doc keywords', () => {
    expect(shouldTryWechatShipmentPreview('帮我开发货单')).toBe(true)
  })

  it('detects quantity + spec pattern', () => {
    expect(shouldTryWechatShipmentPreview('10桶 A123 规格')).toBe(true)
  })

  it('uses primaryIntent context', () => {
    expect(shouldTryWechatShipmentPreview('x', { primaryIntent: 'shipment' })).toBe(true)
  })

  it('uses toolKey context', () => {
    expect(shouldTryWechatShipmentPreview('x', { toolKey: 'delivery' })).toBe(true)
  })

  it('combines label with detail keywords', () => {
    expect(
      shouldTryWechatShipmentPreview('你好', { intentLabel: '发货/物流' }),
    ).toBe(false)
    expect(
      shouldTryWechatShipmentPreview('10桶型号', { intentLabel: '发货/物流' }),
    ).toBe(true)
  })
})
