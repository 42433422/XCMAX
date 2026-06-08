/** LLM 定价展示：目录内嵌 pricing 与全局 billing_settings。 */

export interface LlmModelPricing {
  source?: 'db' | 'default' | string
  input_price_per_1k?: number
  output_price_per_1k?: number
  min_charge?: number
  service_fee_multiplier?: number
  official_markup_multiplier?: number
  effective_input_per_1k?: number
  effective_output_per_1k?: number
  platform_billing_ok?: boolean
  official_input_per_1k?: number | null
  official_output_per_1k?: number | null
  official_synced_at?: string | null
  official_source?: string
  suggested_input_per_1k?: number | null
  suggested_output_per_1k?: number | null
}

export interface LlmBillingSettings {
  service_fee_multiplier?: number
  default_input_price_per_1k?: number
  default_output_price_per_1k?: number
  default_min_charge?: number
}

export interface LlmModelRow {
  id?: string
  pricing?: LlmModelPricing
  capability?: { platform_billing_ok?: boolean; [key: string]: unknown }
}

function fmtYuan(n: number | undefined | null, digits = 4): string {
  const x = Number(n)
  if (!Number.isFinite(x)) return '—'
  return x.toFixed(digits).replace(/\.?0+$/, '') || '0'
}

export function formatPricePer1kLine(pricing: LlmModelPricing | null | undefined): string {
  if (!pricing) return ''
  const ein = pricing.effective_input_per_1k ?? (pricing.input_price_per_1k ?? 0) * (pricing.service_fee_multiplier ?? 1)
  const eout =
    pricing.effective_output_per_1k ?? (pricing.output_price_per_1k ?? 0) * (pricing.service_fee_multiplier ?? 1)
  return `¥${fmtYuan(ein)}/1k入 · ¥${fmtYuan(eout)}/1k出`
}

export function formatPricingDetail(pricing: LlmModelPricing | null | undefined): string {
  if (!pricing) return ''
  const src = pricing.source === 'db' ? '已登记定价' : '默认价'
  const fee = pricing.service_fee_multiplier ?? 1
  const base = `售价 ¥${fmtYuan(pricing.input_price_per_1k)}/1k入 · ¥${fmtYuan(pricing.output_price_per_1k)}/1k出`
  const eff = formatPricePer1kLine(pricing)
  const min = `最低 ¥${fmtYuan(pricing.min_charge, 2)}`
  const gate = pricing.platform_billing_ok === false ? ' · 平台计费受限' : ''
  let official = ''
  if (pricing.official_input_per_1k != null) {
    official = ` · 官网 ¥${fmtYuan(pricing.official_input_per_1k)}/1k入 · ¥${fmtYuan(pricing.official_output_per_1k)}/1k出`
    if (pricing.suggested_input_per_1k != null) {
      official += `（×${fmtYuan(pricing.official_markup_multiplier ?? fee, 2)} 建议售价 ${formatPricePer1kLine({
        effective_input_per_1k: pricing.suggested_input_per_1k,
        effective_output_per_1k: pricing.suggested_output_per_1k,
      })}）`
    }
  }
  return `${src} · ${base}${official} · 结算×${fmtYuan(fee, 2)} 生效 ${eff} · ${min}${gate}`
}

export function modelOptionLabelWithPricing(row: LlmModelRow, baseLabel: string): string {
  const line = formatPricePer1kLine(row.pricing)
  if (!line) return baseLabel
  return `${baseLabel} · ${line}`
}

export function providerTileMinPriceHint(
  modelsDetailed: LlmModelRow[] | undefined,
  billingSettings?: LlmBillingSettings | null,
): string | null {
  const rows = modelsDetailed || []
  let best: number | null = null
  for (const r of rows) {
    const p = r.pricing
    if (!p) continue
    const candidates = [
      Number(p.min_charge),
      Number(p.effective_input_per_1k),
      Number(p.effective_output_per_1k),
    ].filter((x) => Number.isFinite(x) && x > 0)
    for (const c of candidates) {
      if (best === null || c < best) best = c
    }
  }
  if (best === null && billingSettings?.default_min_charge != null) {
    best = Number(billingSettings.default_min_charge)
  }
  if (best === null || !Number.isFinite(best)) return null
  return `起价 ¥${best.toFixed(2)}`
}
