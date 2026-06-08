/**
 * 解析 GET /api/products/units 的多种响应体，供产品页「客户」筛选下拉与冒烟测试共用。
 */
export function productUnitsArrayFromApi(resp: unknown): unknown[] {
  if (!resp || typeof resp !== 'object') return []
  const o = resp as Record<string, unknown>
  if (Array.isArray(o.data)) return o.data
  if (Array.isArray(o.units)) return o.units
  const nested = o.data
  if (nested && typeof nested === 'object' && Array.isArray((nested as { units?: unknown[] }).units)) {
    return (nested as { units: unknown[] }).units
  }
  return []
}
