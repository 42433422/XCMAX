import {
  CORE_MENU_ITEMS_BASE,
  INDUSTRY_DELIVERY_CORE_ITEMS,
  SETTINGS_MENU_ITEM,
  type CoreMenuCatalogItem,
} from '@/constants/coreMenuCatalog'
import {
  resolvePlannerToolsExecutePath,
  resolvePlannerToolsRegistryPath,
} from '@/utils/plannerToolsPaths'

function flattenCapabilities(items: CoreMenuCatalogItem[]): Array<Record<string, string>> {
  const result: Array<Record<string, string>> = []
  for (const item of items) {
    result.push({
      route_key: item.key,
      name: item.name,
      description: item.description || `打开或操作${item.name}`,
    })
    if (item.children?.length) result.push(...flattenCapabilities(item.children))
  }
  return result
}

/**
 * Give Planner a host-owned capability map on every turn.  The model still
 * obeys account permissions and write-confirmation gates; this only removes
 * the old blind spot where it knew chat tools but not the rest of the desktop.
 */
export function buildChatSoftwareCapabilities(): Record<string, unknown> {
  const navigation = flattenCapabilities([
    ...CORE_MENU_ITEMS_BASE,
    ...INDUSTRY_DELIVERY_CORE_ITEMS,
    SETTINGS_MENU_ITEM,
  ])
  return {
    version: 1,
    current_path: typeof window === 'undefined' ? '/' : window.location.pathname,
    navigation,
    supported_actions: [
      'navigate',
      'search',
      'query',
      'create',
      'update',
      'delete',
      'import',
      'export',
      'generate_document',
      'preview_template',
      'print',
      'execute_tool',
    ],
    tool_registry_path: resolvePlannerToolsRegistryPath() || '/api/db-tools/planner_tools',
    tool_execute_path: resolvePlannerToolsExecutePath(),
    control_contract: [
      'Prefer a registered planner tool for data or document operations.',
      'Use a route_key navigation action when the user asks to open a desktop feature.',
      'Require the existing confirmation or write token before destructive operations.',
      'Report the real tool result; never claim an operation succeeded without its result.',
    ],
  }
}
