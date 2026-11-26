import { describe, expect, it } from 'vitest'
import { createLatestBusinessRead, requireBusinessSuccess } from './businessPageLifecycle'

describe('business page lifecycle', () => {
  it('aborts the old read and keeps the latest read current even if the old one finishes', () => {
    const reads = createLatestBusinessRead()
    const old = reads.begin()
    const next = reads.begin()
    expect(old.signal.aborted).toBe(true)
    expect(old.isCurrent()).toBe(false)
    old.finish()
    expect(next.isCurrent()).toBe(true)
    expect(reads.isPending()).toBe(true)
    next.finish()
    expect(reads.isPending()).toBe(false)
  })
  it('retires pending reads on page leave', () => {
    const reads = createLatestBusinessRead()
    const read = reads.begin()
    reads.cancel()
    expect(read.signal.aborted).toBe(true)
    expect(read.isCurrent()).toBe(false)
    expect(reads.isPending()).toBe(false)
  })
  it('requires explicit successful receipts before publishing successful mutations', () => {
    expect(() => requireBusinessSuccess({ success: false, message: '无权限' }, '保存失败')).toThrow('无权限')
    expect(() => requireBusinessSuccess({} as { success: boolean }, '保存失败')).toThrow('保存失败')
    expect(requireBusinessSuccess({ success: true, data: 0 }, '保存失败').data).toBe(0)
  })
})
