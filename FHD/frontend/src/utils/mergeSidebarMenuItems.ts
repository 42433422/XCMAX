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

/**
 * Shallow memo 缓存：每次路由切换时 store ref 引用通常不变，
 * 直接复用上次计算结果，避免全量遍历 + 正则匹配。
 * 命中条件：6 个参数引用完全一致（===），对应 Vue 响应式 store
 * 未触发更新时的常见场景（单纯 route.path 变化不影响菜单内容）。
 */
type _MergeArgs = [
  ResolvedSidebarMenuItem[],
  ResolvedSidebarMenuItem[],
  ResolvedSidebarMenuItem[],
  ResolvedSidebarMenuItem[],
  string[],
  string | null | undefined,
]
let _lastCache: { args: _MergeArgs; result: ResolvedSidebarMenuItem[] } | null = null

function _cacheHit(args: _MergeArgs): boolean {
  if (!_lastCache) return false
  const prev = _lastCache.args
  for (let i = 0; i < 6; i++) {
    if (prev[i] !== args[i]) return false
  }
  return true
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

function isRetiredMaterialsListMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (key === 'materials-list' || key === 'mod-erp-materials-list') return true
  const path = String(item.path || '').trim().split('?')[0].split('#')[0]
  return path === '/materials-list' || path.endsWith('/materials-list')
}

/**
 * Model service stays in Settings. Mod 里的旧「业务对接」页已退役，勿再进侧栏；
 * 宿主「数据对接中心」(key=business-docking → EtlCenter) 仍由 core/industry 槽位展示。
 */
function isConsolidatedCapabilityMenuItem(item: ResolvedSidebarMenuItem): boolean {
  const key = normalizeModSidebarNavKey(String(item.key || '').trim())
  if (
    key === 'model-payment' ||
    key === 'mod-model-payment' ||
    key === 'mod-erp-business-docking'
  ) {
    return true
  }
  const path = String(item.path || '').trim().split('?')[0].split('#')[0]
  return (
    path === '/model-payment' ||
    path.endsWith('/model-payment') ||
    path === '/mod/xcagi-erp-domain-bridge/business-docking' ||
    path.endsWith('/mod/xcagi-erp-domain-bridge/business-docking')
  )
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
 *
 * Performance：模块级 shallow memo。路由频繁切换但 store 引用未变时
 * 直接命中（~O(1) 引用比较），避免 4 × N 次 push + 正则/字符串扫描。
 */
export function mergeSidebarMenuItems(
  coreItems: ResolvedSidebarMenuItem[],
  modItems: ResolvedSidebarMenuItem[],
  adminItems: ResolvedSidebarMenuItem[],
  trailingItems: ResolvedSidebarMenuItem[],
  installedModIds: string[],
  activeModId?: string | null,
): ResolvedSidebarMenuItem[] {
  const args: _MergeArgs = [coreItems, modItems, adminItems, trailingItems, installedModIds, activeModId]
  if (_cacheHit(args)) {
    return _lastCache!.result
  }

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

  _lastCache = { args, result: out }
  return out
}
