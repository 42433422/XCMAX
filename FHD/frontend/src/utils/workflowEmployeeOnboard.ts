/**
 * AI 市场安装员工包后自动上岗，并挂靠当前企业 Mod 栈（行业通用 + 定制）。
 */
import { reloadEmployeePacks } from '@/api/modStore'
import {
  defaultHostModIdForMarketEmployee,
  type EnterpriseModStack,
} from '@/constants/enterpriseModStack'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { filterModsForEnterpriseWorkflowRegistry } from '@/utils/workflowEmployeeScope'
import {
  filterWorkflowRegistrySourceMods,
  isNonWorkflowDeskEmployeeId,
  type ModWithWorkflowEmployees,
  type WorkflowEmployeeManifestEntry,
} from '@/utils/modWorkflowEmployees'

export type MarketInstallCatalogItem = {
  id?: string
  pkg_id?: string
  name?: string
  artifact?: string
  employee?: { id?: string; label?: string }
  workflow_employees?: WorkflowEmployeeManifestEntry[]
  host_mod_id?: string
  enterprise_mod_id?: string
}

function isEmployeePackArtifact(item: MarketInstallCatalogItem | undefined): boolean {
  return String(item?.artifact || '').trim().toLowerCase() === 'employee_pack'
}

function collectDeskWorkflowEmployeeIds(
  workflowEmployees: WorkflowEmployeeManifestEntry[] | undefined,
): string[] {
  const ids: string[] = []
  for (const e of workflowEmployees || []) {
    const id = String(e?.id || '').trim()
    if (!id || isNonWorkflowDeskEmployeeId(id)) continue
    ids.push(id)
  }
  return ids
}

export function collectDeskEmployeeIdsFromCatalogItem(
  item: MarketInstallCatalogItem | undefined,
): string[] {
  if (!item) return []
  const ids = collectDeskWorkflowEmployeeIds(item.workflow_employees)
  if (ids.length) return ids
  const empId = String(item.employee?.id || '').trim()
  if (empId && !isNonWorkflowDeskEmployeeId(empId)) return [empId]
  return []
}

function collectEmployeeIdsFromMod(mod: ModWithWorkflowEmployees | undefined): string[] {
  if (!mod) return []
  return collectDeskWorkflowEmployeeIds(mod.workflow_employees)
}

function resolveInstalledMod(
  mods: ModWithWorkflowEmployees[],
  item: MarketInstallCatalogItem,
): ModWithWorkflowEmployees | undefined {
  const pid = String(item.pkg_id || item.id || '').trim()
  if (!pid) return undefined
  return (
    mods.find((m) => String(m.id || '').trim() === pid) ||
    mods.find((m) => String((m as { pkg_id?: string }).pkg_id || '').trim() === pid)
  )
}

export type AutoOnboardMarketInstallResult = {
  plannerRefreshed: boolean
  onboardedIds: string[]
  enterpriseStackLabel: string
  hostModId: string
}

/**
 * 市场安装成功后：员工挂靠企业 Mod 栈并上岗（Planner + 副窗托管）。
 */
export async function autoOnboardInstalledMarketItem(
  item: MarketInstallCatalogItem,
): Promise<AutoOnboardMarketInstallResult> {
  let stack = await resolveEnterpriseModStack()
  const hostModId = defaultHostModIdForMarketEmployee(stack, item)

  const isEmployeePack = isEmployeePackArtifact(item)
  let plannerRefreshed = false
  if (isEmployeePack) {
    try {
      await reloadEmployeePacks()
      plannerRefreshed = true
    } catch (e) {
      console.warn('[workflowEmployeeOnboard] reloadEmployeePacks failed:', e)
    }
  }

  const modsStore = useModsStore()
  await modsStore.refresh()
  const wfStore = useWorkflowAiEmployeesStore()
  stack = await resolveEnterpriseModStack()
  await wfStore.refreshRegistry(filterModsForEnterpriseWorkflowRegistry(modsStore.modsForUi, stack))

  const mod = resolveInstalledMod(modsStore.modsForUi, item)
  const idSet = new Set<string>([
    ...collectDeskEmployeeIdsFromCatalogItem(item),
    ...collectEmployeeIdsFromMod(mod),
  ])
  const ids = [...idSet]

  if (ids.length) {
    wfStore.assignHostMod(ids, hostModId)
  }

  const onboardedIds = ids.length ? wfStore.enableEmployees(ids, { onlyNew: false }) : []

  return {
    plannerRefreshed,
    onboardedIds,
    enterpriseStackLabel: stack.stackLabel,
    hostModId,
  }
}

/** @deprecated 使用 autoOnboardInstalledMarketItem */
export async function autoOnboardWorkflowEmployeesForMod(
  modId: string,
): Promise<string[]> {
  const result = await autoOnboardInstalledMarketItem({ id: modId, pkg_id: modId })
  return result.onboardedIds
}

export async function autoOnboardWorkflowEmployeesFromMods(
  mods: ModWithWorkflowEmployees[] | undefined,
): Promise<string[]> {
  const modsStore = useModsStore()
  await modsStore.refresh()
  const wfStore = useWorkflowAiEmployeesStore()
  const stack = await resolveEnterpriseModStack()
  await wfStore.refreshRegistry(filterModsForEnterpriseWorkflowRegistry(modsStore.modsForUi, stack))
  const ids: string[] = []
  for (const m of filterWorkflowRegistrySourceMods(mods)) {
    for (const id of collectEmployeeIdsFromMod(m)) ids.push(id)
  }
  if (!ids.length) return []
  return wfStore.enableEmployees(ids, { onlyNew: false })
}
