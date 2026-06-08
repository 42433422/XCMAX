import { describe, expect, it } from 'vitest'
import {
  REFUND_REASON_MIN,
  REFUND_REASON_MAX,
  formatRefundTime,
  refundStatusText,
  refundStatusTone,
  validateRefundForm,
  refundStatusMap,
} from './refundStatus'

describe('refund helpers', () => {
  it('validates refund form before submit', () => {
    expect(validateRefundForm('', '有效原因')).toBe('请填写订单号')
    expect(validateRefundForm('ORD1', '短')).toContain('至少')
    expect(validateRefundForm('ORD1', '这是一个有效退款原因')).toBe('')
  })

  it('maps refund statuses to readable labels', () => {
    expect(refundStatusText('pending')).toBe('待审核')
    expect(refundStatusText('refunded')).toBe('已退款')
    expect(refundStatusText('unknown_status')).toBe('unknown_status')
  })

  it('formats refund time defensively', () => {
    expect(formatRefundTime('')).toBe('—')
    expect(formatRefundTime('bad-date')).toBe('bad-date')
    expect(formatRefundTime('2026-01-02T03:04:05Z')).toContain('2026')
  })
})

describe('refundStatusMap', () => {
  it('contains all expected statuses', () => {
    expect(refundStatusMap).toHaveProperty('pending')
    expect(refundStatusMap).toHaveProperty('approved')
    expect(refundStatusMap).toHaveProperty('rejected')
    expect(refundStatusMap).toHaveProperty('refunded')
    expect(refundStatusMap).toHaveProperty('refund_failed')
  })

  it('each status has label and tone', () => {
    for (const [key, val] of Object.entries(refundStatusMap)) {
      expect(val.label).toBeTruthy()
      expect(val.tone).toBeTruthy()
    }
  })
})

describe('refundStatusTone', () => {
  it('returns correct tone for known statuses', () => {
    expect(refundStatusTone('pending')).toBe('pending')
    expect(refundStatusTone('approved')).toBe('approved')
    expect(refundStatusTone('rejected')).toBe('rejected')
    expect(refundStatusTone('refunded')).toBe('approved')
    expect(refundStatusTone('refund_failed')).toBe('failed')
  })

  it('returns unknown for unrecognized status', () => {
    expect(refundStatusTone('nonexistent')).toBe('unknown')
  })

  it('returns unknown for empty string', () => {
    expect(refundStatusTone('')).toBe('unknown')
  })
})

describe('validateRefundForm edge cases', () => {
  it('rejects null order number', () => {
    expect(validateRefundForm(null, '有效退款原因')).toBe('请填写订单号')
  })

  it('rejects undefined order number', () => {
    expect(validateRefundForm(undefined, '有效退款原因')).toBe('请填写订单号')
  })

  it('rejects whitespace-only order number', () => {
    expect(validateRefundForm('   ', '有效退款原因')).toBe('请填写订单号')
  })

  it('rejects reason shorter than minimum', () => {
    expect(validateRefundForm('ORD1', '1234')).toContain('至少')
  })

  it('accepts reason at minimum length boundary', () => {
    const minReason = 'a'.repeat(REFUND_REASON_MIN)
    expect(validateRefundForm('ORD1', minReason)).toBe('')
  })

  it('rejects reason exceeding maximum length', () => {
    const longReason = 'a'.repeat(REFUND_REASON_MAX + 1)
    expect(validateRefundForm('ORD1', longReason)).toContain('最多')
  })

  it('accepts reason at maximum length boundary', () => {
    const maxReason = 'a'.repeat(REFUND_REASON_MAX)
    expect(validateRefundForm('ORD1', maxReason)).toBe('')
  })

  it('trims whitespace before validation', () => {
    expect(validateRefundForm('  ORD1  ', '  有效退款原因  ')).toBe('')
  })

  it('rejects null reason', () => {
    expect(validateRefundForm('ORD1', null)).toContain('至少')
  })
})

describe('refundStatusText edge cases', () => {
  it('returns 未知 for empty string', () => {
    expect(refundStatusText('')).toBe('未知')
  })

  it('returns approved label', () => {
    expect(refundStatusText('approved')).toBe('已退回钱包')
  })

  it('returns rejected label', () => {
    expect(refundStatusText('rejected')).toBe('已拒绝')
  })

  it('returns refund_failed label', () => {
    expect(refundStatusText('refund_failed')).toBe('退款失败')
  })
})

describe('formatRefundTime edge cases', () => {
  it('returns dash for null', () => {
    expect(formatRefundTime(null)).toBe('—')
  })

  it('returns dash for undefined', () => {
    expect(formatRefundTime(undefined)).toBe('—')
  })

  it('returns dash for 0', () => {
    expect(formatRefundTime(0)).toBe('—')
  })

  it('returns dash for false', () => {
    expect(formatRefundTime(false as any)).toBe('—')
  })

  it('formats with custom locale', () => {
    const result = formatRefundTime('2026-01-02T03:04:05Z', 'en-US')
    expect(result).toContain('2026')
  })

  it('returns raw value for invalid date string', () => {
    expect(formatRefundTime('not-a-date')).toBe('not-a-date')
  })
})
