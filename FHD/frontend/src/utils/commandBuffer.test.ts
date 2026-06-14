import { describe, expect, it, beforeEach } from 'vitest'
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
  getCommandBufferLimit,
} from './commandBuffer'

describe('commandBuffer', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('normalizes punctuation and case', () => {
    expect(normalizeCommandText('  开始打印吧！ ')).toBe('开始打印吧')
  })

  it('detects start_print intent', () => {
    expect(detectIntentByRegex('开始打印')).toEqual({
      intent: 'start_print',
      handlerKey: 'handleStartPrintCommand',
    })
  })

  it('detects sales contract', () => {
    expect(isSalesContractCommandText('生成销售合同')).toBe(true)
    expect(isSalesContractCommandText('销售合同')).toBe(false)
  })

  it('detects price list variants', () => {
    expect(isPriceListCommandText('打印报价表')).toBe(true)
    expect(isPriceListCommandText('价目表生成')).toBe(true)
  })

  it('records and finds cached command', () => {
    recordCommandHit({
      intent: 'price_list',
      handlerKey: 'handlePriceListCommand',
      message: '生成价格表',
    })
    const hit = findRunnableCachedCommand('生成价格表')
    expect(hit?.strategy).toBe('exact')
    expect(hit?.intent).toBe('price_list')
  })

  it('compacts buffer by limit', () => {
    const now = Date.now()
    const rows = Array.from({ length: 5 }, (_, i) => ({
      intent: 'price_list' as const,
      handlerKey: 'handlePriceListCommand' as const,
      normalizedText: `cmd-${i}`,
      hitCount: 1,
      createdAt: now,
      lastUsedAt: now - i,
    }))
    saveBuffer(rows)
    expect(loadBuffer()).toHaveLength(5)
    expect(getCommandBufferLimit()).toBe(200)
    const compacted = compactBuffer(
      Array.from({ length: 250 }, (_, i) => ({
        intent: 'price_list' as const,
        handlerKey: 'handlePriceListCommand' as const,
        normalizedText: `x-${i}`,
        hitCount: 1,
        createdAt: now,
        lastUsedAt: now - i,
      })),
    )
    expect(compacted).toHaveLength(200)
  })
})
