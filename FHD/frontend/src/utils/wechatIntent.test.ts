import { describe, expect, it } from 'vitest'
import {
  inferWechatCustomerIntent,
  isLabelPrintRelatedWechatIntent,
  isReceiptConfirmRelatedWechatIntent,
} from './wechatIntent'

describe('wechatIntent', () => {
  it('returns empty label for blank text', () => {
    expect(inferWechatCustomerIntent('')).toEqual({
      label: '空消息',
      detail: '未识别到文本内容。',
    })
  })

  it('detects price inquiry', () => {
    const r = inferWechatCustomerIntent('这个型号多少钱？')
    expect(r.label).toBe('询价/报价')
  })

  it('detects shipment/logistics', () => {
    const r = inferWechatCustomerIntent('发货单号多少')
    expect(r.label).toBe('发货/物流')
  })

  it('detects receipt confirm', () => {
    const r = inferWechatCustomerIntent('货已签收')
    expect(r.label).toBe('收货确认')
  })

  it('detects label/print', () => {
    const r = inferWechatCustomerIntent('帮忙打印标签')
    expect(r.label).toBe('标签/打印')
  })

  it('detects greeting', () => {
    const r = inferWechatCustomerIntent('在吗')
    expect(r.label).toBe('寒暄/触达')
  })

  it('falls back to pending analysis', () => {
    const r = inferWechatCustomerIntent('随便聊聊别的内容很长很长')
    expect(r.label).toBe('待分析')
  })

  it('isLabelPrintRelatedWechatIntent via ctx label', () => {
    expect(isLabelPrintRelatedWechatIntent('', { intentLabel: '标签/打印' })).toBe(true)
  })

  it('isLabelPrintRelatedWechatIntent via text', () => {
    expect(isLabelPrintRelatedWechatIntent('要条码贴纸')).toBe(true)
  })

  it('isReceiptConfirmRelatedWechatIntent via label', () => {
    expect(isReceiptConfirmRelatedWechatIntent('', { intentLabel: '收货确认' })).toBe(true)
  })

  it('isReceiptConfirmRelatedWechatIntent requires context for bare 确认', () => {
    expect(isReceiptConfirmRelatedWechatIntent('确认')).toBe(false)
    expect(isReceiptConfirmRelatedWechatIntent('确认收货')).toBe(true)
  })
})
