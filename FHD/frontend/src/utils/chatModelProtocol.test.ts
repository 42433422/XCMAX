import { describe, expect, it } from 'vitest'
import { stripModelToolProtocol } from './chatModelProtocol'

describe('stripModelToolProtocol', () => {
  it('preserves ordinary assistant text', () => {
    expect(stripModelToolProtocol('客户列表已打开')).toBe('客户列表已打开')
  })

  it('removes raw and encoded tool call transport syntax', () => {
    expect(stripModelToolProtocol('结果：<tool_call>hidden</tool_call>')).toBe('结果：')
    expect(stripModelToolProtocol('&amp;lt;tool_call&amp;gt;hidden&amp;lt;/tool_call&amp;gt;')).toBe('')
  })

  it('does not decode ordinary assistant text while hiding tool transport', () => {
    expect(stripModelToolProtocol('报价中的 &amp;amp; 保持原样')).toBe('报价中的 &amp;amp; 保持原样')
  })
})
