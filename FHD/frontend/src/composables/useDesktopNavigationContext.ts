import { isDesktopShell } from '@/utils/desktopShell'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { i18n } from '@/i18n'
import { MOD_STORE_EMPLOYEE_OPTION, MOD_STORE_ROUTE } from '@/constants/modStoreNavigation'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useModsStore } from '@/stores/mods'
import { readSettingsNavigation } from '@/views/settings-view/settingsNavigation'
import type { DesktopNavigationItem } from '@/views/settings-view/settingsNavigation'
import { useVisibleNavItems } from './useVisibleNavItems'

export type { DesktopNavigationItem } from '@/views/settings-view/settingsNavigation'

const NAVIGATION_LIMIT = 128
const NAVIGATION_ID = /^[a-z0-9][a-z0-9._-]{0,79}$/i
const URL_TEXT = /(?:[a-z][a-z0-9+.-]*:\/\/|\bwww\.)/i

export function useDesktopNavigationContext(): () => DesktopNavigationItem[] {
  if (!isDesktopShell()) return () => []
  const account = useAccountProfileStore()
  const mods = useModsStore()
  const { visibleNavItems } = useVisibleNavItems()

  return () => {
    if (!account.workspaceReady || (!mods.clientModsUiOff &&
      (!mods.isLoaded || mods.loadedAccountEpoch !== productReadAccountEpoch.value))) return []
    const visible = visibleNavItems.value
    const names = new Map(visible.map(item => [item.key, item.name]))
    const entries: DesktopNavigationItem[] = []
    const adminConsole = isAdminConsoleSpa()
    const canOpenStore = adminConsole || !String(account.userRole || '').startsWith('tenant:')
    for (const item of visible) {
      if (!canOpenStore && item.key === MOD_STORE_ROUTE.name) continue
      const parent = item.parentKey ? names.get(item.parentKey) : undefined
      entries.push({ id: item.key, label: item.name, breadcrumb: parent ? [parent] : [], kind: 'page' })
      if (item.key === 'settings') {
        entries.push(...readSettingsNavigation(item.name, account, mods, adminConsole, key => i18n.global.t(key)))
      }
      if (item.key === 'ai-ecosystem' && canOpenStore && !adminConsole && !names.has(MOD_STORE_ROUTE.name)) {
        // The non-admin ecosystem launcher also exposes the catalog when it has no sidebar item.
        entries.push({ id: MOD_STORE_ROUTE.name, label: MOD_STORE_ROUTE.title, breadcrumb: [item.name], kind: 'page' })
      }
    }
    const storeEntry = entries.find(entry => entry.id === MOD_STORE_ROUTE.name)
    if (storeEntry) {
      entries.push({
        id: `${MOD_STORE_ROUTE.name}-${MOD_STORE_EMPLOYEE_OPTION.value}`,
        label: MOD_STORE_EMPLOYEE_OPTION.label,
        breadcrumb: [...storeEntry.breadcrumb, storeEntry.label],
        kind: 'page',
      })
    }
    const ids = new Set<string>()
    return entries.filter(({ id, label, breadcrumb }) => {
      if (ids.has(id) || !NAVIGATION_ID.test(id) ||
        [label, ...breadcrumb].some(text => typeof text !== 'string' || !text.trim() || text.length > 80 || URL_TEXT.test(text))) return false
      ids.add(id)
      return true
    }).slice(0, NAVIGATION_LIMIT)
  }
}
