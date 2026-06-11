import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useSidebarLayoutStore } from '@/stores/sidebarLayout'
import { useModsStore } from '@/stores/mods'
import { useModRoutes } from '@/composables/useModRoutes'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import {
  ADMIN_MENU_ITEM,
  ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN,
  CORE_MENU_ITEMS_BASE,
  CORE_MENU_ITEMS_TRAILING,
  SANDBOX_MENU_KEYS,
  SETTINGS_MENU_ITEM,
} from '@/constants/coreMenuCatalog'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { isPlatformShellModeEnabled, SHELL_CORE_MENU_KEYS } from '@/constants/platformShellMode'
import {
  isClientErpSidebarContext,
  keepHostNavKeyVisibleWhenModSidebarFacetSuppressed,
  normalizeModSidebarNavKey,
  shouldHideAttendanceModSidebarMenu,
} from '@/constants/genericModPack'
import { resolveNavRouteName } from '@/constants/navRouteAliases'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'
import { isCustomerServiceNavVisible } from '@/constants/customerServiceNav'
import {
  mergeSidebarMenuItems,
  type ResolvedSidebarMenuItem,
} from '@/utils/mergeSidebarMenuItems'
import { pinSidebarMenuItemsTop } from '@/utils/pinSidebarMenuItemsTop'
import { buildRoleMenuProfile, canShowCoreMenuKey } from '@/utils/roleMenuProfile'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import {
  ADMIN_OPERATOR_AUX_MENU_ITEMS,
  ADMIN_OPERATOR_MENU_ITEMS,
  ADMIN_OPERATOR_ATTENDANCE_MOD_IDS,
  ADMIN_OPERATOR_HIDDEN_MOD_IDS,
} from '@/constants/adminOperatorNav'

export type VisibleNavSource = 'core' | 'mod' | 'trailing' | 'settings' | 'child'

export type VisibleNavItem = {
  key: string
  name: string
  routeName: string
  source: VisibleNavSource
  iconClass?: string
  modId?: string
  modPath?: string
  parentKey?: string
}

export type { ResolvedSidebarMenuItem } from '@/utils/mergeSidebarMenuItems'

const isSandboxMode = () => new URLSearchParams(window.location.search).has('sandbox')
const isPlatformShellMode = () => isPlatformShellModeEnabled()

function buildCoreMenuOverrides(mods: Array<{ menu_overrides?: Array<Record<string, unknown>> }>) {
  const out = new Map<string, { label?: string; iconClass?: string; hidden?: boolean }>()
  for (const mod of mods || []) {
    const rows = Array.isArray(mod?.menu_overrides) ? mod.menu_overrides : []
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue
      const key = String(row.key || '').trim()
      if (!key) continue
      const prev = out.get(key) || {}
      const label = String(row.label || '').trim()
      const iconClass = String(row.iconClass || row.icon || '').trim()
      out.set(key, {
        ...prev,
        ...(label ? { label } : {}),
        ...(iconClass ? { iconClass } : {}),
        ...(row.hidden !== undefined ? { hidden: row.hidden === true } : {}),
      })
    }
  }
  return out
}

