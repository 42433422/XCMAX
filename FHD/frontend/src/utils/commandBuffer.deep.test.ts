import { describe, it, expect, beforeEach } from 'vitest'
import {
  normalizeCommandText,
  detectIntentByRegex,
  isSalesContractCommandText,
  isPriceListCommandText,
  loadBuffer,
  saveBuffer,
  recordCommandHit,
  findRunnableCachedCommand,
  compactBuffer,
} from './commandBuffer'

describe('commandBuffer deep branches', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('normalizeCommandText handles empty and quotes', () => {
    expect(normalizeCommandText('')).toBe('')
    expect(normalizeCommandText('“开 始”')).toBe('开 始')
    expect(normalizeCommandText(null as unknown as string)).toBe('')
  })

  it('detectIntentByRegex returns null for empty and non-command', () => {
    expect(detectIntentByRegex('')).toBeNull()
    expect(detectIntentByRegex('你好啊')).toBeNull()
  })

  it('detectIntentByRegex prioritizes start_print exact', () => {
    expect(detectIntentByRegex('开始打印一下')?.intent).toBe('start_print')
  })

  it('detectIntentByRegex matches sales_contract and price_list', () => {
    expect(detectIntentByRegex('帮我生成销售合同')?.intent).toBe('sales_contract')
    expect(detectIntentByRegex('打印价目表')?.intent).toBe('price_list')
  })

  it('isSalesContractCommandText requires verb', () => {
    expect(isSalesContractCommandText('')).toBe(false)
    expect(isSalesContractCommandText('看下销售合同')).toBe(false)
    expect(isSalesContractCommandText('更新销售合同')).toBe(true)
  })

  it('isPriceListCommandText requires doc keyword and verb', () => {
    expect(isPriceListCommandText('')).toBe(false)
    expect(isPriceListCommandText('随便说说')).toBe(false)
    expect(isPriceListCommandText('生成报价表')).toBe(true)
  })

  it('findRunnableCachedCommand returns null without intent', () => {
    expect(findRunnableCachedCommand('你好')).toBeNull()
  })

  it('findRunnableCachedCommand returns null with empty buffer', () => {
    expect(findRunnableCachedCommand('生成价格表')).toBeNull()
  })

  it('findRunnableCachedCommand matches via contains strategy', () => {
    recordCommandHit({
      intent: 'price_list',
      handlerKey: 'handlePriceListCommand',
      message: '生成蓝色涂料价格表',
    })
    const hit = findRunnableCachedCommand('请帮我生成蓝色涂料价格表给客户')
    expect(hit?.strategy).toBe('contains')
  })

  it('recordCommandHit increments hitCount on repeat', () => {
    recordCommandHit({ intent: 'price_list', handlerKey: 'handlePriceListCommand', message: '生成价格表' })
    recordCommandHit({ intent: 'price_list', handlerKey: 'handlePriceListCommand', message: '生成价格表' })
    const buf = loadBuffer()
    const entry = buf.find((e) => e.normalizedText === '生成价格表')
    expect(entry?.hitCount).toBe(2)
  })

  it('recordCommandHit ignores empty normalized text', () => {
    recordCommandHit({ intent: 'price_list', handlerKey: 'handlePriceListCommand', message: '   ' })
    expect(loadBuffer()).toHaveLength(0)
  })

  it('compactBuffer drops stale entries past TTL', () => {
    const old = Date.now() - 60 * 24 * 60 * 60 * 1000
    const fresh = Date.now()
    const result = compactBuffer([
      { intent: 'price_list', handlerKey: 'handlePriceListCommand', normalizedText: 'old', hitCount: 1, createdAt: old, lastUsedAt: old },
      { intent: 'price_list', handlerKey: 'handlePriceListCommand', normalizedText: 'fresh', hitCount: 1, createdAt: fresh, lastUsedAt: fresh },
    ])
    expect(result.map((r) => r.normalizedText)).toEqual(['fresh'])
  })

  it('loadBuffer ignores malformed JSON', () => {
    localStorage.setItem('xcagi_command_buffer_v1', '{not json')
    expect(loadBuffer()).toEqual([])
  })

  it('loadBuffer drops entries missing required fields', () => {
    localStorage.setItem(
      'xcagi_command_buffer_v1',
      JSON.stringify([{ intent: '', handlerKey: '', normalizedText: '' }]),
    )
    expect(loadBuffer()).toEqual([])
  })
})
