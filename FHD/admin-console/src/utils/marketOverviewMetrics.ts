/** 管理端市场总览：把 /api/admin/status 响应收成业务指标卡片数据。 */

export type MarketOverviewStats = {
  ok: boolean
  totalCatalogItems: number | null
  totalUsers: number | null
  raw: Record<string, unknown>
}

function asNonNegInt(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const n = Math.trunc(value)
  return n >= 0 ? n : null
}

export function parseMarketOverviewStats(payload: unknown): MarketOverviewStats {
  const raw = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {}
  const ok = raw.ok === true || raw.success === true
  return {
    ok,
    totalCatalogItems: asNonNegInt(raw.total_catalog_items),
    totalUsers: asNonNegInt(raw.total_users),
    raw,
  }
}

export function formatMetric(value: number | null): string {
  return value == null ? '待核实' : String(value)
}
