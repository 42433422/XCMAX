import {
  isClientErpSidebarContext,
  isHostBridgeModId,
  MOD_MENU_ID_TO_HOST_NAV_KEY,
  normalizeModSidebarNavKey,
  shouldSuppressClientErpModMenuId,
} from '@/constants/genericModPack'

export type ResolvedSidebarMenuItem = {
  key: string
  name: string
  iconClass: string
  modId?: string
  path?: string
  children?: ResolvedSidebarMenuItem[]
}

function collectNavKeys(items: ResolvedSidebarMenuItem[]): Set<string> {
  const keys = new Set<string>()
  for (const item of items) {
    keys.add(String(item.key || '').trim())
    for (const child of item.children || []) {
      const ck = String(child.key || '').trim()
      if (ck) keys.add(ck)
    }
  }
  return keys
}

function hostSlotForModItem(item: ResolvedSidebarMenuItem): string {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  const mapped = MOD_MENU_ID_TO_HOST_NAV_KEY[key]
  if (mapped) return mapped
  const path = String(item.path || '').trim()
  const tail = path.split('/').filter(Boolean).pop() || ''
  if (tail && hostKeysFromPath.has(tail)) return tail
  return ''
}

function isRetiredCustomerServiceMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (
    key === 'enterprise-customer-service' ||
    key === 'internal-customer-service' ||
    key === 'mod-enterprise-customer-service' ||
    key === 'mod-internal-customer-service'
  ) return true
  const path = String(item.path || '').trim()
  const pathOnly = path.split('?')[0].split('#')[0]
  return pathOnly.includes('/enterprise-customer-service') || pathOnly.includes('/internal-customer-service')
}

function isRetiredWechatContactsMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (
    key === 'wechat-contacts' ||
    key === 'mod-erp-wechat-contacts' ||
    key === 'wechat-contacts-ai-employee-entry'
  ) return true
  const path = String(item.path || '').trim().split('?')[0].split('#')[0]
  return path === '/wechat-contacts' || path.endsWith('/wechat-contacts')
}

function isRetiredMaterialsListMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (key === 'materials-list' || key === 'mod-erp-materials-list') return true
  const path = String(item.path || '').trim().split('?')[0].split('#')[0]
  return path === '/materials-list' || path.endsWith('/materials-list')
}

/**
 * Model service lives in Settings; keep stale Mod/runtime menu rows from
 * recreating a duplicate primary-nav entry.
 * 数据对接中心（business-docking）归 ERP 侧栏，不再并入对话入口。
 */
function isConsolidatedCapabilityMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (key === 'model-payment' || key === 'mod-model-payment') return true
  const path = String(item.path || '').trim().split('?')[0].split('#')[0]
  return path === '/model-payment' || path.endsWith('/model-payment')
}

const hostKeysFromPath = new Set([
  'enterprise-customer-service',
  'internal-customer-service',
  'approval-hub',
  'workflow-visualization',
  'products',
  'customers',
  'orders',
  'shipment-records',
  'materials',
  'traditional-mode',
  'business-docking',
  'data-sources',
  'print',
  'printer-list',
  'template-preview',
  'tools',
  'other-tools',
  'workflow-visualization',
  'workflow-employee-space',
  'chat',
  'ai-ecosystem',
  'kitten-finance',
  'lan-gate',
])

/**
 * 合并宿主核心菜单 + Mod 菜单 + 尾部项，按 key 与宿主槽位去重。
 */
export function mergeSidebarMenuItems(
  coreItems: ResolvedSidebarMenuItem[],
  modItems: ResolvedSidebarMenuItem[],
  adminItems: ResolvedSidebarMenuItem[],
  trailingItems: ResolvedSidebarMenuItem[],
  installedModIds: string[],
  activeModId?: string | null,
): ResolvedSidebarMenuItem[] {
  const occupiedHostSlots = new Set<string>([
    ...collectNavKeys(coreItems),
    ...collectNavKeys(trailingItems),
  ])
  const seen = new Set<string>()
  const out: ResolvedSidebarMenuItem[] = []
  const hideHostBridgeMods = isClientErpSidebarContext(installedModIds, activeModId)

  const push = (item: ResolvedSidebarMenuItem) => {
    const key = String(item.key || '').trim()
    if (!key || seen.has(key)) return
    if (
      isRetiredCustomerServiceMenuItem(item) ||
      isRetiredWechatContactsMenuItem(item) ||
      isRetiredMaterialsListMenuItem(item) ||
      isConsolidatedCapabilityMenuItem(item)
    ) return

    const modId = String(item.modId || '').trim()
    const navKey = normalizeModSidebarNavKey(key)
    if (modId) {
      if (hideHostBridgeMods && isHostBridgeModId(modId)) return
      if (shouldSuppressClientErpModMenuId(navKey, installedModIds, activeModId)) return
    }

    if (modId) {
      const slot = hostSlotForModItem(item)
      if (slot) {
        if (occupiedHostSlots.has(slot)) return
        occupiedHostSlots.add(slot)
      }
    }

    seen.add(key)
    out.push(item)
  }

  for (const item of coreItems) push(item)
  for (const item of modItems) push(item)
  for (const item of adminItems) push(item)
  for (const item of trailingItems) push(item)

  return out
}
