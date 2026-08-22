import { describe, expect, it } from 'vitest'
import {
  findDeepLinkArg,
  parseDesktopDeepLink,
  isBenignDesktopLoadAbort,
  isTrustedDesktopOrigin,
} from './desktop-navigation'

describe('findDeepLinkArg', () => {
  it('从 argv 中提取 xcagi:// 深链', () => {
    const argv = ['/usr/bin/xcagi', '--flag', 'xcagi://chat?q=hello']
    expect(findDeepLinkArg(argv)).toBe('xcagi://chat?q=hello')
  })

  it('无深链时返回 null', () => {
    expect(findDeepLinkArg(['/usr/bin/xcagi', '--flag'])).toBeNull()
  })

  it('空/非数组入参安全返回 null', () => {
    expect(findDeepLinkArg(undefined)).toBeNull()
    expect(findDeepLinkArg(null)).toBeNull()
    expect(findDeepLinkArg([])).toBeNull()
  })
})

describe('parseDesktopDeepLink', () => {
  it('解析 host / path / params', () => {
    const parsed = parseDesktopDeepLink('xcagi://chat?q=%E4%BD%A0%E5%A5%BD&id=42')
    expect(parsed).not.toBeNull()
    expect(parsed!.host).toBe('chat')
    expect(parsed!.path).toBe('')
    expect(parsed!.params.q).toBe('你好')
    expect(parsed!.params.id).toBe('42')
    expect(parsed!.raw).toBe('xcagi://chat?q=%E4%BD%A0%E5%A5%BD&id=42')
  })

  it('非 xcagi 协议返回 null', () => {
    expect(parseDesktopDeepLink('https://example.com/a')).toBeNull()
    expect(parseDesktopDeepLink('kellai://messages')).toBeNull()
  })

  it('非法/空入参返回 null', () => {
    expect(parseDesktopDeepLink(undefined)).toBeNull()
    expect(parseDesktopDeepLink('')).toBeNull()
    expect(parseDesktopDeepLink('not a url')).toBeNull()
  })
})

describe('既有权重行为回归', () => {
  it('是合法桌面来源', () => {
    expect(isTrustedDesktopOrigin('http://127.0.0.1:5100/', 5100)).toBe(true)
    expect(isTrustedDesktopOrigin('http://localhost:5100/', 5100)).toBe(true)
  })

  it('err_aborted 且已在可信页视为良性加载中断', () => {
    expect(isBenignDesktopLoadAbort(new Error('net::ERR_ABORTED'), 'http://127.0.0.1:5100/', 5100)).toBe(true)
  })
})