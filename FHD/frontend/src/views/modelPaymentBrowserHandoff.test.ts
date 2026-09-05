import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMarketBrowserHandoff } from '@/api/marketAccount'
import { handleDesktopWindowOpen } from '../../../desktop/desktop-navigation'
import { useMpHandoff } from '../../../mods/xcagi-model-payment-bridge/frontend/views/model-payment/mpHandoff'
import { useMpMarketActions } from '../../../mods/xcagi-model-payment-bridge/frontend/views/model-payment/useMpMarketActions'
vi.mock('@/api/marketAccount', () => ({ createMarketBrowserHandoff: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  Reflect.deleteProperty(window, 'xcagiDesktop')
})
describe('wallet and plans handoff', () => {
  it('rendering links never issues a code or includes reusable credentials or identity', () => {
    localStorage.setItem('xcagi_market_access_token', 'never-in-url')
    const links = useMpHandoff()
    expect(links.walletUrl.value).toBe('https://xiu-ci.com/wallet?source=fhd')
    expect(links.plansUrl.value).toBe('https://xiu-ci.com/plans?source=fhd')
    expect(links.rechargeLinks.value[1].url).toContain('recharge=30')
    expect(JSON.stringify(links.rechargeLinks.value)).not.toContain('never-in-url')
    expect(createMarketBrowserHandoff).not.toHaveBeenCalled()
  })
  it('opens a popup during the click and only navigates with a short code after issuing', async () => {
    const popup = { opener: window, closed: false, location: { replace: vi.fn() }, close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    vi.mocked(createMarketBrowserHandoff).mockImplementation(async () => {
      expect(open).toHaveBeenCalledWith('about:blank', '_blank')
      return { code: 'a'.repeat(43), target: '/wallet?recharge=30&source=fhd', purpose: 'wallet', expires_in: 60 }
    })
    const actions = useMpMarketActions({ marketPlanUrl: () => '', forceRefreshAll: vi.fn() })
    await actions.openMarketUrl('https://xiu-ci.com/wallet?recharge=30&source=fhd')
    expect(createMarketBrowserHandoff).toHaveBeenCalledWith('/wallet?recharge=30&source=fhd', 'wallet')
    expect(popup.opener).toBeNull()
    expect(popup.location.replace).toHaveBeenCalledWith('https://xiu-ci.com/wallet?recharge=30&source=fhd#xcagi_code=' + 'a'.repeat(43))
  })
  it('fails safely without navigating or copying an expired credential', async () => {
    const popup = { opener: null, closed: false, location: { replace: vi.fn() }, close: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    vi.mocked(createMarketBrowserHandoff).mockRejectedValue(new Error('secret-server-context'))
    const actions = useMpMarketActions({ marketPlanUrl: () => '', forceRefreshAll: vi.fn() })
    await actions.openMarketUrl('https://xiu-ci.com/plans?plan=vip')
    expect(popup.close).toHaveBeenCalledOnce()
    expect(popup.location.replace).not.toHaveBeenCalled()
    expect(actions.handoffError.value).toContain('重新登录')
    expect(actions.handoffError.value).not.toContain('secret')
  })
})

it('Electron opens the issued URL through the actual trusted external handler without local navigation', async () => {
  Object.defineProperty(window, 'xcagiDesktop', { value: {}, configurable: true })
  const external = vi.fn().mockResolvedValue(undefined)
  const warn = vi.fn()
  const open = vi.spyOn(window, 'open').mockImplementation((url) => {
    expect(handleDesktopWindowOpen(String(url), 17500, external, warn)).toBe('deny')
    return null // Electron returns no child window when delegating to the system browser.
  })
  const currentUrl = window.location.href
  vi.mocked(createMarketBrowserHandoff).mockResolvedValue({
    code: 'b'.repeat(43),
    target: '/plans?plan=vip',
    purpose: 'plans',
    expires_in: 60,
  })
  const actions = useMpMarketActions({ marketPlanUrl: () => '', forceRefreshAll: vi.fn() })
  await actions.openMarketUrl('https://xiu-ci.com/plans?plan=vip')
  const url = 'https://xiu-ci.com/plans?plan=vip#xcagi_code=' + 'b'.repeat(43)
  expect(open).toHaveBeenCalledExactlyOnceWith(url, '_blank', 'noopener,noreferrer')
  expect(external).toHaveBeenCalledExactlyOnceWith(url)
  expect(window.location.href).toBe(currentUrl)
  expect(warn).not.toHaveBeenCalled()
  expect(actions.handoffError.value).toBe('')
  Reflect.deleteProperty(window, 'xcagiDesktop')
})
