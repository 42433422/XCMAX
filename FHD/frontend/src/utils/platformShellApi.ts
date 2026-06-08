import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'
import type {
  DeliverableStatus,
  IndustryBaselinePlan,
  OnboardingIndustryCatalog,
  PlatformShellCapabilities,
} from '@/constants/platformShell'

let cached: PlatformShellCapabilities | null = null
let deliverableCached: DeliverableStatus | null = null
const baselineCache = new Map<string, IndustryBaselinePlan>()
let onboardingCatalogCached: OnboardingIndustryCatalog | null = null

export async function fetchPlatformShellCapabilities(
  force = false,
): Promise<PlatformShellCapabilities> {
  if (cached && !force) return cached
  const r = await apiFetch('/api/platform-shell/capabilities', {
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`platform-shell/capabilities HTTP ${r.status}`)
  const body = await r.json()
  const data = (body?.data || body) as PlatformShellCapabilities
  cached = data
  return data
}

export function isBridgeModInstalled(
  caps: PlatformShellCapabilities,
  modId: string,
): boolean {
  const row = (caps.bridge_mods || []).find((b) => b.mod_id === modId)
  return Boolean(row?.installed)
}

export async function fetchDeliverableStatus(force = false): Promise<DeliverableStatus> {
  if (deliverableCached && !force) return deliverableCached
  const r = await apiFetch('/api/platform-shell/deliverable-status', {
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`deliverable-status HTTP ${r.status}`)
  const body = await r.json()
  const data = (body?.data || body) as DeliverableStatus
  deliverableCached = data
  return data
}

export function clearDeliverableStatusCache(): void {
  deliverableCached = null
  cached = null
  baselineCache.clear()
  onboardingCatalogCached = null
}

export async function fetchOnboardingIndustryCatalog(
  force = false,
): Promise<OnboardingIndustryCatalog> {
  if (!force && onboardingCatalogCached) return onboardingCatalogCached
  const r = await apiFetch('/api/platform-shell/onboarding-industries', {
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`onboarding-industries HTTP ${r.status}`)
  const body = await r.json()
  const data = (body?.data || body) as OnboardingIndustryCatalog
  onboardingCatalogCached = data
  return data
}

export async function fetchIndustryBaseline(
  industryId: string,
  force = false,
): Promise<IndustryBaselinePlan> {
  const key = String(industryId || '').trim() || '通用'
  if (!force && baselineCache.has(key)) {
    return baselineCache.get(key) as IndustryBaselinePlan
  }
  const r = await apiFetch(
    `/api/platform-shell/industry-baseline?industry_id=${encodeURIComponent(key)}`,
    { timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS },
  )
  if (!r.ok) throw new Error(`industry-baseline HTTP ${r.status}`)
  const body = await r.json()
  const data = (body?.data || body) as IndustryBaselinePlan
  baselineCache.set(key, data)
  return data
}
