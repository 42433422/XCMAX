import type { ModInfo } from '@/types/modInfo'
import { isSelectableExtensionModId } from '@/constants/genericModPack'

export function isSelectableModInfo(mod: ModInfo): boolean {
  const id = String(mod.id || '').trim()
  const type = String(mod.type || '').trim().toLowerCase()
  const artifact = String(mod.artifact || '').trim().toLowerCase()
  return Boolean(id && isSelectableExtensionModId(id) && type !== 'employee_pack' && artifact !== 'employee_pack')
}

export function pickEntitledModId(
  entitledModIds: string[], modsList: ModInfo[], primaryErpModId: string,
  entitlementMatches: (modId: string, entitledSet: Set<string>) => boolean,
  isAccountCustom: (modId: string) => boolean,
): string {
  const entitledSet = new Set(entitledModIds)
  const selectable = modsList.filter((mod) => {
    const id = String(mod.id || '').trim()
    return isSelectableModInfo(mod) && (!entitledSet.size || entitlementMatches(id, entitledSet))
  })
  const customHit = selectable.find((mod) => {
    const id = String(mod.id || '').trim()
    return isAccountCustom(id) && entitledSet.has(id)
  })
  if (customHit) return String(customHit.id || '').trim()
  if (primaryErpModId && entitlementMatches(primaryErpModId, entitledSet)) {
    const erpHit = selectable.find((mod) => String(mod.id || '').trim() === primaryErpModId)
    if (erpHit) return primaryErpModId
  }
  const primaryHit = selectable.find((mod) => mod.primary && entitlementMatches(String(mod.id || '').trim(), entitledSet))
  return String(primaryHit?.id || selectable[0]?.id || '').trim()
}
