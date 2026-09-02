/**
 * Mod 权益匹配纯函数（拆分自 stores/mods.ts，行为保持一致）。
 */
import type { ModInfo } from '@/types/modInfo'
import { ACCOUNT_CUSTOM_MOD_IDS, isSelectableExtensionModId } from '@/constants/genericModPack'

export function readEntitledModIdsFromAuthPayload(raw: unknown): string[] {
  if (!raw || typeof raw !== 'object') return []
  const o = raw as Record<string, unknown>
  const data = o.data && typeof o.data === 'object' && !Array.isArray(o.data) ? (o.data as Record<string, unknown>) : undefined
  const list = o.entitled_mod_ids ?? data?.entitled_mod_ids
  return normalizeEntitledModIds(Array.isArray(list) ? (list as string[]) : undefined)
}

export function normalizeEntitledModIds(raw: string[] | undefined): string[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of raw) {
    const id = String(item || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push(id)
  }
  return out
}

const LEGACY_CLIENT_MOD_CANONICAL: Record<string, string> = {
  'taiyangniao-pro': 'attendance-industry',
  'sz-qsm-pro': 'coating-industry',
}

export function canonicalEntitlementId(modId: string): string {
  const id = String(modId || '').trim()
  return LEGACY_CLIENT_MOD_CANONICAL[id] || id
}

export function isAccountCustomModId(modId: string): boolean {
  return (ACCOUNT_CUSTOM_MOD_IDS as readonly string[]).includes(String(modId || '').trim())
}

export function entitlementMatchesMod(modId: string, entitledSet: Set<string>): boolean {
  const id = String(modId || '').trim()
  if (!id) return false
  if (entitledSet.has(id)) return true
  if (isAccountCustomModId(id)) return false
  const canonical = canonicalEntitlementId(id)
  if (canonical && entitledSet.has(canonical)) return true
  for (const entitled of entitledSet) {
    if (canonicalEntitlementId(entitled) === canonical) return true
  }
  return false
}

export function pickModIdFromEntitled(entitledModIds: string[], modsList: ModInfo[], primaryErpModId: string): string {
  const entitledSet = new Set(entitledModIds)
  const selectable = modsList.filter((m) => {
    const id = String(m.id || '').trim()
    if (!id || !isSelectableExtensionModId(id)) return false
    return entitledSet.size === 0 || entitlementMatchesMod(id, entitledSet)
  })
  if (!selectable.length) return ''

  const customHit = selectable.find((m) => {
    const id = String(m.id || '').trim()
    return isAccountCustomModId(id) && entitledSet.has(id)
  })
  if (customHit) return String(customHit.id || '').trim()

  if (primaryErpModId && entitlementMatchesMod(primaryErpModId, entitledSet)) {
    const erpHit = selectable.find((m) => String(m.id || '').trim() === primaryErpModId)
    if (erpHit) return primaryErpModId
  }

  const primaryHit = selectable.find((m) => m.primary && entitlementMatchesMod(String(m.id || '').trim(), entitledSet))
  if (primaryHit) return String(primaryHit.id || '').trim()

  return String(selectable[0].id || '').trim()
}
