import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import type { WorkflowEmployeeRegistryEntry } from '@/types/workflow-employee'
import { filterWorkflowRegistrySourceMods, isNonWorkflowDeskEmployeeId } from '@/utils/modWorkflowEmployees'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import {
  loadWorkflowEmployeeRegistry,
  mergeModManifestEntries,
  resolveLabel,
  invalidateWorkflowEmployeeRegistryCache,
} from '@/utils/workflowEmployeeRegistry'

function collectManifestWorkflowEmployeeIds(mods: ModWithWorkflowEmployees[] | undefined): Set<string> {
  const ids = new Set<string>()
  for (const m of filterWorkflowRegistrySourceMods(mods)) {
    const allowNonDesk = m.directory_sourced === true
    for (const e of m.workflow_employees || []) {
      const id = String(e?.id || '').trim()
      if (id && (allowNonDesk || !isNonWorkflowDeskEmployeeId(id))) ids.add(id)
    }
  }
  return ids
}

import { buildTenantScopedStorageKey, resolveTenantStorageScopeFromRuntime } from '@/utils/tenantStorageScope'

export const WORKFLOW_AI_EMPLOYEES_STORAGE_KEY = 'xcagi_workflow_ai_employees'

let activeTenantScope = ''

function ensureActiveTenantScope(): string {
  if (!activeTenantScope) {
    activeTenantScope = resolveTenantStorageScopeFromRuntime(true)
  }
  return activeTenantScope
}

export function workflowAiEmployeesStorageKey(scope?: string): string {
  return buildTenantScopedStorageKey(WORKFLOW_AI_EMPLOYEES_STORAGE_KEY, scope ?? ensureActiveTenantScope())
}

export function defaultWorkflowBuiltinEnabled(): Record<string, boolean> {
  return {}
}

export function coreWorkflowEmployeeIdSet(): Set<string> {
  return new Set()
}

function readWorkflowEnabledFromLocalStorage(scope?: string): Record<string, boolean> {
  const base = defaultWorkflowBuiltinEnabled()
  try {
    const raw = localStorage.getItem(workflowAiEmployeesStorageKey(scope))
    if (!raw) return base
    const p = JSON.parse(raw) as Record<string, unknown>
    if (!p || typeof p !== 'object') return base
    for (const k of Object.keys(base)) {
      if (typeof p[k] === 'boolean') base[k] = p[k]
    }
    for (const k of Object.keys(p)) {
      if (!(k in base) && typeof p[k] === 'boolean') base[k] = p[k] as boolean
    }
    return base
  } catch {
    return base
  }
}

function mergeModWorkflowIds(cur: Record<string, boolean>, mods: ModWithWorkflowEmployees[] | undefined): Record<string, boolean> {
  const next = { ...cur }
  for (const m of filterWorkflowRegistrySourceMods(mods)) {
    for (const e of m.workflow_employees || []) {
      const id = String(e?.id || '').trim()
      if (!id || isNonWorkflowDeskEmployeeId(id) || id in next) continue
      next[id] = false
    }
  }
  return next
}

