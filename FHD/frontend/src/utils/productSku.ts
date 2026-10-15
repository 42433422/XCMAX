import { apiFetch } from '@/utils/apiBase'

let cachedSku: string | null = null
let skuFetchPromise: Promise<string> | null = null
const PRODUCT_SKU_RETRY_DELAYS_MS = [200, 400] as const

function viteDevSkuOverride(): string | null {
  if (!import.meta.env.DEV) return null
  const raw = import.meta.env.VITE_XCAGI_PRODUCT_SKU
  if (typeof raw !== 'string') return null
  const sku = raw.trim().toLowerCase()
  return sku || null
}

export async function fetchProductSku(force = false): Promise<string> {
  const viteSku = viteDevSkuOverride()
  if (!force && viteSku) {
    cachedSku = viteSku
    return viteSku
  }
  if (!force && cachedSku) return cachedSku
  if (!force && skuFetchPromise) return skuFetchPromise
  skuFetchPromise = (async () => {
    for (let attempt = 0; attempt <= PRODUCT_SKU_RETRY_DELAYS_MS.length; attempt += 1) {
      try {
        const res = await apiFetch('/api/runtime/product-sku', { timeoutMs: 8_000 })
        if (res.ok) {
          const body = await res.json()
          const sku = String(body?.data?.sku || body?.sku || 'generic').trim() || 'generic'
          cachedSku = viteSku || sku
          return cachedSku
        }
        if (![404, 502, 503, 504].includes(res.status) || attempt === PRODUCT_SKU_RETRY_DELAYS_MS.length) {
          break
        }
      } catch {
        break
      }
      if (attempt < PRODUCT_SKU_RETRY_DELAYS_MS.length) {
        await new Promise(resolve => setTimeout(resolve, PRODUCT_SKU_RETRY_DELAYS_MS[attempt]))
      }
    }
    // A temporary startup failure must not make the fallback SKU sticky for the
    // lifetime of the renderer. A later route mount can then resolve the real SKU.
    return viteSku || cachedSku || 'generic'
  })()
  try {
    return await skuFetchPromise
  } finally {
    skuFetchPromise = null
  }
}

export function isEnterpriseEdition(sku?: string | null): boolean {
  const s = (sku ?? cachedSku ?? '').trim()
  return s === 'enterprise'
}
