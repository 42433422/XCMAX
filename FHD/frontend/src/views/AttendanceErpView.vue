<template>
  <main class="attendance-erp">
    <header class="attendance-erp__header">
      <div class="attendance-erp__header-copy">
        <div class="attendance-erp__eyebrow">ERP · 人事与考勤</div>
        <h1 class="attendance-erp__title">{{ title }}</h1>
        <p class="attendance-erp__description">{{ description }}</p>
      </div>
      <div class="attendance-erp__header-meta" aria-label="数据概览">
        <div class="attendance-erp__metric">
          <strong>{{ total }}</strong>
          <span>{{ countLabel }}</span>
        </div>
        <div class="attendance-erp__source">
          <span class="attendance-erp__source-dot"></span>
          {{ dataSourceLabel }}
        </div>
      </div>
    </header>

    <section v-if="legacyPending" class="attendance-erp__migration" role="status">
      <div>
        <strong>发现旧版考勤数据，尚未归入 ERP</strong>
        <span>
          人员 {{ legacyCounts.employees || 0 }}、部门 {{ legacyCounts.departments || 0 }}、考勤明细
          {{ legacyCounts.daily_records || 0 }}。迁移前仍保持只读，不会混入新数据。
        </span>
      </div>
      <button
        class="attendance-erp__button attendance-erp__button--primary"
        type="button"
        :disabled="migrating"
        @click="migrateLegacy"
      >
        {{ migrating ? '正在迁移…' : '确认归入当前组织' }}
      </button>
    </section>

    <form class="attendance-erp__toolbar" role="search" @submit.prevent="applySearch">
      <label class="attendance-erp__search" :aria-label="searchPlaceholder">
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model="searchInput" :placeholder="searchPlaceholder" />
      </label>
      <button class="attendance-erp__button attendance-erp__button--primary" type="submit" :disabled="loading">
        查询
      </button>
      <button class="attendance-erp__button attendance-erp__button--secondary" type="button" :disabled="loading" @click="load()">
        <i class="fa fa-refresh" aria-hidden="true"></i>
        {{ loading ? '读取中…' : '刷新' }}
      </button>
      <span v-if="search" class="attendance-erp__filter-note">正在筛选“{{ search }}”</span>
    </form>

    <section class="attendance-erp__panel">
      <div v-if="error" class="attendance-erp__state attendance-erp__state--error">{{ error }}</div>
      <div v-else-if="loading" class="attendance-erp__state">正在读取 ERP 数据…</div>
      <div v-else-if="items.length === 0" class="attendance-erp__state">
        <strong>暂无{{ emptyLabel }}</strong>
        <span>请在“数据对接中心”确认导入后再查看，这里不会显示未执行的分析结果。</span>
      </div>
      <div v-else class="attendance-erp__table-wrap">
        <table class="attendance-erp__table" :class="`attendance-erp__table--${section}`">
          <thead>
            <tr>
              <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="String(item.id)">
              <td v-for="column in columns" :key="column.key" :class="`attendance-erp__cell--${column.key}`">
                <span v-if="column.key === 'source_system'" class="attendance-erp__origin">
                  {{ displayValue(item[column.key], column.key) }}
                </span>
                <strong v-else-if="column.key === 'employee_name'" class="attendance-erp__primary-cell">
                  {{ displayValue(item[column.key], column.key) }}
                </strong>
                <template v-else>{{ displayValue(item[column.key], column.key) }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer v-if="total > 0" class="attendance-erp__footer">
        <span>显示 {{ rangeStart }}–{{ rangeEnd }}，共 {{ total }} 条</span>
        <nav class="attendance-erp__pagination" aria-label="分页">
          <button
            class="attendance-erp__page-button"
            type="button"
            :disabled="loading || page <= 1"
            aria-label="上一页"
            @click="changePage(page - 1)"
          >
            <i class="fa fa-angle-left" aria-hidden="true"></i>
          </button>
          <span>第 {{ page }} / {{ pageCount }} 页</span>
          <button
            class="attendance-erp__page-button"
            type="button"
            :disabled="loading || page >= pageCount"
            aria-label="下一页"
            @click="changePage(page + 1)"
          >
            <i class="fa fa-angle-right" aria-hidden="true"></i>
          </button>
        </nav>
      </footer>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { primeCsrfCookie } from '@/api/core'
import { apiFetch } from '@/utils/apiBase'

type AttendanceSection = 'employees' | 'departments' | 'records'
type Row = Record<string, unknown> & { id: number | string }

const route = useRoute()
const section = computed<AttendanceSection>(() => {
  const value = String(route.meta.attendanceSection || 'employees')
  return value === 'departments' || value === 'records' ? value : 'employees'
})
const PAGE_SIZE = 20
const searchInput = ref('')
const search = ref('')
const page = ref(1)
const loading = ref(false)
const error = ref('')
const items = ref<Row[]>([])
const total = ref(0)
const source = ref('')
const legacyPending = ref(false)
const migrating = ref(false)
const legacyCounts = ref<Record<string, number>>({})

const copy = computed(() => {
  if (section.value === 'departments') {
    return {
      title: '部门管理',
      description: '组织与考勤归属的统一主数据，不再借用客户表。',
      placeholder: '搜索部门、上级部门或考勤组',
      empty: '部门档案',
    }
  }
  if (section.value === 'records') {
    return {
      title: '考勤记录',
      description: '已确认导入的真实打卡结果，与 AI 查询、导出和打印使用同一数据源。',
      placeholder: '按姓名、工号或部门筛选',
      empty: '考勤记录',
    }
  }
  return {
    title: '人员管理',
    description: 'ERP 人员档案，不再把员工伪装成产品。',
    placeholder: '搜索姓名、工号、部门或岗位',
    empty: '人员档案',
  }
})

const title = computed(() => copy.value.title)
const description = computed(() => copy.value.description)
const searchPlaceholder = computed(() => copy.value.placeholder)
const emptyLabel = computed(() => copy.value.empty)
const countLabel = computed(() => {
  if (section.value === 'departments') return '个部门'
  if (section.value === 'records') return '条记录'
  return '名人员'
})
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const rangeStart = computed(() => (total.value > 0 ? (page.value - 1) * PAGE_SIZE + 1 : 0))
const rangeEnd = computed(() => Math.min(total.value, (page.value - 1) * PAGE_SIZE + items.value.length))
const dataSourceLabel = computed(() => {
  const labels: Record<string, string> = {
    'erp:erp_employees': 'ERP 人员档案',
    'erp:erp_departments': 'ERP 组织架构',
    'erp:erp_attendance_records': 'ERP 考勤数据',
    'erp:erp_attendance_daily_records': 'ERP 考勤数据',
  }
  return labels[source.value] || 'ERP 主业务库'
})
const columns = computed(() => {
  if (section.value === 'departments') {
    return [
      { key: 'department', label: '部门' },
      { key: 'main_department', label: '上级部门' },
      { key: 'attendance_group', label: '考勤组' },
      { key: 'source_system', label: '来源' },
    ]
  }
  if (section.value === 'records') {
    return [
      { key: 'work_date', label: '日期' },
      { key: 'employee_name', label: '姓名' },
      { key: 'employee_no', label: '工号' },
      { key: 'department', label: '部门' },
      { key: 'shift_name', label: '班次' },
      { key: 'all_times_json', label: '打卡时间' },
      { key: 'late_count_hint', label: '迟到' },
      { key: 'absent_days', label: '缺勤' },
    ]
  }
  return [
    { key: 'employee_name', label: '姓名' },
    { key: 'employee_no', label: '工号' },
    { key: 'department', label: '部门' },
    { key: 'position', label: '岗位' },
    { key: 'attendance_group', label: '考勤组' },
    { key: 'source_system', label: '来源' },
  ]
})

function displayValue(value: unknown, key: string): string {
  if (key === 'all_times_json') {
    try {
      const values = JSON.parse(String(value || '[]'))
      return Array.isArray(values) && values.length ? values.join('、') : '—'
    } catch {
      return '—'
    }
  }
  if (key === 'source_system') {
    const labels: Record<string, string> = {
      legacy_attendance_migration: '旧考勤数据 · 已归入 ERP',
      erp_attendance_import: 'ERP 考勤导入',
      office_file_docking: '办公文件对接',
      manual: '人工录入',
    }
    return labels[String(value || '')] || (value ? 'ERP 业务数据' : 'ERP 主业务库')
  }
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function endpoint(): string {
  const query = new URLSearchParams({ page: String(page.value), page_size: String(PAGE_SIZE) })
  if (section.value === 'employees' || section.value === 'departments') {
    if (search.value) query.set('search', search.value)
  } else if (search.value) {
    // Records API keeps filters explicit; a human-entered term is resolved in
    // the most useful order without inventing a generic cross-field query.
    if (/^[A-Za-z0-9_-]+$/.test(search.value)) query.set('employee_no', search.value)
    else if (search.value.endsWith('部')) query.set('department', search.value)
    else query.set('employee_name', search.value)
  }
  const path =
    section.value === 'employees'
      ? '/api/erp/hr/employees'
      : section.value === 'departments'
        ? '/api/erp/hr/departments'
        : '/api/erp/hr/attendance-records'
  return `${path}?${query.toString()}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await apiFetch(endpoint(), { credentials: 'include' })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.success) throw new Error(payload?.message || `HTTP ${response.status}`)
    items.value = Array.isArray(payload.data?.items) ? payload.data.items : []
    total.value = Number(payload.data?.total || 0)
    source.value = String(payload.data?.source || '')
  } catch (cause) {
    items.value = []
    total.value = 0
    error.value = `ERP 数据读取失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    loading.value = false
  }
}

function applySearch() {
  search.value = searchInput.value.trim()
  page.value = 1
  void load()
}

function changePage(nextPage: number) {
  const bounded = Math.min(Math.max(1, nextPage), pageCount.value)
  if (bounded === page.value) return
  page.value = bounded
  void load()
}

async function loadLegacyPreview() {
  try {
    const response = await apiFetch('/api/erp/hr/legacy-migration-preview', { credentials: 'include' })
    const payload = await response.json().catch(() => null)
    const data = payload?.data || {}
    legacyCounts.value = data.counts || {}
    legacyPending.value = Boolean(data.available && !data.already_migrated)
  } catch {
    legacyPending.value = false
  }
}

async function migrateLegacy() {
  if (migrating.value) return
  migrating.value = true
  error.value = ''
  try {
    await primeCsrfCookie()
    const response = await apiFetch('/api/erp/hr/legacy-migrate', {
      method: 'POST',
      credentials: 'include',
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.success) throw new Error(payload?.message || `HTTP ${response.status}`)
    legacyPending.value = false
    await load()
  } catch (cause) {
    error.value = `旧版数据迁移失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    migrating.value = false
  }
}

watch(section, () => {
  searchInput.value = ''
  search.value = ''
  page.value = 1
  void load()
})
onMounted(() => {
  void Promise.all([load(), loadLegacyPreview()])
})
</script>

<style scoped>
.attendance-erp {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: hidden;
  padding: 22px 28px 24px;
  color: #17243b;
  background:
    radial-gradient(circle at 92% 4%, rgba(68, 137, 231, 0.12), transparent 30%),
    linear-gradient(180deg, #f7faff 0%, #f2f6fc 100%);
}
.attendance-erp__header {
  flex: none;
  min-height: 82px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 2px 2px 4px;
}
.attendance-erp__header-copy { min-width: 0; }
.attendance-erp__eyebrow { margin-bottom: 6px; color: #3978cc; font-size: 11px; font-weight: 750; letter-spacing: .12em; }
.attendance-erp__title { margin: 0; color: #14233a; font-size: 27px; line-height: 1.15; letter-spacing: -.025em; }
.attendance-erp__description { max-width: 720px; margin: 7px 0 0; color: #66758d; font-size: 13px; line-height: 1.5; }
.attendance-erp__header-meta { flex: none; display: flex; align-items: center; gap: 10px; }
.attendance-erp__metric {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 8px 13px;
  border: 1px solid rgba(199, 216, 238, .82);
  border-radius: 13px;
  background: rgba(255, 255, 255, .72);
  box-shadow: 0 8px 24px rgba(48, 87, 135, .06);
}
.attendance-erp__metric strong { color: #2368bd; font-size: 20px; line-height: 1; }
.attendance-erp__metric span { color: #60748f; font-size: 12px; }
.attendance-erp__source { display: inline-flex; align-items: center; gap: 8px; padding: 9px 12px; border: 1px solid #d7e3f4; border-radius: 13px; background: rgba(255,255,255,.78); color: #46617f; font-size: 12px; white-space: nowrap; }
.attendance-erp__source-dot { width: 7px; height: 7px; border-radius: 50%; background: #3f80d8; box-shadow: 0 0 0 4px rgba(63,128,216,.12); }
.attendance-erp__toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  margin: 0;
  padding: 6px;
  border: 1px solid rgba(215, 226, 241, .88);
  border-radius: 15px;
  background: rgba(255, 255, 255, .72);
}
.attendance-erp__migration { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 0; padding: 15px 16px; border: 1px solid #d8e5f5; border-radius: 14px; background: #edf5ff; color: #315c91; }
.attendance-erp__migration div { display: grid; gap: 4px; }
.attendance-erp__migration span { color: #627997; font-size: 13px; }
.attendance-erp__migration button { flex: none; }
.attendance-erp__search { display: flex; align-items: center; flex: 1; min-width: 180px; max-width: 560px; gap: 9px; padding: 0 10px; color: #7590b0; }
.attendance-erp__search input { width: 100%; height: 34px; border: 0; outline: 0; color: #17243b; background: transparent; }
.attendance-erp__button { height: 36px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 15px; border-radius: 10px; font-weight: 650; cursor: pointer; }
.attendance-erp__button--primary { border: 1px solid #2f74ce; color: white; background: #3f80d8; }
.attendance-erp__button--secondary { border: 1px solid #d2deed; color: #49627f; background: rgba(255, 255, 255, .86); }
.attendance-erp__button:disabled { cursor: wait; opacity: .62; }
.attendance-erp__filter-note { margin-left: auto; padding-right: 9px; color: #75869d; font-size: 12px; white-space: nowrap; }
.attendance-erp__panel { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; border: 1px solid #dce5f2; border-radius: 18px; background: rgba(255,255,255,.92); box-shadow: 0 16px 40px rgba(55,91,137,.08); }
.attendance-erp__table-wrap { flex: 1 1 auto; min-height: 0; overflow: auto; }
.attendance-erp__table { width: 100%; min-width: 860px; border-collapse: separate; border-spacing: 0; font-size: 13px; }
.attendance-erp__table--departments { min-width: 700px; }
.attendance-erp__table--records { min-width: 1100px; }
.attendance-erp__table th { position: sticky; top: 0; z-index: 1; padding: 12px 16px; border-bottom: 1px solid #e7edf5; color: #60748f; background: rgba(247,249,253,.97); backdrop-filter: blur(10px); font-size: 11px; font-weight: 750; text-align: left; white-space: nowrap; }
.attendance-erp__table td { height: 43px; box-sizing: border-box; padding: 10px 16px; border-bottom: 1px solid #edf1f6; color: #25354c; white-space: nowrap; }
.attendance-erp__table tbody tr { transition: background 140ms ease; }
.attendance-erp__table tbody tr:hover { background: #f5f9ff; }
.attendance-erp__primary-cell { color: #172b46; font-weight: 680; }
.attendance-erp__origin { display: inline-flex; padding: 4px 8px; border-radius: 999px; color: #4e6988; background: #eef4fb; font-size: 11px; }
.attendance-erp__state { display: grid; justify-items: center; gap: 8px; padding: 76px 24px; color: #79869a; text-align: center; }
.attendance-erp__state strong { color: #2d405b; font-size: 16px; }
.attendance-erp__state--error { color: #b44b55; }
.attendance-erp__footer { flex: none; min-height: 47px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 8px 14px 8px 16px; border-top: 1px solid #e7edf5; color: #76869b; background: rgba(250, 252, 255, .94); font-size: 12px; }
.attendance-erp__pagination { display: flex; align-items: center; gap: 10px; color: #5c708a; }
.attendance-erp__page-button { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #d4dfed; border-radius: 9px; color: #42607f; background: white; cursor: pointer; }
.attendance-erp__page-button:disabled { cursor: default; opacity: .42; }
@media (max-width: 900px) {
  .attendance-erp { padding: 18px 20px 20px; }
  .attendance-erp__header { min-height: 74px; }
  .attendance-erp__description { max-width: 500px; }
  .attendance-erp__metric { display: none; }
}
@media (max-width: 760px) {
  .attendance-erp { overflow: auto; padding: 16px; }
  .attendance-erp__header { display: block; }
  .attendance-erp__header-meta { margin-top: 12px; }
  .attendance-erp__toolbar { flex-wrap: wrap; }
  .attendance-erp__filter-note { width: 100%; margin: 0; padding: 0 10px 5px; }
  .attendance-erp__panel { min-height: 420px; }
}
</style>
