<template>
  <div class="emp">
    <header class="emp-head">
      <div>
        <h1 class="emp-title">我的员工</h1>
        <p class="emp-sub">
          管理你的 AI 员工包。点击员工进入制作画布，可删除或隐藏不需要的员工。
        </p>
      </div>
      <button type="button" class="emp-refresh" :disabled="loadingList" @click="loadEmployees">
        {{ loadingList ? '刷新中…' : '↻ 刷新' }}
      </button>
    </header>

    <p v-if="listError" class="emp-flash" :class="listError.startsWith('已清空') ? 'emp-flash--ok' : 'emp-flash--err'">
      {{ listError }}
    </p>

    <section class="emp-list-wrap" aria-labelledby="emp-list-title">
      <h2 id="emp-list-title" class="emp-section-title">已创建的员工</h2>

      <p v-if="loadingList" class="emp-empty">加载中…</p>
      <p v-else-if="!visibleEmployees.length" class="emp-empty">
        暂无可见员工。
        <template v-if="hiddenPkgIds.size">
          <button type="button" class="emp-btn emp-btn--ghost" @click="clearHiddenPkgIds">
            显示已隐藏（{{ hiddenPkgIds.size }}）
          </button>
        </template>
      </p>

      <ul v-else class="emp-grid">
        <li v-for="e in visibleEmployees" :key="e.id" class="emp-card">
          <header class="emp-card-head">
            <span v-if="e.source === 'v1_catalog'" class="emp-badge emp-badge--v1">仅目录</span>
            <span v-if="isDutyRosterEmployee(e.id)" class="emp-badge emp-badge--duty">在岗</span>
            <h3 class="emp-name">{{ e.name || e.id }}</h3>
          </header>
          <p class="emp-id">{{ e.id }}</p>
          <div class="emp-card-actions">
            <button type="button" class="emp-btn emp-btn--ghost" @click="openEmployee(e.id)">进入制作</button>
            <button
              v-if="!isDutyRosterEmployee(e.id)"
              type="button"
              class="emp-btn emp-btn--ghost"
              @click="hideLocally(e.id)"
            >
              隐藏
            </button>
            <button
              v-if="isAdmin && !isDutyRosterEmployee(e.id)"
              type="button"
              class="emp-btn emp-btn--danger"
              :disabled="deletingId === e.id"
              @click="confirmDeleteEmployee(e)"
            >
              {{ deletingId === e.id ? '删除中…' : '删除' }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <div v-if="isAdmin && hasV1OnlyEmployees" class="emp-purge-row">
      <button type="button" class="emp-btn emp-btn--danger" :disabled="purgeBusy" @click="purgeAllEmployees">
        {{ purgeBusy ? '清空中…' : '一键清空员工仓库' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'
import { isPlannedDutyRosterPkgId as isDutyRosterEmployee } from '../utils/workbenchEmployeeFilter'

const router = useRouter()
const auth = useAuthStore()
const { isAdmin } = storeToRefs(auth)

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

type EmployeeRow = { id: string; name?: string; source?: 'catalog' | 'v1_catalog' }

const employees = ref<EmployeeRow[]>([])
const hiddenPkgIds = ref<Set<string>>(readHiddenPkgIds())
const loadingList = ref(false)
const listError = ref('')
const deletingId = ref('')
const purgeBusy = ref(false)

const visibleEmployees = computed(() =>
  employees.value.filter((e) => !hiddenPkgIds.value.has(e.id) && !isDutyRosterEmployee(e.id)),
)
const hasV1OnlyEmployees = computed(() => employees.value.some((e) => e.source === 'v1_catalog'))

function persistHiddenPkgIds() {
  localStorage.setItem(HIDDEN_PKG_IDS_KEY, JSON.stringify([...hiddenPkgIds.value]))
}

function hideLocally(pkgId: string) {
  const row = employees.value.find((e) => e.id === pkgId)
  const label = row?.name || pkgId
  if (!window.confirm(`确定在列表中隐藏「${label}」？\n仅影响本机展示，不会删除员工包。`)) return
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
    window.alert('该员工属于编制在岗岗位包，已锁定，禁止删除。')
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
    '确定一键清空员工仓库？\n将原子地删除 packages.json 与 catalog_items 中所有 employee_pack 行（含磁盘 .xcemp 文件），\n不可恢复。',
  )
  if (!ok) return
  purgeBusy.value = true
  listError.value = ''
  try {
    const res: any = await api.adminPurgeAllEmployeePacks()
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

function openEmployee(id: string) {
  router.push({ name: 'workbench-shell', params: { target: 'employee', id } })
}

onMounted(loadEmployees)
</script>

<style scoped>
.emp {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  color: #d8dde6;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}
.emp-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}
.emp-title {
  margin: 0;
  font-size: 22px;
}
.emp-sub {
  margin: 8px 0 0;
  color: #9aa3b2;
  font-size: 14px;
  line-height: 1.6;
  max-width: 720px;
}
.emp-refresh {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #6366f1;
  color: #fff;
  font-weight: 600;
  border: none;
  padding: 10px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
.emp-refresh:disabled {
  opacity: 0.55;
  cursor: default;
}
.emp-flash {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}
.emp-flash--err {
  background: #3a1515;
  color: #f5a8a8;
  border: 1px solid #6b2a2a;
}
.emp-flash--ok {
  background: #143b1f;
  color: #9be7b7;
  border: 1px solid #2a6b3f;
}
.emp-section-title {
  margin: 28px 0 10px;
  font-size: 16px;
  color: #e8ecf3;
}
.emp-empty {
  color: #6b7280;
  padding: 32px;
  text-align: center;
  background: #0f131a;
  border: 1px dashed #2c333f;
  border-radius: 8px;
}
.emp-grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.emp-card {
  background: #0f131a;
  border: 1px solid #2c333f;
  border-radius: 8px;
  padding: 14px 16px;
}
.emp-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.emp-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.emp-badge--duty {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
  border: 1px solid rgba(16, 185, 129, 0.35);
}
.emp-badge--v1 {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
}
.emp-name {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin: 0;
}
.emp-id {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
  word-break: break-all;
  margin: 2px 0 0;
}
.emp-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.emp-btn {
  background: #2ba8ff;
  color: #061018;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
}
.emp-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.emp-btn--ghost {
  background: transparent;
  color: #c7e5ff;
  border: 1px solid #2c5a82;
}
.emp-btn--danger {
  background: transparent;
  color: #f57878;
  border: 1px solid #6b2a2a;
}
.emp-purge-row {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #2c333f;
}
html[data-workbench-theme='light'] .emp {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .emp-sub {
  color: #86868b;
}
html[data-workbench-theme='light'] .emp-refresh {
  background: #0071e3;
}
html[data-workbench-theme='light'] .emp-flash--err {
  background: rgba(215,0,21,.08);
  color: #d70015;
  border-color: rgba(215,0,21,.2);
}
html[data-workbench-theme='light'] .emp-flash--ok {
  background: rgba(52,168,83,.08);
  color: #34a853;
  border-color: rgba(52,168,83,.2);
}
html[data-workbench-theme='light'] .emp-section-title {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .emp-empty {
  color: #86868b;
  background: #ffffff;
  border-color: rgba(0,0,0,.08);
}
html[data-workbench-theme='light'] .emp-card {
  background: #ffffff;
  border-color: rgba(0,0,0,.08);
}
html[data-workbench-theme='light'] .emp-badge--duty {
  background: rgba(52,168,83,.08);
  color: #34a853;
  border-color: rgba(52,168,83,.2);
}
html[data-workbench-theme='light'] .emp-badge--v1 {
  background: rgba(217,119,6,.08);
  color: #d97706;
  border-color: rgba(217,119,6,.2);
}
html[data-workbench-theme='light'] .emp-name {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .emp-id {
  color: #86868b;
}
html[data-workbench-theme='light'] .emp-btn {
  background: #0071e3;
  color: #fff;
}
html[data-workbench-theme='light'] .emp-btn--ghost {
  color: #1d1d1f;
  border-color: rgba(0,0,0,0.1);
  background: rgba(0,0,0,0.03);
}
html[data-workbench-theme='light'] .emp-btn--ghost:hover {
  background: rgba(0,0,0,0.06);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .emp-btn--danger {
  color: #d70015;
  border-color: rgba(215,0,21,.2);
}
html[data-workbench-theme='light'] .emp-purge-row {
  border-top-color: rgba(0,0,0,.08);
}
</style>
