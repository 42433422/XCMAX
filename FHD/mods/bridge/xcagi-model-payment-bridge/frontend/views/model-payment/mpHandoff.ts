import { computed } from 'vue'
import type { MarketMembershipPlan } from './useMpMembershipPlans'

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

export function useMpHandoff() {
  const plansUrl = computed(() => withQuery(plansUrlBase, { source: 'fhd' }))
  const walletUrl = computed(() => withQuery(walletUrlBase, { source: 'fhd' }))
  function marketPlanUrl(plan: MarketMembershipPlan): string {
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
