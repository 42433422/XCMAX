import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import { aminDefaultEnabledMap, aminPluginIds } from '@/utils/aminRegistry'

function collectManifestWorkflowEmployeeIds(mods: ModWithWorkflowEmployees[] | undefined): Set<string> {
  const ids = new Set<string>()
  for (const m of mods || []) {
    for (const e of m.workflow_employees || []) {
      const id = String(e?.id || '').trim()
      if (id) ids.add(id)
    }
  }
  return ids
}

export const WORKFLOW_AI_EMPLOYEES_STORAGE_KEY = 'xcagi_workflow_ai_employees'

export function defaultWorkflowBuiltinEnabled(): Record<string, boolean> {
  return aminDefaultEnabledMap()
}

function readWorkflowEnabledFromLocalStorage(): Record<string, boolean> {
  const base = defaultWorkflowBuiltinEnabled()
  try {
    const raw = localStorage.getItem(WORKFLOW_AI_EMPLOYEES_STORAGE_KEY)
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

function mergeModWorkflowIds(
  cur: Record<string, boolean>,
  mods: ModWithWorkflowEmployees[] | undefined
): Record<string, boolean> {
  const builtin = new Set(aminPluginIds())
  const next = { ...cur }
  for (const m of mods || []) {
    for (const e of m.workflow_employees || []) {
      const id = String(e?.id || '').trim()
      if (id && !builtin.has(id) && !(id in next)) next[id] = false
    }
  }
  return next
}

export const useWorkflowAiEmployeesStore = defineStore('workflowAiEmployees', () => {
  const enabled = ref<Record<string, boolean>>(readWorkflowEnabledFromLocalStorage())

  function persistAndNotify() {
    try {
      localStorage.setItem(WORKFLOW_AI_EMPLOYEES_STORAGE_KEY, JSON.stringify(enabled.value))
    } catch {
      /* quota / private mode */
    }
    window.dispatchEvent(
      new CustomEvent('xcagi:workflow-ai-employees-changed', {
        detail: { enabled: { ...enabled.value } },
      })
    )
  }

  function hydrateFromMods(mods: ModWithWorkflowEmployees[] | undefined) {
    const merged = mergeModWorkflowIds({ ...enabled.value }, mods)
    if (JSON.stringify(merged) !== JSON.stringify(enabled.value)) {
      enabled.value = merged
    }
  }

  function stripModWorkflowEmployeeKeys() {
    const builtins = defaultWorkflowBuiltinEnabled()
    const next: Record<string, boolean> = { ...builtins }
    for (const k of Object.keys(builtins)) {
      if (k in enabled.value) next[k] = enabled.value[k]
    }
    enabled.value = next
    persistAndNotify()
  }

  function pruneOrphanWorkflowEmployeeToggles(mods: ModWithWorkflowEmployees[] | undefined) {
    const builtins = defaultWorkflowBuiltinEnabled()
    const manifestIds = collectManifestWorkflowEmployeeIds(mods)
    const next: Record<string, boolean> = { ...enabled.value }
    for (const k of Object.keys(next)) {
      if (k in builtins) continue
      if (!manifestIds.has(k)) delete next[k]
    }
    if (JSON.stringify(next) !== JSON.stringify(enabled.value)) {
      enabled.value = next
      persistAndNotify()
    }
  }

  function reloadFromLocalStorage() {
    enabled.value = readWorkflowEnabledFromLocalStorage()
  }

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

  return {
    enabled,
    hydrateFromMods,
    stripModWorkflowEmployeeKeys,
    pruneOrphanWorkflowEmployeeToggles,
    reloadFromLocalStorage,
    setAll,
    toggle,
    enableAllOn,
    persistAndNotify,
  }
})
