import { ERP_DOMAIN_BRIDGE_MOD_ID, LEGACY_CLIENT_ERP_MOD_ID, readErpDomainModFacadeEnabled } from '@/constants/erpDomainMod'
import { CLIENT_PRIMARY_ERP_MOD_ID } from '@/constants/genericModPack'
import { isProtectedClientModId } from '@/constants/protectedMods'
import { clientModPolicies } from '@/stores/hostConfig'
import { useModsStore } from '@/stores/mods'
import { getActivePinia } from 'pinia'
import { readActiveExtensionModIdFromStorage } from '@/utils/xcagiStorageKeys'

const MOD_FACADE_BASE = `/api/mod/${ERP_DOMAIN_BRIDGE_MOD_ID}`

/**
 * 太阳鸟等客户 Mod 自管 API（见 mods/taiyangniao-pro/backend/blueprints.py）。
 * 订单/考勤记录等仍由 xcagi-erp-domain-bridge 提供；购买单位与客户同源走客户 Mod。
 */
const ERP_ON_CLIENT_MOD_PREFIXES: readonly string[] = [
  '/api/products',
  '/api/customers',
  '/api/purchase_units',
  '/api/shipment/shipment-records/units',
]

/** 选中客户 Mod 时仍走领域门面的路径（勿用 /api/shipment 整段前缀，否则会盖住 units 走客户库） */
const ERP_ON_BRIDGE_WHEN_CLIENT_ACTIVE: readonly string[] = ['/api/orders']

/**
 * 与 app.mod_sdk.erp_domain_compat.DOMAIN_SPECS 及 Mod blueprints 实际挂载路径对齐。
 */
const ERP_DOMAIN_PREFIXES = [
  '/api/shipment',
  '/api/products',
  '/api/customers',
  '/api/purchase_units',
  '/api/orders',
] as const

/** 客户 Mod（太阳鸟等）未实现的 API，继续走宿主 /api */
const HOST_ONLY_API_PREFIXES: readonly string[] = [
  '/api/shipment/shipment-records/record',
  '/api/shipment/shipment-records/export',
  '/api/materials',
  '/api/print',
  '/api/printers',
  '/api/templates',
  '/api/template',
  '/api/generate',
  '/api/db-tools',
  '/api/traditional-mode',
  '/api/business-docking',
  '/api/data-sources',
  '/api/service-bridge',
  '/api/approval',
  '/api/market',
  '/api/employees',
  '/api/ai',
  '/api/tools',
  '/api/system',
  '/api/auth',
  '/api/mods',
  '/api/mod/',
  '/api/health',
  '/api/lan',
  '/api/xcmax',
  '/api/debug',
  '/api/preferences',
  '/api/desktop',
  '/api/tts',
  '/api/intent-packages',
]

function normalizeApiPath(path: string): string {
  const raw = path.startsWith('/') ? path : `/${path}`
  const end = Math.min(raw.length, ...['?', '#'].map(separator => raw.indexOf(separator)).filter(index => index >= 0))
  return raw.slice(0, end) || raw
}

export function readActiveExtensionModId(): string {
  try {
    return readActiveExtensionModIdFromStorage()
  } catch {
    return ''
  }
}

function readInstalledModIds(explicit?: string[]): string[] {
  if (explicit?.length) return explicit.map((id) => String(id || '').trim()).filter(Boolean)
  try {
    const store = useModsStore()
    return (store.mods || []).map((m) => String(m.id || '').trim()).filter(Boolean)
  } catch {
    return []
  }
}

function pathMatchesPrefixes(pathOnly: string, prefixes: readonly string[]): boolean {
  return prefixes.some((prefix) => pathOnly === prefix || pathOnly.startsWith(`${prefix}/`))
}

function isIndustryShellModId(modId: string): boolean {
  return String(modId || '')
    .trim()
    .endsWith('-industry')
}

/** 该 mod 是否为可路由的客户 ERP mod（受保护客户 mod，且非行业壳 mod） */
function isRoutableClientErpModId(modId: string): boolean {
  const id = String(modId || '').trim()
  return isProtectedClientModId(id) && !isIndustryShellModId(id)
}

