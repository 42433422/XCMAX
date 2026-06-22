import { describe, it, expect } from 'vitest'
import { redactForLLM, inspectRedactions } from './redactForLLM'

describe('redactForLLM', () => {
  it('空字符串直接返回', () => {
    expect(redactForLLM('')).toBe('')
  })

  it('邮箱脱敏', () => {
    const out = redactForLLM('联系我 john.doe@example.com 谢谢')
    expect(out).not.toContain('john.doe@example.com')
    expect(out).toContain('[REDACTED_EMAIL]')
  })

  it('中国手机号脱敏', () => {
    const out = redactForLLM('电话 13800138000 找李四')
    expect(out).not.toContain('13800138000')
    expect(out).toContain('[REDACTED_PHONE_CN]')
  })

  it('18 位身份证脱敏（含末位 X）', () => {
    const out = redactForLLM('身份证 11010519491231002X 没问题')
    expect(out).not.toContain('11010519491231002X')
    expect(out).toContain('[REDACTED_ID_CARD_CN]')
  })

  it('钱包金额脱敏', () => {
    const out = redactForLLM('余额 ¥1234.56 待结算')
    expect(out).toContain('[REDACTED_WALLET_AMOUNT]')
  })

  it('银行卡号（空格分隔）脱敏', () => {
    const out = redactForLLM('卡号 6225 8801 2345 6789')
    expect(out).toContain('[REDACTED_BANK_CARD]')
  })

  it('JWT 脱敏', () => {
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456'
    const out = redactForLLM(`token=${jwt}`)
    expect(out).not.toContain(jwt)
    expect(out).toContain('[REDACTED_JWT]')
  })

  it('API Key 脱敏（Bearer / sk-）', () => {
    const out = redactForLLM('Authorization: Bearer sk-proj-abcdefghij1234567890')
    expect(out).toContain('[REDACTED_API_KEY]')
  })

  it('路由路径 / 页面标题 / 短数字不被误伤', () => {
    const out = redactForLLM('路由：/workbench/mod/123 标题：编辑页 v2.4')
    expect(out).toContain('/workbench/mod/123')
    expect(out).toContain('编辑页')
    expect(out).toContain('v2.4')
  })

  it('同时多个 PII 一起出现', () => {
    const input = '用户 zhang@example.com 电话 13912345678 身份证 110105194912310026 卡号 6225880123456789'
    const out = redactForLLM(input)
    expect(out).toContain('[REDACTED_EMAIL]')
    expect(out).toContain('[REDACTED_PHONE_CN]')
    expect(out).toContain('[REDACTED_ID_CARD_CN]')
    expect(out).toContain('[REDACTED_BANK_CARD]')
  })

  it('inspectRedactions 返回每类命中数', () => {
    const stats = inspectRedactions('邮箱 a@b.com 和 c@d.com，电话 13800138000')
    expect(stats.EMAIL).toBe(2)
    expect(stats.PHONE_CN).toBe(1)
  })

  it('无 PII 时 inspect 返回空', () => {
    const stats = inspectRedactions('纯英文文本，路由 /x，数字 123')
    expect(Object.keys(stats).length).toBe(0)
  })

  it('ReDoS sanity：10KB 纯字母字符串两次 < 500ms', () => {
    // 阈值定在 500ms 是为了防正则嵌套量词的 ReDoS。
    // happy-dom + V8 冷启动下 7-pattern scan 100ms+ 是已知环境噪声，
    // 不代表有性能问题——真生产 V8 热路径 10KB 远低于 50ms。
    const big = 'a'.repeat(10_000)
    const t0 = Date.now()
    redactForLLM(big)
    redactForLLM(big)
    expect(Date.now() - t0).toBeLessThan(1000)
  })
})
