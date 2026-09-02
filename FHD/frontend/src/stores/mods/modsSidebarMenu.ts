/**
 * 侧栏 Mod 菜单构建（拆分自 stores/mods.ts，行为保持一致）：
 * 菜单来源、去重优先级与 DEV 路径校验。
 */
import type { ComputedRef, Ref } from 'vue'
import type { ModInfo } from '@/types/modInfo'
import {
  CLIENT_PRIMARY_ERP_MOD_ID,
  isAuxEmployeePackModId,
  isClientErpSidebarContext,
  isHostMountedModMenuPath,
  isSelectableExtensionModId,
  shouldHideAttendanceModSidebarMenu,
  shouldSuppressClientErpModMenuId,
} from '@/constants/genericModPack'
import { buildAttendanceIndustryModStub } from '@/constants/sunbirdClientMod'
import { canonicalEntitlementId, isAccountCustomModId } from './entitlements'

export interface ModsSidebarMenuDeps {
  mods: Ref<ModInfo[]>
  modsForUi: ComputedRef<ModInfo[]>
  activeModId: Ref<string>
  findClientPrimaryErpMod: () => ModInfo | undefined
}

export function useModsSidebarMenu(deps: ModsSidebarMenuDeps) {
  const { mods, modsForUi, activeModId, findClientPrimaryErpMod } = deps

  /** 同一 manifest.menu.id 冲突时，优先保留的 Mod（靠前优先） */
  const DUPLICATE_MENU_MOD_PRIORITY: Record<string, readonly string[]> = {
    'mod-workflow-visualization': ['xcagi-workflow-visualization-bridge', 'xcagi-core-workflow-employees'],
  }

  function modPriorityForMenuEntry(menuId: string, modId: string): number {
    const order = DUPLICATE_MENU_MOD_PRIORITY[menuId]
    if (!order) return 50
    const idx = order.indexOf(modId)
    return idx >= 0 ? idx : 100
  }

  /** 侧栏 Mod 菜单来源：已选行业扩展时该包 + 同线账号定制 + AI 员工触点；不遍历全部 bridge */
  function modsContributingSidebarMenu(): ModInfo[] {
    const ui = modsForUi.value
    const full = mods.value
    const active = String(activeModId.value || '').trim()
    const activeCanonical = active ? canonicalEntitlementId(active) : ''

    /** 账号定制叠在行业包上（如太阳鸟「考勤表转换」），与行业包并存、不互斥 */
    const isOverlayCustomForActive = (id: string): boolean =>
      Boolean(activeCanonical && isAccountCustomModId(id) && canonicalEntitlementId(id) === activeCanonical)

    const pickForActive = (pool: ModInfo[]): ModInfo[] =>
      pool.filter((m) => {
        const id = String(m.id || '').trim()
        if (!id) return false
        if (id === active) return true
        if (isAuxEmployeePackModId(id)) return true
        if (isOverlayCustomForActive(id)) return true
        return false
      })

    if (active && isSelectableExtensionModId(active)) {
      // modsForUi 在已选扩展时仅含 active 一项；若先 pick(ui) 会提前返回，
      // 同线账号定制（如太阳鸟「考勤表转换」）永远进不了侧栏。
      // 原版关闭 / 管理端 SPA：ui 故意为空，不贡献。
      if (!ui.length) return []
      const fromFull = pickForActive(full)
      if (fromFull.length) return fromFull
      if (active === CLIENT_PRIMARY_ERP_MOD_ID) {
        const stub = findClientPrimaryErpMod() || buildAttendanceIndustryModStub()
        return [
          stub,
          ...full.filter((m) => {
            const id = String(m.id || '').trim()
            return isAuxEmployeePackModId(id) || isOverlayCustomForActive(id)
          }),
        ]
      }
      return []
    }
    const installedIds = mods.value.map((m) => String(m.id || '').trim()).filter(Boolean)
    if (isClientErpSidebarContext(installedIds, activeModId.value)) {
      const fromFull = full.filter((m) => isSelectableExtensionModId(String(m.id || '')))
      if (fromFull.length) return fromFull
    }
    return ui
  }

  function shouldHideModMenuEntry(menuId: string): boolean {
    if (shouldHideAttendanceModSidebarMenu(menuId)) return true
    const installedIds = mods.value.map((m) => String(m.id || '').trim()).filter(Boolean)
    return shouldSuppressClientErpModMenuId(menuId, installedIds, activeModId.value)
  }

  /**
   * 侧栏 Mod 菜单项：来自各 manifest.frontend.menu（与 routes.js 的 modMenu 保持一致）。
   * 多 Mod 时条目合并；10–20 个 Mod 时建议每包 menu 控制在合理数量并由 menu_overrides 隐藏宿主重复项。
   */
  function getModMenu() {
    const menus: Array<{
      id: string
      label: string
      icon: string
      path: string
      modId: string
    }> = []

    const byMenuId = new Map<string, { item: NonNullable<ModInfo['menu']>[number]; modId: string }>()

    for (const mod of modsContributingSidebarMenu()) {
      if (!mod.menu || !Array.isArray(mod.menu)) continue
      const modId = String(mod.id || '').trim()
      for (const item of mod.menu) {
        const menuId = String(item.id || '').trim()
        if (!menuId || shouldHideModMenuEntry(menuId)) continue
        const existing = byMenuId.get(menuId)
        if (!existing || modPriorityForMenuEntry(menuId, modId) < modPriorityForMenuEntry(menuId, existing.modId)) {
          byMenuId.set(menuId, { item, modId })
        }
      }
    }

    for (const { item, modId } of byMenuId.values()) {
      menus.push({
        ...item,
        modId,
      })
    }

    if (import.meta.env.DEV) {
      validateModMenuPaths(menus)
    }

    return menus
  }

  const warnedModMenuPathKeys = new Set<string>()

  /** DEV：manifest.menu.path 应落在 /mod/{modId}/ 下；员工包可复用宿主 pro_entry_path */
  function validateModMenuPaths(menus: Array<{ path?: string; modId?: string; label?: string }>) {
    for (const item of menus) {
      const path = String(item.path || '').trim()
      const modId = String(item.modId || '').trim()
      if (!path || !modId) continue
      const expectedPrefix = `/mod/${modId}/`
      if (path.startsWith(expectedPrefix) || path === `/mod/${modId}`) continue
      const mod = mods.value.find((m) => String(m.id || '').trim() === modId)
      const proEntry = String(mod?.frontend?.pro_entry_path || '').trim() || (modId === 'lan-gate-ai-employee' ? '/lan-gate' : '')
      if (isHostMountedModMenuPath(path, proEntry)) continue
      const warnKey = `${modId}\0${path}`
      if (warnedModMenuPathKeys.has(warnKey)) continue
      warnedModMenuPathKeys.add(warnKey)
      console.warn(`[mods] menu path "${path}" does not match mod id prefix ${expectedPrefix} (${item.label || modId})`)
    }
  }

  return {
    getModMenu,
  }
}
