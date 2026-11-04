import { describe, expect, it } from 'vitest'
import { statusLabel } from '../../../admin-console/src/utils/statusLabel'

describe('statusLabel', () => {
  it('把常见状态码转成中文，大小写不敏感', () => {
    expect(statusLabel('completed')).toBe('已完成')
    expect(statusLabel('In_Progress')).toBe('进行中')
    expect(statusLabel('FAILED')).toBe('失败')
  })
  it('空值显示未知，未登记的值原样保留', () => {
    expect(statusLabel('')).toBe('未知')
    expect(statusLabel(null)).toBe('未知')
    expect(statusLabel('已完成')).toBe('已完成')
    expect(statusLabel('custom_x')).toBe('custom_x')
  })
})