export const useWorkflowAiEmployeesStore = defineStore('workflowAiEmployees', () => {
  const localEnabled = ref(defaultWorkflowBuiltinEnabled())
  const serverEnabled = ref<Record<string, boolean> | null>(null)
  const enabled = computed({
    get: () => serverEnabled.value ?? localEnabled.value,
    set: (values: Record<string, boolean>) => {
      if (serverEnabled.value === null) localEnabled.value = values
      else serverEnabled.value = values
    },
  })
  const registryEntries = ref<WorkflowEmployeeRegistryEntry[]>([])
  const registryLoaded = ref(false)
  let registryLoadGeneration = 0
  let registryOwner = ''
  const confirmedEnabled = ref<Record<string, boolean>>({})
  const prefsReady = ref(false)
  const prefsSaving = ref('')
  const prefsError = ref('')
  let prefsVersion = 0

  const registeredIds = computed(() => new Set(registryEntries.value.map((e) => e.id)))

  function persistAndNotify(sync = true) {
    if (serverEnabled.value === null) {
      try {
        localStorage.setItem(workflowAiEmployeesStorageKey(), JSON.stringify(localEnabled.value))
      } catch {
        /* quota / private mode */
      }
    }
    const snapshot = { ...enabled.value }
    if (sync) {
      const scope = prefsScope()
      void import('@/utils/workspacePrefsApi')
        .then(({ queueWorkspacePrefsSync }) => {
          if (scope === prefsScope()) queueWorkspacePrefsSync({ workflow_ai_employees: snapshot })
        })
        .catch(() => {})
    }
    window.dispatchEvent(
      new CustomEvent('xcagi:workflow-ai-employees-changed', {
        detail: { enabled: snapshot },
      }),
    )
  }

  function prefsScope() { return `${productReadScopeKey('')}:${ensureActiveTenantScope()}` }

  function acceptConfirmedPreferences(values: Record<string, boolean>) {
    confirmedEnabled.value = { ...values }
    serverEnabled.value = { ...Object.fromEntries(registryEntries.value.map(entry => [entry.id, false])), ...values }
    prefsReady.value = true
    prefsError.value = ''
    persistAndNotify(false)
  }

  async function refreshConfirmedPreferences() {
    if (prefsSaving.value) return
    const version = ++prefsVersion
    const scope = prefsScope()
    const tenantScope = ensureActiveTenantScope()
    try {
      const { fetchWorkspacePrefs, flushWorkspacePrefsSync, confirmWorkspacePrefsSnapshot } = await import('@/utils/workspacePrefsApi')
      await flushWorkspacePrefsSync()
      if (version !== prefsVersion || scope !== prefsScope()) return
      const response = await fetchWorkspacePrefs()
      if (version !== prefsVersion || scope !== prefsScope()) return
      if (response.success !== true || !response.owner_id) throw new Error('无法确认工作区归属')
      confirmWorkspacePrefsSnapshot(response, tenantScope)
      acceptConfirmedPreferences(response.data?.workflow_ai_employees || {})
    } catch (reason) {
      if (version !== prefsVersion || scope !== prefsScope()) return
      prefsReady.value = false
      prefsError.value = reason instanceof Error ? reason.message : '托管状态暂未核实'
    }
  }

  async function setEmployeeEnabledConfirmed(id: string, value: boolean) {
    if (!prefsReady.value || prefsSaving.value || !registeredIds.value.has(id)) return
    const scope = prefsScope()
    const version = ++prefsVersion
    prefsSaving.value = id
    prefsError.value = ''
    try {
      const { patchWorkspacePrefs, flushWorkspacePrefsSync } = await import('@/utils/workspacePrefsApi')
      await flushWorkspacePrefsSync()
      if (version !== prefsVersion || scope !== prefsScope()) return
      const response = await patchWorkspacePrefs({ workflow_ai_employees: { [id]: value } })
      if (version !== prefsVersion || scope !== prefsScope()) return
      const values = response.data?.workflow_ai_employees
      if (response.success !== true || !response.owner_id || !values || values[id] !== value) throw new Error('服务器未确认托管状态，请重新同步')
      acceptConfirmedPreferences(values)
    } catch (reason) {
      if (version !== prefsVersion || scope !== prefsScope()) return
      prefsReady.value = false
      prefsError.value = reason instanceof Error ? reason.message : '托管操作未确认，请重新同步'
    } finally {
      if (version === prefsVersion && scope === prefsScope()) prefsSaving.value = ''
    }
  }

  async function loadRegistry(mods?: ModWithWorkflowEmployees[], isCurrent: () => boolean = () => true) {
    const generation = ++registryLoadGeneration
    try {
      const registry = await loadWorkflowEmployeeRegistry()
      if (generation !== registryLoadGeneration || !isCurrent()) return
      const merged = mods ? mergeModManifestEntries(registry, mods) : registry.employees
      registryEntries.value = merged
      registryLoaded.value = true
      ensureEnabledKeys()
    } catch (e) {
      console.warn('[workflowAiEmployees] loadRegistry failed:', e)
    }
  }

  function registerEmployee(entry: WorkflowEmployeeRegistryEntry) {
    const idx = registryEntries.value.findIndex((e) => e.id === entry.id)
    if (idx >= 0) {
      registryEntries.value[idx] = entry
    } else {
      registryEntries.value.push(entry)
      registryEntries.value.sort((a, b) => a.order - b.order)
    }
    if (!(entry.id in enabled.value)) {
      enabled.value = { ...enabled.value, [entry.id]: false }
      persistAndNotify(false)
    }
  }

  function unregisterEmployee(id: string) {
    const idx = registryEntries.value.findIndex((e) => e.id === id)
    if (idx >= 0) {
      registryEntries.value.splice(idx, 1)
    }
    const next = { ...enabled.value }
    delete next[id]
    if (JSON.stringify(next) !== JSON.stringify(enabled.value)) {
      enabled.value = next
      persistAndNotify(false)
    }
  }

  function ensureEnabledKeys() {
    const next = { ...enabled.value }
    let changed = false
    for (const entry of registryEntries.value) {
      if (!(entry.id in next)) {
        next[entry.id] = false
        changed = true
      }
    }
    if (changed) {
      enabled.value = next
      persistAndNotify(false)
    }
  }

  function hydrateFromMods(mods: ModWithWorkflowEmployees[] | undefined) {
    const merged = mergeModWorkflowIds({ ...enabled.value }, mods)
    if (JSON.stringify(merged) !== JSON.stringify(enabled.value)) {
      enabled.value = merged
    }
  }

  function stripModWorkflowEmployeeKeys() {
    const registryIds = registeredIds.value
    const next: Record<string, boolean> = {}
    for (const k of Object.keys(enabled.value)) {
      if (registryIds.has(k)) next[k] = enabled.value[k]
    }
    if (JSON.stringify(next) !== JSON.stringify(enabled.value)) {
      enabled.value = next
      // Registry reconciliation is a local projection, not a user setting change.
      // Writing it back races with the enterprise model's revisioned save.
      persistAndNotify(false)
    }
  }

  function pruneOrphanWorkflowEmployeeToggles(mods: ModWithWorkflowEmployees[] | undefined) {
    const manifestIds = collectManifestWorkflowEmployeeIds(mods)
    const registryIds = registeredIds.value
    const next: Record<string, boolean> = { ...enabled.value }
    for (const k of Object.keys(next)) {
      if (registryIds.has(k)) continue
      if (!manifestIds.has(k)) delete next[k]
    }
    if (JSON.stringify(next) !== JSON.stringify(enabled.value)) {
      enabled.value = next
      persistAndNotify(false)
    }
  }

  function reloadFromLocalStorage() {
    if (serverEnabled.value === null) localEnabled.value = readWorkflowEnabledFromLocalStorage()
  }

  function reloadForTenantScope(scope?: string) {
    activeTenantScope = scope || resolveTenantStorageScopeFromRuntime(true)
    const owner = `${productReadScopeKey('')}:${activeTenantScope}`
    if (owner !== registryOwner) {
      registryOwner = owner
      prefsVersion++
      confirmedEnabled.value = {}
      serverEnabled.value = null
      prefsReady.value = false
      prefsSaving.value = ''
      prefsError.value = ''
      registryLoadGeneration++
      registryEntries.value = []
      registryLoaded.value = false
    }
    reloadFromLocalStorage()
  }

  reloadForTenantScope(resolveTenantStorageScopeFromRuntime(true))

  function setAll(next: Record<string, boolean>) {
    enabled.value = { ...next }
    persistAndNotify()
  }

  function toggle(id: string) {
    if (!(id in enabled.value)) {
      enabled.value = { ...enabled.value, [id]: true }
    } else {
      enabled.value = { ...enabled.value, [id]: !enabled.value[id] }
    }
    persistAndNotify()
  }

  function enableAllOn() {
    const next = { ...enabled.value }
    for (const k of Object.keys(next)) next[k] = true
    setAll(next)
  }

  /**
   * 上岗：将指定员工设为已托管（AI 市场安装员工包后自动调用）。
   * @returns 实际从 false→true 的员工 id
   */
  function assignHostMod(employeeIds: string[], hostModId: string) {
    const hid = String(hostModId || '').trim()
    if (!hid) return
    let changed = false
    const next = registryEntries.value.map((entry) => {
      if (!employeeIds.includes(entry.id)) return entry
      if (entry.hostModId === hid) return entry
      changed = true
      return { ...entry, hostModId: hid }
    })
    if (changed) registryEntries.value = next
  }

  function enableEmployees(ids: string[], options?: { onlyNew?: boolean }) {
    const onlyNew = Boolean(options?.onlyNew)
    const next = { ...enabled.value }
    const turnedOn: string[] = []
    for (const raw of ids) {
      const id = String(raw || '').trim()
      if (!id || isNonWorkflowDeskEmployeeId(id)) continue
      if (onlyNew && next[id] === true) continue
      if (!next[id]) {
        turnedOn.push(id)
      }
      next[id] = true
    }
    if (JSON.stringify(next) !== JSON.stringify(enabled.value)) {
      enabled.value = next
      persistAndNotify()
    }
    return turnedOn
  }

  function getEmployeeLabel(id: string, i18nResolver?: (key: string) => string): string {
    const entry = registryEntries.value.find((e) => e.id === id)
    if (entry) return resolveLabel(entry, i18nResolver)
    return id
  }

  async function refreshRegistry(mods?: ModWithWorkflowEmployees[]) {
    invalidateWorkflowEmployeeRegistryCache()
    registryLoaded.value = false
    await loadRegistry(mods)
  }

  return {
    enabled,
    registryEntries,
    registryLoaded,
    registeredIds,
    confirmedEnabled,
    prefsReady,
    prefsSaving,
    prefsError,
    acceptConfirmedPreferences,
    refreshConfirmedPreferences,
    setEmployeeEnabledConfirmed,
    loadRegistry,
    registerEmployee,
    unregisterEmployee,
    ensureEnabledKeys,
    hydrateFromMods,
    stripModWorkflowEmployeeKeys,
    pruneOrphanWorkflowEmployeeToggles,
    reloadFromLocalStorage,
    reloadForTenantScope,
    setAll,
    toggle,
    enableAllOn,
    enableEmployees,
    assignHostMod,
    persistAndNotify,
    getEmployeeLabel,
    refreshRegistry,
  }
})
