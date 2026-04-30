import { beforeEach, describe, expect, it } from 'vitest'
import {
  detectIntentByRegex,
  findRunnableCachedCommand,
  getCommandBufferLimit,
  loadBuffer,
  recordCommandHit,
  saveBuffer
} from '@/utils/commandBuffer'

describe('command buffer smoke', () => {
  beforeEach(() => {
    saveBuffer([])
  })

  it('识别长句销售合同意图（动作词与关键词距离较远）', () => {
    const text = '帮我打一下百木鼎家具有限公司的一个销售合同一个8828和一个303和一桶的779'
    const hit = detectIntentByRegex(text)
    expect(hit?.intent).toBe('sales_contract')
    expect(hit?.handlerKey).toBe('handleSalesContractCommand')
  })

  it('记录后可精确命中并返回对应 handler', () => {
    const text = '帮我打一下百木鼎家具有限公司的一个销售合同一个8828和一个303和一桶的779'
    recordCommandHit({
      message: text,
      intent: 'sales_contract',
      handlerKey: 'handleSalesContractCommand'
    })

    const cached = findRunnableCachedCommand(text)
    expect(cached).not.toBeNull()
    expect(cached?.strategy).toBe('exact')
    expect(cached?.handlerKey).toBe('handleSalesContractCommand')
  })

  it('同意图近似句式可 contains 命中', () => {
    recordCommandHit({
      message: '帮我打一下百木鼎家具有限公司的一个销售合同一个8828和一个303和一桶的779',
      intent: 'sales_contract',
      handlerKey: 'handleSalesContractCommand'
    })
    const similar = '打一下销售合同 8828 303 779'
    const cached = findRunnableCachedCommand(similar)
    expect(cached).not.toBeNull()
    expect(cached?.handlerKey).toBe('handleSalesContractCommand')
  })

  it('超过上限时按 LRU 裁剪到 200 条', () => {
    const cap = getCommandBufferLimit()
    for (let i = 0; i < cap + 15; i += 1) {
      recordCommandHit({
        message: `生成价格表 客户${i}`,
        intent: 'price_list',
        handlerKey: 'handlePriceListCommand'
      })
    }
    const rows = loadBuffer()
    expect(rows.length).toBe(cap)
  })
})
