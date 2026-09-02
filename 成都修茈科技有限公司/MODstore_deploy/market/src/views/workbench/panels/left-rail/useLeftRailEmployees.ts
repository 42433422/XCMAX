// LeftRail 员工列表逻辑：隐藏名单持久化、列表加载/删除/一键清空与路由选中。
import { computed, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '../../../../api'
import { isPlannedDutyRosterPkgId as isDutyRosterEmployee } from '../../../../utils/workbenchEmployeeFilter'

const HIDDEN_PKG_IDS_KEY = 'modstore_emp_chat_hidden_pkg_ids'

function readHiddenPkgIds(): Set<string> {
  try {
    const raw = localStorage.getItem(HIDDEN_PKG_IDS_KEY)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.filter((x): x is string => typeof x === 'string'))
  } catch {
    return new Set()
  }
}

export type EmployeeRow = { id: string; name?: string; source?: 'catalog' | 'v1_catalog' }

export function useLeftRailEmployees(deps: {
  isAdmin: Ref<boolean>
  selectEmployee: (id: string) => void
  route: RouteLocationNormalizedLoaded
}) {
  const { isAdmin, selectEmployee, route } = deps

  const employees = ref<EmployeeRow[]>([])
  const hiddenPkgIds = ref<Set<string>>(readHiddenPkgIds())
  const loadingList = ref(false)
  const listError = ref('')
  const deletingId = ref('')
  const purgeBusy = ref(false)

  /** 仅显示未隐藏的非在岗员工；在岗员工不可操作，不在此列表 */
  const visibleEmployees = computed(() =>
    employees.value.filter((e) => !hiddenPkgIds.value.has(e.id) && !isDutyRosterEmployee(e.id)),
  )
  const _hasV1OnlyEmployees = computed(() => employees.value.some((e) => e.source === 'v1_catalog'))

  function persistHiddenPkgIds() {
    localStorage.setItem(HIDDEN_PKG_IDS_KEY, JSON.stringify([...hiddenPkgIds.value]))
  }

  function hideLocally(pkgId: string) {
    hiddenPkgIds.value = new Set([...hiddenPkgIds.value, pkgId])
    persistHiddenPkgIds()
  }

  function clearHiddenPkgIds() {
    hiddenPkgIds.value = new Set()
    persistHiddenPkgIds()
  }

  async function loadEmployees() {
    listError.value = ''
    loadingList.value = true
    try {
      const rows = await api.listEmployees()
      if (!Array.isArray(rows)) {
        employees.value = []
        return
      }
      employees.value = (rows as Record<string, unknown>[]).map((e) => {
        const id = String(e.id ?? '').trim()
        const rawSrc = e.source
        const source: EmployeeRow['source'] = rawSrc === 'v1_catalog' ? 'v1_catalog' : 'catalog'
        return { id, name: typeof e.name === 'string' ? e.name : undefined, source }
      })
    } catch (e: unknown) {
      listError.value = e instanceof Error ? e.message : String(e)
      employees.value = []
    } finally {
      loadingList.value = false
    }
  }

  async function confirmDeleteEmployee(e: EmployeeRow) {
    if (!isAdmin.value) return
    if (isDutyRosterEmployee(e.id)) {
      window.alert('该员工属于编制在岗岗位包（与「员工工作流管理」矩阵一致），已锁定，禁止从工作台删除。')
      return
    }
    const label = e.name || e.id
    const ok = window.confirm(`确定删除员工包「${label}」（${e.id}）？将从目录与数据库移除，不可恢复。`)
    if (!ok) return
    deletingId.value = e.id
    listError.value = ''
    try {
      await api.adminDeleteEmployeePack(e.id)
      hiddenPkgIds.value.delete(e.id)
      persistHiddenPkgIds()
      await loadEmployees()
    } catch (err: unknown) {
      listError.value = err instanceof Error ? err.message : String(err)
    } finally {
      deletingId.value = ''
    }
  }

  async function purgeAllEmployees() {
    if (!isAdmin.value || purgeBusy.value) return
    const ok = window.confirm(
      '确定一键清空员工仓库？\n将原子地删除 packages.json 与 catalog_items 中所有 employee_pack 行（含磁盘 .xcemp 文件），\n用于解决「老是删不完」（两个数据源 pkg_id 不重合时单条对账会遗漏）。\n不可恢复。',
    )
    if (!ok) return
    purgeBusy.value = true
    listError.value = ''
    try {
      const res = (await api.adminPurgeAllEmployeePacks()) as {
        removed_packages_json?: number
        removed_db_rows?: number
        removed_files?: number
      }
      const a = Number(res?.removed_packages_json || 0)
      const b = Number(res?.removed_db_rows || 0)
      const c = Number(res?.removed_files || 0)
      hiddenPkgIds.value = new Set()
      persistHiddenPkgIds()
      await loadEmployees()
      listError.value = `已清空员工仓库：packages.json 删 ${a} 行，DB 删 ${b} 行，磁盘文件删 ${c} 个`
    } catch (err: unknown) {
      listError.value = err instanceof Error ? err.message : String(err)
    } finally {
      purgeBusy.value = false
    }
  }

  async function maybeSelectFromRoute() {
    const packId = String(route.query.packId ?? route.query.id ?? '').trim()
    if (packId) {
      selectEmployee(packId)
    }
  }

  onMounted(async () => {
    await loadEmployees()
    await maybeSelectFromRoute()
  })

  watch(
    () => String(route.query.packId ?? route.query.id ?? '').trim(),
    async (packId, prev) => {
      if (!packId || packId === prev) return
      await loadEmployees()
      await maybeSelectFromRoute()
    },
  )

  return {
    employees,
    hiddenPkgIds,
    loadingList,
    listError,
    deletingId,
    purgeBusy,
    visibleEmployees,
    _hasV1OnlyEmployees,
    loadEmployees,
    confirmDeleteEmployee,
    purgeAllEmployees,
    hideLocally,
    clearHiddenPkgIds,
  }
}
