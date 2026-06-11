import { computed, onMounted, ref } from 'vue'
import { buildFullApiUrl } from '@/api/core'
import {
  KITTEN_VIZ_EMPLOYEES,
  findKittenVizEmployee,
  type KittenVizEmployeeDef,
} from '@/constants/kittenVisualizationEmployees'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { buildTenantScopedStorageKey } from '@/utils/tenantStorageScope'

const LS_KEY_BASE = 'xcagi_kitten_viz_employee_pkg'
const BRIDGE_INSTALLED_URL = '/api/mod/xcagi-office-employee-pack-bridge/installed'

export interface KittenVizEmployeeState extends KittenVizEmployeeDef {
  installed: boolean
}

function kittenVizStorageKey(): string {
  return buildTenantScopedStorageKey(LS_KEY_BASE)
}

function readStoredPkgId(): string {
  try {
    const raw = localStorage.getItem(kittenVizStorageKey())
    if (raw && KITTEN_VIZ_EMPLOYEES.some((e) => e.pkgId === raw)) return raw
  } catch {
    /* ignore */
  }
  return KITTEN_VIZ_EMPLOYEES[0].pkgId
}

function collectInstalledIds(data: Record<string, unknown> | null | undefined): Set<string> {
  const ids = new Set<string>()
  if (!data || typeof data !== 'object') return ids
  const buckets = ['office_installed', 'other_installed']
  for (const key of buckets) {
    const list = data[key]
    if (!Array.isArray(list)) continue
    for (const row of list) {
      if (!row || typeof row !== 'object') continue
      const pid = String((row as Record<string, unknown>).pack_id || (row as Record<string, unknown>).id || '').trim()
      if (pid) ids.add(pid)
    }
  }
  return ids
}

export function useKittenVizEmployees() {
  const loading = ref(false)
  const installedIds = ref<Set<string>>(new Set())
  const selectedPkgId = ref(readStoredPkgId())

  const employees = computed<KittenVizEmployeeState[]>(() =>
    KITTEN_VIZ_EMPLOYEES.map((def) => ({
      ...def,
      installed: installedIds.value.has(def.pkgId),
    })),
  )

  const selected = computed(() => findKittenVizEmployee(selectedPkgId.value) || KITTEN_VIZ_EMPLOYEES[0])

  const installedCount = computed(() => employees.value.filter((e) => e.installed).length)

  async function refreshInstalled() {
    loading.value = true
    try {
      const resp = await fetch(buildFullApiUrl(BRIDGE_INSTALLED_URL), { credentials: 'include' })
      const json = await safeJsonRequest<{ success?: boolean; data?: Record<string, unknown> }>(resp)
      installedIds.value = collectInstalledIds(json?.data)
    } catch {
      installedIds.value = new Set()
    } finally {
      loading.value = false
    }
  }

  function selectEmployee(pkgId: string) {
    if (!KITTEN_VIZ_EMPLOYEES.some((e) => e.pkgId === pkgId)) return
    selectedPkgId.value = pkgId
    try {
      localStorage.setItem(kittenVizStorageKey(), pkgId)
    } catch {
      /* ignore */
    }
  }

  onMounted(() => {
    void refreshInstalled()
  })

  return {
    employees,
    selected,
    selectedPkgId,
    installedCount,
    loading,
    refreshInstalled,
    selectEmployee,
  }
}