function resolveErpBaseForClientMod(activeClient: string, ids: string[]): string {
  if (isIndustryShellModId(activeClient)) {
    return ids.includes(ERP_DOMAIN_BRIDGE_MOD_ID) ? MOD_FACADE_BASE : '/api'
  }
  if (ids.includes(activeClient)) {
    return `/api/mod/${activeClient}`
  }
  if (ids.includes(ERP_DOMAIN_BRIDGE_MOD_ID)) {
    return MOD_FACADE_BASE
  }
  return `/api/mod/${activeClient}`
}

function isHostOnlyApiPath(pathOnly: string): boolean {
  if (!pathOnly.startsWith('/api/')) return true
  return HOST_ONLY_API_PREFIXES.some((prefix) => pathOnly === prefix || pathOnly.startsWith(`${prefix}/`))
}

/**
 * ERP 领域 API 根路径（不含尾部路径段）。
 * 优先级：当前选中的客户 Mod > 通用领域门面 Mod > 宿主 /api
 */
export function resolveErpApiBase(installedModIds?: string[]): string {
  const ids = readInstalledModIds(installedModIds)
  const activeClient = readActiveExtensionModId()
  if (activeClient && isRoutableClientErpModId(activeClient)) {
    return resolveErpBaseForClientMod(activeClient, ids)
  }
  const primary = String(clientModPolicies.value?.client_primary_erp_mod_id || CLIENT_PRIMARY_ERP_MOD_ID).trim()
  if (!activeClient && primary && isRoutableClientErpModId(primary) && ids.includes(primary)) {
    return resolveErpBaseForClientMod(primary, ids)
  }
  if (readErpDomainModFacadeEnabled()) {
    return MOD_FACADE_BASE
  }
  if (ids.includes(LEGACY_CLIENT_ERP_MOD_ID)) {
    return `/api/mod/${LEGACY_CLIENT_ERP_MOD_ID}`
  }
  if (ids.includes(ERP_DOMAIN_BRIDGE_MOD_ID)) {
    return MOD_FACADE_BASE
  }
  return '/api'
}

export function resolveErpApiPath(hostPath: string, installedModIds?: string[]): string {
  const raw = hostPath.startsWith('/') ? hostPath : `/${hostPath}`
  const pathOnly = normalizeApiPath(raw)
  const suffix = raw.slice(pathOnly.length)
  const ids = readInstalledModIds(installedModIds)

  if (isHostOnlyApiPath(pathOnly)) {
    return raw
  }

  const activeClient = readActiveExtensionModId()
  if (activeClient && isRoutableClientErpModId(activeClient)) {
    let erpBase = resolveErpBaseForClientMod(activeClient, ids)
    if (pathMatchesPrefixes(pathOnly, ERP_ON_BRIDGE_WHEN_CLIENT_ACTIVE)) {
      erpBase = ids.includes(ERP_DOMAIN_BRIDGE_MOD_ID) ? MOD_FACADE_BASE : '/api'
    } else if (!pathMatchesPrefixes(pathOnly, ERP_ON_CLIENT_MOD_PREFIXES)) {
      erpBase = ids.includes(ERP_DOMAIN_BRIDGE_MOD_ID) ? MOD_FACADE_BASE : erpBase
    }
    return erpBase === '/api' ? raw : `${erpBase}${pathOnly.slice(4)}${suffix}`
  }

  const erpBase = resolveErpApiBase(ids)
  return erpBase === '/api' ? raw : `${erpBase}${pathOnly.slice(4)}${suffix}`
}

export function useErpDomainModFacade(): boolean {
  return readErpDomainModFacadeEnabled()
}

export async function resolveErpApiPathWhenReady(path: string): Promise<string> {
  const only = normalizeApiPath(path)
  if (!getActivePinia() || isHostOnlyApiPath(only) || !pathMatchesPrefixes(only, ERP_DOMAIN_PREFIXES)) return path
  const store = useModsStore()
  if (!store.clientModsUiOff && !store.isLoaded && !store.mods.length) await store.fetchMods()
  return resolveErpApiPath(path)
}

export function erpDomainModStatusPath(): string {
  return `${MOD_FACADE_BASE}/status`
}
