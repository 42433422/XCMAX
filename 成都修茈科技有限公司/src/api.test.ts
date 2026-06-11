import { describe, expect, it } from 'vitest'
import { buildCheckoutSignData, generateSignature } from './api'

describe('buildCheckoutSignData', () => {
  it('对整数金额输出无小数点形式（与后端签名约定一致）', () => {
    const data = buildCheckoutSignData(
      {
        item_id: 12,
        plan_id: 'pro_monthly',
        subject: '订阅',
        total_amount: 100,
        wallet_recharge: false,
      },
      'req_abc',
      1700000000,
    )
    expect(data.total_amount).toBe('100')
    expect(data.item_id).toBe('12')
    expect(data.plan_id).toBe('pro_monthly')
    expect(data.timestamp).toBe('1700000000')
    expect(data.wallet_recharge).toBe('false')
  })

  it('对小数金额裁剪尾随 0', () => {
    const data = buildCheckoutSignData(
      { item_id: 0, total_amount: 12.3, wallet_recharge: true },
      'req_x',
      1700000000.7,
    )
    expect(data.total_amount).toBe('12.3')
    expect(data.timestamp).toBe('1700000000')
    expect(data.wallet_recharge).toBe('true')
  })

  it('非法/缺失字段降级为空串与 0', () => {
    const data = buildCheckoutSignData({}, '', '0')
    expect(data.item_id).toBe('0')
    expect(data.plan_id).toBe('')
    expect(data.subject).toBe('')
    expect(data.total_amount).toBe('0')
    expect(data.wallet_recharge).toBe('false')
    expect(data.request_id).toBe('')
  })

  it('subject / plan_id 自动 trim', () => {
    const data = buildCheckoutSignData(
      { plan_id: '  pro  ', subject: '  hi  ', total_amount: 1, wallet_recharge: false },
      'r',
      1,
    )
    expect(data.plan_id).toBe('pro')
    expect(data.subject).toBe('hi')
  })
})

describe('generateSignature', () => {
  it('对相同入参产出稳定签名（SHA-256，按 key 排序）', async () => {
    const payload = {
      a: '1',
      b: '2',
      c: 'abc',
    }
    const a = await generateSignature(payload, 'secret')
    const b = await generateSignature(payload, 'secret')
    expect(a).toBe(b)
    expect(a).toHaveLength(64)
    expect(/^[0-9a-f]+$/.test(a)).toBe(true)
  })

  it('不同 secret 输出不同签名', async () => {
    const payload = { a: '1' }
    const s1 = await generateSignature(payload, 'k1')
    const s2 = await generateSignature(payload, 'k2')
    expect(s1).not.toBe(s2)
  })

  it('字段顺序无关（按 key 字典序签名）', async () => {
    const p1 = { b: '2', a: '1' }
    const p2 = { a: '1', b: '2' }
    expect(await generateSignature(p1, 'k')).toBe(await generateSignature(p2, 'k'))
  })
})
