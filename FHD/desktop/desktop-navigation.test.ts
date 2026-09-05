import { describe, expect, it, vi } from 'vitest'
import {
  findDeepLinkArg,
  handleDesktopWindowOpen,
  handleDesktopWillNavigate,
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

describe('browser handoff navigation contract', () => {
  it('delegates a trusted code URL to the system browser and denies an Electron child', () => {
    const url = 'https://xiu-ci.com/wallet?recharge=30#xcagi_code=' + 'a'.repeat(43)
    const open = vi.fn().mockResolvedValue(undefined)
    const warn = vi.fn()
    expect(handleDesktopWindowOpen(url, 17500, open, warn)).toBe('deny')
    expect(open).toHaveBeenCalledExactlyOnceWith(url)
    expect(warn).not.toHaveBeenCalled()
    expect(handleDesktopWindowOpen('about:blank', 17500, open, warn)).toBe('deny')
    expect(open).toHaveBeenCalledTimes(1)
  })

  it('never logs URL credentials even when shell errors echo them', async () => {
    const url = 'https://xiu-ci.com/wallet?xcagi_mt=reusable#xcagi_code=secret-code'
    const warn = vi.fn()
    handleDesktopWindowOpen(url, 17500, vi.fn().mockRejectedValue(new Error('failed ' + url)), warn)
    await Promise.resolve()
    handleDesktopWindowOpen('https://evil.example/?access_token=reusable#xcagi_code=secret-code', 17500, vi.fn(), warn)
    expect(warn).toHaveBeenCalledTimes(2)
    expect(JSON.stringify(warn.mock.calls)).not.toMatch(/reusable|secret-code|xcagi_mt|access_token|xcagi_code/)
  })
})

it('the will-navigate policy blocks external replacement without logging credentials', () => {
  const prevent = vi.fn()
  const warn = vi.fn()
  handleDesktopWillNavigate('https://xiu-ci.com/wallet?xcagi_mt=reusable#xcagi_code=secret-code', 17500, prevent, warn)
  expect(prevent).toHaveBeenCalledOnce()
  expect(JSON.stringify(warn.mock.calls)).not.toMatch(/reusable|secret-code|xcagi_code|xcagi_mt/)
  handleDesktopWillNavigate('http://127.0.0.1:17500/model-payment', 17500, prevent, warn)
  expect(prevent).toHaveBeenCalledOnce()
})
