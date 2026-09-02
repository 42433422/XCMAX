/**
 * Mod 门面探测：/api/mod/* 可用性探测与 facade 开关（拆分自 stores/mods.ts，行为保持一致）。
 * 探测结果带 TTL 缓存，避免重复请求与全局限流桶冲突。
 */
import type { ModInfo } from '@/types/modInfo'
import { apiFetch, MOD_PROBE_API_TIMEOUT_MS } from '@/utils/apiBase'
import { APPROVAL_BRIDGE_MOD_ID, setApprovalModFacadeEnabled } from '@/constants/approvalMod'
import { ERP_DOMAIN_BRIDGE_MOD_ID, setErpDomainModFacadeEnabled } from '@/constants/erpDomainMod'
import { erpDomainModStatusPath } from '@/utils/erpDomainPaths'
import { LAN_BRIDGE_MOD_ID, setLanModFacadeEnabled } from '@/constants/lanMod'
import { MODEL_PAYMENT_BRIDGE_MOD_ID, setModelPaymentModFacadeEnabled } from '@/constants/modelPaymentMod'
import { CUSTOMER_SERVICE_BRIDGE_MOD_ID, setCustomerServiceModPagesEnabled } from '@/constants/customerServiceMod'
import { PLANNER_FACADE_MOD_ID, setPlannerModFacadeEnabled } from '@/constants/plannerMod'
import { OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID, setOfficeEmployeePackModPagesEnabled } from '@/constants/officeEmployeePackMod'
import { CORE_WORKFLOW_MOD_ID, coreWorkflowModEmployeesPath, setCoreWorkflowModPagesEnabled } from '@/constants/coreWorkflowMod'
import { isClientErpSidebarContext } from '@/constants/genericModPack'
import { isProtectedClientModId } from '@/constants/protectedMods'

const MOD_PROBE_CACHE_MS = 5 * 60 * 1000
const MOD_PROBE_RATE_LIMIT_CACHE_MS = 90 * 1000

type ModProbeCacheEntry = { ok: boolean; at: number; ttlMs: number }
const modStatusProbeCache = new Map<string, ModProbeCacheEntry>()
let modFacadeProbesCompleted = false

function readModProbeCache(cacheKey: string): boolean | null {
  const row = modStatusProbeCache.get(cacheKey)
  if (!row) return null
  if (Date.now() - row.at > row.ttlMs) {
    modStatusProbeCache.delete(cacheKey)
    return null
  }
  return row.ok
}

function writeModProbeCache(cacheKey: string, ok: boolean, ttlMs = MOD_PROBE_CACHE_MS) {
  modStatusProbeCache.set(cacheKey, { ok, at: Date.now(), ttlMs })
}

/** 太阳鸟等客户 ERP：走宿主路由，勿在启动时打 /api/mod/* 探测（与全局限流桶冲突）。 */
function shouldSkipModFacadeProbes(installedModIds: string[], activeId: string | null | undefined): boolean {
  const active = String(activeId || '').trim()
  if (isProtectedClientModId(active)) return true
  return isClientErpSidebarContext(installedModIds, activeId)
}

async function probeModStatusSuccess(cacheKey: string, path: string, warnLabel: string): Promise<boolean> {
  const cached = readModProbeCache(cacheKey)
  if (cached !== null) return cached

  try {
    const response = await apiFetch(path, {
      timeoutMs: MOD_PROBE_API_TIMEOUT_MS,
    })
    if (response.status === 429) {
      writeModProbeCache(cacheKey, false, MOD_PROBE_RATE_LIMIT_CACHE_MS)
      return false
    }
    if (!response.ok) {
      console.warn(`[mods] ${warnLabel} probe failed:`, response.status, path)
      writeModProbeCache(cacheKey, false)
      return false
    }
    const body = await response.json().catch(() => null)
    const ok = Boolean(body && typeof body === 'object' && (body as { success?: boolean }).success)
    writeModProbeCache(cacheKey, ok)
    return ok
  } catch (error) {
    console.warn(`[mods] ${warnLabel} probe error:`, error)
    writeModProbeCache(cacheKey, false)
    return false
  }
}

/** 核心工作流 Mod：流程可视化物理页挂载前校验 employees 列表。 */
async function probeCoreWorkflowModAvailable(): Promise<boolean> {
  return probeModStatusSuccess('core-workflow-employees', coreWorkflowModEmployeesPath(), 'Core workflow mod listed but employees')
}

/** ERP 门面：仅在后端 Mod HTTP 路由可用时开启，避免全站请求落入 SPA 404。 */
async function probeErpDomainModFacadeAvailable(): Promise<boolean> {
  return probeModStatusSuccess('erp-domain-status', erpDomainModStatusPath(), 'ERP domain mod listed but status')
}

/** force 初始化时重置「已完成探测」标记，允许下一轮重新探测。 */
export function resetModFacadeProbes() {
  modFacadeProbesCompleted = false
}

export async function applyModFacadeFlagsFromListing(modsList: ModInfo[], activeId: string | null | undefined, forceProbe = false): Promise<void> {
  if (modFacadeProbesCompleted && !forceProbe) return

  const installedIds = modsList.map((m) => String(m.id || '').trim()).filter(Boolean)
  const active = String(activeId || '').trim()
  const skipProbes = shouldSkipModFacadeProbes(installedIds, active)

  setPlannerModFacadeEnabled(modsList.some((m) => m.id === PLANNER_FACADE_MOD_ID))

  const hasErpDomainModListed = modsList.some((m) => m.id === ERP_DOMAIN_BRIDGE_MOD_ID)
  const hasCoreWorkflowListed = modsList.some((m) => m.id === CORE_WORKFLOW_MOD_ID)

  let erpFacade = false
  let coreWorkflow = false
  if (skipProbes) {
    setErpDomainModFacadeEnabled(false)
    setCoreWorkflowModPagesEnabled(false)
  } else {
    const [erpOk, wfOk] = await Promise.all([
      hasErpDomainModListed ? probeErpDomainModFacadeAvailable() : Promise.resolve(false),
      hasCoreWorkflowListed ? probeCoreWorkflowModAvailable() : Promise.resolve(false),
    ])
    erpFacade = erpOk
    coreWorkflow = wfOk
    setErpDomainModFacadeEnabled(erpFacade)
    setCoreWorkflowModPagesEnabled(coreWorkflow)
  }

  setApprovalModFacadeEnabled(modsList.some((m) => m.id === APPROVAL_BRIDGE_MOD_ID))
  setLanModFacadeEnabled(modsList.some((m) => m.id === LAN_BRIDGE_MOD_ID))
  setModelPaymentModFacadeEnabled(modsList.some((m) => m.id === MODEL_PAYMENT_BRIDGE_MOD_ID))
  setCustomerServiceModPagesEnabled(modsList.some((m) => m.id === CUSTOMER_SERVICE_BRIDGE_MOD_ID))
  setOfficeEmployeePackModPagesEnabled(modsList.some((m) => m.id === OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID))

  modFacadeProbesCompleted = true
}