/** 与 Sidebar 一致的可见菜单项（含 Mod、行业文案、沙箱/壳模式过滤与排序） */
export function useVisibleNavItems() {
  const industryStore = useIndustryStore()
  const sidebarLayoutStore = useSidebarLayoutStore()
  const accountProfileStore = useAccountProfileStore()
  const modsStore = useModsStore()
  const { modsForUi, activeModId, mods } = storeToRefs(modsStore)
  const { modMenuItems } = useModRoutes()

  const installedModIds = computed(() =>
    (mods.value || []).map((m) => String(m.id || '').trim()).filter(Boolean),
  )

  const hasIndustryBusinessMod = computed(() =>
    isClientErpSidebarContext(installedModIds.value, activeModId.value),
  )

  const roleMenuProfile = computed(() =>
    buildRoleMenuProfile(
      {
        accountKind: accountProfileStore.accountKind,
        marketIsAdmin: accountProfileStore.marketIsAdmin,
        marketIsEnterprise: accountProfileStore.marketIsEnterprise,
        isAdminAccount: accountProfileStore.isAdminAccount,
      },
      hasIndustryBusinessMod.value,
    ),
  )

  const coreMenuOverrides = computed(() => buildCoreMenuOverrides(modsForUi.value || []))

  const industryId = computed(() =>
    String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID),
  )

  const isCoreNavHidden = (key: string) => {
    const override = coreMenuOverrides.value.get(key)
    if (override?.hidden !== true) return false
    return !keepHostNavKeyVisibleWhenModSidebarFacetSuppressed(
      key,
      installedModIds.value,
      activeModId.value,
    )
  }

  const localizedCoreBase = computed((): ResolvedSidebarMenuItem[] => {
    const id = industryId.value
    const adminShell = isAdminConsoleSpa() && accountProfileStore.isAdminAccount
    const adminOperatorTop: ResolvedSidebarMenuItem[] = adminShell
      ? ADMIN_OPERATOR_MENU_ITEMS.map((item) => ({
          ...item,
          name: resolveCoreNavLabel(item.key, id, modsForUi.value) || item.name,
        }))
      : []
    const baseCore = CORE_MENU_ITEMS_BASE.map((item) => {
      const override = coreMenuOverrides.value.get(item.key)
      if (isCoreNavHidden(item.key)) return null
      const childKeys = [
        ...(item.children?.map((c) => c.key) || []),
        ...(item.key === 'employee-workflow' &&
        isAdminConsoleSpa() &&
        accountProfileStore.isAdminAccount
          ? ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN.map((c) => c.key)
          : []),
      ]
      const parentAllowed =
        canShowCoreMenuKey(roleMenuProfile.value, item.key) ||
        childKeys.some((key) => canShowCoreMenuKey(roleMenuProfile.value, key))
      if (!parentAllowed) return null
      const resolved: ResolvedSidebarMenuItem = {
        ...item,
        name: resolveCoreNavLabel(item.key, id, modsForUi.value) || item.name,
        iconClass: override?.iconClass || item.iconClass,
      }
      if (item.children?.length) {
        const childSource = [
          ...item.children,
          ...(isAdminConsoleSpa() && accountProfileStore.isAdminAccount
            ? ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN
            : []),
        ]
        resolved.children = childSource
          .map((child) => {
            if (isCoreNavHidden(child.key)) return null
            if (!canShowCoreMenuKey(roleMenuProfile.value, child.key)) return null
            const childOverride = coreMenuOverrides.value.get(child.key)
            return {
              ...child,
              name: resolveCoreNavLabel(child.key, id, modsForUi.value) || child.name,
              iconClass: childOverride?.iconClass || child.iconClass,
            }
          })
          .filter(Boolean) as ResolvedSidebarMenuItem[]
        if (!resolved.children.length) return null
      }
      return resolved
    }).filter((item) => {
      if (!item) return false
      if (isSandboxMode() && !SANDBOX_MENU_KEYS.has(item.key)) return false
      if (isPlatformShellMode() && !SHELL_CORE_MENU_KEYS.has(item.key)) return false
      return true
    }) as ResolvedSidebarMenuItem[]
    return [...adminOperatorTop, ...baseCore]
  })

  const trailingLocalized = computed((): ResolvedSidebarMenuItem[] => {
    const id = industryId.value
    const adminShell = isAdminConsoleSpa() && accountProfileStore.isAdminAccount
    const trailingSource = adminShell
      ? ADMIN_OPERATOR_AUX_MENU_ITEMS
      : CORE_MENU_ITEMS_TRAILING
    return trailingSource.map((item) => ({
      ...item,
      name: resolveCoreNavLabel(item.key, id, modsForUi.value) || item.name,
    })).filter((item) => {
      if (isSandboxMode() && !SANDBOX_MENU_KEYS.has(item.key)) return false
      if (isPlatformShellMode()) return false
      if (!canShowCoreMenuKey(roleMenuProfile.value, item.key)) return false
      if (
        !isCustomerServiceNavVisible(item.key, accountProfileStore.isAdminAccount)
      ) {
        return false
      }
      return true
    })
  })

  const adminItems = computed((): ResolvedSidebarMenuItem[] => {
    if (!roleMenuProfile.value.canSeeAdminMenus) return []
    const id = industryId.value
    return [
      {
        ...ADMIN_MENU_ITEM,
        name:
          resolveCoreNavLabel(ADMIN_MENU_ITEM.key, id, modsForUi.value) ||
          ADMIN_MENU_ITEM.name,
      },
    ]
  })

  const modItemsResolved = computed((): ResolvedSidebarMenuItem[] => {
    const adminShell = isAdminConsoleSpa() && accountProfileStore.isAdminAccount
    return modMenuItems.value
      .filter((item) => {
        const navKey = normalizeModSidebarNavKey(String(item.key || ''))
        if (shouldHideAttendanceModSidebarMenu(navKey)) return false
        if (
          roleMenuProfile.value.role === 'enterprise-user' &&
          (navKey === 'workflow-visualization' || navKey === 'mod-workflow-visualization')
        ) {
          return false
        }
        if (!adminShell) return true
        const modId = String(item.modId || '').trim()
        if (modId && ADMIN_OPERATOR_HIDDEN_MOD_IDS.has(modId)) return false
        if (modId && ADMIN_OPERATOR_ATTENDANCE_MOD_IDS.has(modId)) return false
        return true
      })
      .map((item) => ({
        key: item.key,
        name: item.name,
        iconClass: item.iconClass,
        modId: item.modId,
        path: item.path,
      }))
  })

  const mergedMenuItems = computed((): ResolvedSidebarMenuItem[] =>
    mergeSidebarMenuItems(
      localizedCoreBase.value,
      modItemsResolved.value,
      adminItems.value,
      trailingLocalized.value,
      installedModIds.value,
      modsStore.activeModId,
    ),
  )

  const menuItems = computed((): ResolvedSidebarMenuItem[] => {
    const ordered = sidebarLayoutStore.applyOrder(mergedMenuItems.value)
    const active = String(activeModId.value || '').trim()
    let result = ordered
    if (!isAdminConsoleSpa() && (active === 'attendance-industry' || active === 'taiyangniao-pro')) {
      const modKeys = new Set(
        modItemsResolved.value
          .filter((m) => {
            const id = String(m.modId || '').trim()
            return id === 'attendance-industry' || id === 'taiyangniao-pro'
          })
          .map((m) => m.key),
      )
      if (modKeys.size) {
        const modOnly = ordered.filter((item) => modKeys.has(item.key))
        const rest = ordered.filter((item) => !modKeys.has(item.key))
        result = [...modOnly, ...rest]
      }
    }
    return pinSidebarMenuItemsTop(result)
  })

  const visibleNavItems = computed((): VisibleNavItem[] => {
    const out: VisibleNavItem[] = []
    for (const item of menuItems.value) {
      const source: VisibleNavSource = item.modId ? 'mod' : item.key.startsWith('enterprise-') || item.key.startsWith('internal-') ? 'trailing' : 'core'
      out.push({
        key: item.key,
        name: item.name,
        routeName: resolveNavRouteName(item.key, item.path),
        source,
        iconClass: item.iconClass,
        modId: item.modId,
        modPath: item.path,
      })
      if (item.children?.length) {
        for (const child of item.children) {
          out.push({
            key: child.key,
            name: child.name,
            routeName: resolveNavRouteName(child.key),
            source: 'child',
            iconClass: child.iconClass,
            parentKey: item.key,
          })
        }
      }
    }
    out.push({
      key: SETTINGS_MENU_ITEM.key,
      name: resolveCoreNavLabel(SETTINGS_MENU_ITEM.key, industryId.value, modsForUi.value) || SETTINGS_MENU_ITEM.name,
      routeName: SETTINGS_MENU_ITEM.key,
      source: 'settings',
      iconClass: SETTINGS_MENU_ITEM.iconClass,
    })
    return out
  })

  return {
    menuItems,
    visibleNavItems,
    coreMenuOverrides,
  }
}
