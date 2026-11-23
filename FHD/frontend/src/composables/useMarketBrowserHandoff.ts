import { computed, ref } from 'vue'
import { createMarketBrowserHandoff } from '@/api/marketAccount'
import { isDesktopShell } from '@/utils/desktopShell'

type MarketPlanLink = { id: string; tier: string }

export const marketBase = String(import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com').replace(/\/$/, '')
const plansUrlBase = String(import.meta.env.VITE_MARKET_PLANS_URL || `${marketBase}/plans`)
const walletUrlBase = String(import.meta.env.VITE_MARKET_WALLET_URL || `${marketBase}/wallet`)

/** Navigation URLs contain business parameters only, never account credentials. */
export function withQuery(base: string, params: Record<string, string | number>): string {
  const url = new URL(base, marketBase)
  if (url.origin !== new URL(marketBase).origin || !['/wallet', '/plans'].includes(url.pathname)) {
    throw new Error('不支持此市场地址')
  }
  url.hash = ''
  url.search = ''
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value))
  return url.toString()
}

export function useMarketUrls() {
  const plansUrl = computed(() => withQuery(plansUrlBase, { source: 'fhd' }))
  const walletUrl = computed(() => withQuery(walletUrlBase, { source: 'fhd' }))
  function marketPlanUrl(plan: MarketPlanLink): string {
    return withQuery(plansUrlBase, { plan: plan.id, tier: plan.tier, source: 'fhd' })
  }
  const rechargeLinks = computed(() =>
    [10, 30, 100, 300].map((amount) => ({
      amount,
      label: amount < 100 ? '轻量补充' : '高频调用',
      url: withQuery(walletUrlBase, { recharge: amount, source: 'fhd' }),
    })),
  )
  return { plansUrl, walletUrl, marketPlanUrl, rechargeLinks }
}

export function useMarketBrowserHandoff(deps: { marketPlanUrl: (plan: MarketPlanLink) => string; forceRefreshAll: () => Promise<void> }) {
  const handoffError = ref('')
  const handoffBusy = ref(false)

  async function openMarketUrl(rawUrl: string): Promise<void> {
    if (handoffBusy.value) return
    handoffError.value = ''
    handoffBusy.value = true
    let popup: Window | null = null
    try {
      const url = new URL(rawUrl)
      if (url.origin !== new URL(marketBase).origin || !['/wallet', '/plans'].includes(url.pathname)) {
        throw new Error('不支持此市场地址')
      }
      const desktop = isDesktopShell()
      // Browser popups need the click gesture. Electron denies about:blank and
      // delegates trusted external URLs to the system browser instead.
      if (!desktop) {
        popup = window.open('about:blank', '_blank')
        if (popup) popup.opener = null
      }
      const purpose = url.pathname === '/wallet' ? 'wallet' : 'plans'
      const issued = await createMarketBrowserHandoff(url.pathname + url.search, purpose)
      const target = new URL(issued.target, marketBase)
      if (target.origin !== url.origin || target.pathname !== url.pathname || target.hash || issued.purpose !== purpose) {
        throw new Error('登录连接无效')
      }
      target.hash = `xcagi_code=${encodeURIComponent(issued.code)}`
      if (desktop) window.open(target.toString(), '_blank', 'noopener,noreferrer')
      else if (popup && !popup.closed) popup.location.replace(target.toString())
      else window.location.assign(target.toString())
      const refreshOnReturn = () => {
        if (document.visibilityState === 'visible') {
          void deps.forceRefreshAll()
          document.removeEventListener('visibilitychange', refreshOnReturn)
        }
      }
      document.addEventListener('visibilitychange', refreshOnReturn)
      setTimeout(() => document.removeEventListener('visibilitychange', refreshOnReturn), 30_000)
    } catch {
      popup?.close()
      // Never log errors/URLs or copy a login credential to the clipboard.
      handoffError.value = '暂时无法连接市场账号，请重试或重新登录。也可右键打开钱包或套餐链接后登录。'
    } finally {
      handoffBusy.value = false
    }
  }

  async function openMarketPlan(plan: MarketPlanLink): Promise<void> {
    await openMarketUrl(deps.marketPlanUrl(plan))
  }
  return { handoffError, handoffBusy, openMarketUrl, openMarketPlan }
}
