<template>
  <main class="attendance-erp">
    <header class="attendance-erp__header">
      <div>
        <div class="attendance-erp__eyebrow">ERP · 人事与考勤</div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <div class="attendance-erp__source">
        <span class="attendance-erp__source-dot"></span>
        ERP 主业务库
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
      <button type="button" :disabled="migrating" @click="migrateLegacy">
        {{ migrating ? '正在迁移…' : '确认归入当前组织' }}
      </button>
    </section>

    <section class="attendance-erp__toolbar">
      <label class="attendance-erp__search">
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model.trim="search" :placeholder="searchPlaceholder" @keyup.enter="load" />
      </label>
      <button type="button" :disabled="loading" @click="load">
        {{ loading ? '读取中…' : '刷新' }}
      </button>
    </section>

    <section class="attendance-erp__panel">
      <div v-if="error" class="attendance-erp__state attendance-erp__state--error">{{ error }}</div>
      <div v-else-if="loading" class="attendance-erp__state">正在读取 ERP 数据…</div>
      <div v-else-if="items.length === 0" class="attendance-erp__state">
        <strong>暂无{{ emptyLabel }}</strong>
        <span>请在“数据对接中心”确认导入后再查看，这里不会显示未执行的分析结果。</span>
      </div>
      <div v-else class="attendance-erp__table-wrap">
        <table>
          <thead>
            <tr>
              <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="String(item.id)">
              <td v-for="column in columns" :key="column.key">
                {{ displayValue(item[column.key], column.key) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer v-if="total > 0" class="attendance-erp__footer">
        共 {{ total }} 条 · 数据源 {{ source || 'ERP' }}
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
const search = ref('')
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
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function endpoint(): string {
  const query = new URLSearchParams({ page: '1', page_size: '200' })
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
  search.value = ''
  void load()
})
onMounted(() => {
  void Promise.all([load(), loadLegacyPreview()])
})
</script>

<style scoped>
.attendance-erp {
  min-height: 100%;
  padding: 28px;
  color: #17243b;
  background:
    radial-gradient(circle at 92% 4%, rgba(68, 137, 231, 0.12), transparent 30%),
    linear-gradient(180deg, #f7faff 0%, #f2f6fc 100%);
}
.attendance-erp__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.attendance-erp__eyebrow { margin-bottom: 7px; color: #3978cc; font-size: 12px; font-weight: 700; letter-spacing: .12em; }
h1 { margin: 0; font-size: 28px; letter-spacing: -.02em; }
p { margin: 8px 0 0; color: #66758d; }
.attendance-erp__source { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid #d7e3f4; border-radius: 999px; background: rgba(255,255,255,.8); color: #46617f; font-size: 13px; }
.attendance-erp__source-dot { width: 8px; height: 8px; border-radius: 50%; background: #3f80d8; box-shadow: 0 0 0 4px rgba(63,128,216,.12); }
.attendance-erp__toolbar { display: flex; gap: 10px; margin-bottom: 14px; }
.attendance-erp__migration { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: -4px 0 18px; padding: 15px 16px; border: 1px solid #d8e5f5; border-radius: 14px; background: #edf5ff; color: #315c91; }
.attendance-erp__migration div { display: grid; gap: 4px; }
.attendance-erp__migration span { color: #627997; font-size: 13px; }
.attendance-erp__migration button { flex: none; }
.attendance-erp__search { display: flex; align-items: center; flex: 1; max-width: 520px; gap: 9px; padding: 0 13px; border: 1px solid #d6e0ee; border-radius: 12px; background: white; color: #7590b0; }
.attendance-erp__search input { width: 100%; height: 42px; border: 0; outline: 0; color: #17243b; background: transparent; }
button { height: 42px; padding: 0 18px; border: 1px solid #2f74ce; border-radius: 12px; color: white; background: #3f80d8; cursor: pointer; }
button:disabled { cursor: wait; opacity: .65; }
.attendance-erp__panel { overflow: hidden; border: 1px solid #dce5f2; border-radius: 18px; background: rgba(255,255,255,.92); box-shadow: 0 16px 40px rgba(55,91,137,.08); }
.attendance-erp__table-wrap { overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { padding: 14px 16px; color: #60748f; background: #f7f9fd; font-size: 12px; font-weight: 700; text-align: left; white-space: nowrap; }
td { padding: 15px 16px; border-top: 1px solid #edf1f6; color: #25354c; }
tbody tr:hover { background: #f8fbff; }
.attendance-erp__state { display: grid; justify-items: center; gap: 8px; padding: 76px 24px; color: #79869a; text-align: center; }
.attendance-erp__state strong { color: #2d405b; font-size: 16px; }
.attendance-erp__state--error { color: #b44b55; }
.attendance-erp__footer { padding: 12px 16px; border-top: 1px solid #edf1f6; color: #76869b; font-size: 12px; }
@media (max-width: 760px) { .attendance-erp { padding: 18px; } .attendance-erp__header { display: block; } .attendance-erp__source { margin-top: 14px; } }
</style>
