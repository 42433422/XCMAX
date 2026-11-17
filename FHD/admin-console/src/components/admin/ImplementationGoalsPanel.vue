<template>
  <section class="implementation-goals">
    <header class="goals-header">
      <div><h2>实现目标</h2><span class="muted">{{ dataDay ? `记录日期 ${dataDay}` : '目标清单' }}</span></div>
      <button class="btn" type="button" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
    </header>

    <div class="goals-filters">
      <input v-model="search" type="search" aria-label="搜索目标" placeholder="搜索目标、负责人" />
      <select v-model="status" aria-label="目标状态">
        <option value="">全部状态</option><option v-for="value in statuses" :key="value" :value="value">{{ label(value) }}</option>
      </select>
      <select v-model="line" aria-label="目标产线">
        <option value="">全部产线</option><option v-for="value in lines" :key="value" :value="value">{{ value }}</option>
      </select>
      <input v-model="day" type="date" aria-label="记录日期" />
      <button v-if="day" class="btn" type="button" @click="day = ''">最新清单</button>
    </div>

    <div v-if="loading" class="admin-card goals-state" role="status">正在加载目标…</div>
    <div v-else-if="error" class="admin-card goals-state" role="alert">
      <strong>目标清单暂时无法加载</strong><button class="btn" type="button" @click="load">重试</button>
    </div>
    <div v-else class="goals-content" :class="{ 'has-detail': selected }">
      <div class="admin-card goals-list">
        <div class="admin-pane goals-table-wrap" tabindex="0" aria-label="目标列表">
          <table class="goals-table">
            <thead><tr><th>优先级</th><th>目标</th><th class="goal-owner">负责人</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
            <tbody>
              <tr v-for="goal in pageItems" :key="goal.id" :class="{ selected: selected?.id === goal.id }">
                <td><span class="priority" :class="{ urgent: goal.priority === 'P0' }">{{ goal.priority || '—' }}</span></td>
                <td><span class="goal-title">{{ goal.text || '未命名目标' }}</span><span class="muted">{{ goal.line || '未分配产线' }}</span></td>
                <td class="goal-owner">{{ goal.employee_label || goal.employee_id || '未分配' }}</td>
                <td><span class="goal-status" :class="{ running: goal.status === 'in_progress' }">{{ label(goal.status) }}</span></td>
                <td><button class="detail-button" type="button" :aria-label="`查看目标 ${goal.id}`" :aria-expanded="selected?.id === goal.id" @click="selected = goal">详情</button></td>
              </tr>
              <tr v-if="!filtered.length"><td colspan="5" class="goals-empty">{{ goals.length ? '没有符合筛选条件的目标' : '暂无目标记录' }}</td></tr>
            </tbody>
          </table>
        </div>
        <footer class="goals-pager">
          <span class="muted">{{ filtered.length }} 项<span v-if="goals.length >= 1000"> · 当前最多载入 1000 项</span></span>
          <div><button class="btn" type="button" :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pageCount }}</span><button class="btn" type="button" :disabled="page >= pageCount" @click="page++">下一页</button></div>
        </footer>
      </div>
      <aside v-if="selected" class="admin-card goal-detail admin-pane" aria-label="目标详情" tabindex="0">
        <header class="goals-header"><h3>目标详情</h3><button class="btn" type="button" @click="selected = null">收起</button></header>
        <p class="goal-full-text">{{ selected.text || '未命名目标' }}</p>
        <dl>
          <dt>状态</dt><dd>{{ label(selected.status) }}</dd>
          <dt>优先级</dt><dd>{{ selected.priority || '—' }}</dd>
          <dt>负责人</dt><dd>{{ selected.employee_label || selected.employee_id || '未分配' }}</dd>
          <dt>产线</dt><dd>{{ selected.line || '—' }}</dd>
          <dt>范围</dt><dd>{{ selected.scope_path || '—' }}</dd>
          <dt>记录日期</dt><dd>{{ selected.day || dataDay || '—' }}</dd>
          <dt>最近更新</dt><dd>{{ selected.updated_at || '—' }}</dd>
        </dl>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import api from '@/api/core'
import { statusLabel } from '../../utils/statusLabel'

type Goal = Record<'id' | 'text' | 'priority' | 'status' | 'employee_id' | 'employee_label' | 'line' | 'scope_path' | 'day' | 'updated_at', string>
const goals = ref<Goal[]>([])
const selected = ref<Goal | null>(null)
const search = ref('')
const status = ref('')
const line = ref('')
const day = ref('')
const dataDay = ref('')
const loading = ref(false)
const error = ref(false)
const page = ref(1)
const pageSize = 8
let controller: AbortController | undefined
const label = (value: string) => value === 'merged' ? '已合入' : statusLabel(value)
const statuses = computed(() => [...new Set(goals.value.map(goal => goal.status).filter(Boolean))])
const lines = computed(() => [...new Set(goals.value.map(goal => goal.line).filter(Boolean))])
const filtered = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return goals.value.filter(goal => (!status.value || goal.status === status.value) && (!line.value || goal.line === line.value)
    && (!query || [goal.text, goal.employee_id, goal.employee_label, goal.line].join(' ').toLocaleLowerCase().includes(query)))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const pageItems = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([search, status, line], () => { page.value = 1; selected.value = null })
watch(page, () => { selected.value = null })

async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = false
  goals.value = []
  selected.value = null
  dataDay.value = ''
  page.value = 1
  try {
    const raw = await api.get<Record<string, unknown>>('/api/xcmax/admin/action-items', { kind: 'update', ...(day.value ? { day: day.value } : {}) }, { signal: request.signal, timeoutMs: 20_000, retry: false })
    if (request.signal.aborted) return
    const payload = (raw?.data ?? raw) as Record<string, unknown> | null
    if (raw?.success === false || raw?.ok === false || !payload || payload.ok === false || payload.success === false || !Array.isArray(payload.items)) throw new Error('Invalid goal list')
    goals.value = payload.items.map(item => {
      if (!item || typeof item !== 'object' || item.id == null) throw new Error('Invalid goal')
      return Object.fromEntries(['id', 'text', 'priority', 'status', 'employee_id', 'employee_label', 'line', 'scope_path', 'day', 'updated_at'].map(key => [key, String(item[key] ?? '')])) as Goal
    })
    dataDay.value = String(payload.day || '')
  } catch {
    if (!request.signal.aborted) error.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}
watch(day, load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.implementation-goals { display:flex; flex-direction:column; gap:16px; height:100%; min-height:0; }
.goals-header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.goals-header h2 { margin:0 0 6px; font-size:20px; }
.goals-header h3 { margin:0; font-size:16px; }
.goals-header .muted, .goal-title + .muted { font-size:12px; }
.goals-filters { display:flex; flex-wrap:wrap; gap:8px; }
.goals-filters input[type="search"] { flex:1; min-width:180px; }
.goals-filters :is(input,select) { border:1px solid var(--admin-border); background:#fff; }
.goals-content { flex:1; min-height:0; display:grid; grid-template-columns:minmax(0,1fr); gap:12px; }
.goals-content.has-detail { grid-template-columns:minmax(0,1fr) 280px; }
.goals-list { display:flex; flex-direction:column; min-height:0; overflow:hidden; }
.goals-table-wrap { flex:1; }
.goals-table { width:100%; border-collapse:collapse; font-size:13px; }
.goals-table th { position:sticky; top:0; z-index:1; background:#f8fafc; text-align:left; white-space:nowrap; }
.goals-table :is(th,td) { padding:12px; border-bottom:1px solid var(--admin-border); }
.goals-table tr.selected { background:#eff6ff; }
.goal-title { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; line-height:1.5; margin-bottom:4px; }
.priority { font-size:12px; color:var(--admin-muted); }
.priority.urgent { color:#b42318; font-weight:600; }
.goal-status { white-space:nowrap; border-radius:6px; padding:4px 6px; background:#f1f5f9; font-size:12px; }
.goal-status.running { color:#175cd3; background:#eff6ff; }
.detail-button { border:0; background:transparent; color:var(--admin-primary); cursor:pointer; white-space:nowrap; }
.goals-pager, .goals-pager > div { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.goals-pager { padding:12px; border-top:1px solid var(--admin-border); font-size:12px; }
.goal-detail { padding:16px; }
.goal-full-text { white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.6; }
.goal-detail dl { display:grid; grid-template-columns:64px minmax(0,1fr); gap:14px 10px; font-size:13px; }
.goal-detail dt { color:var(--admin-muted); }
.goal-detail dd { margin:0; overflow-wrap:anywhere; }
.goals-state { padding:48px 20px; display:grid; justify-items:center; gap:16px; color:var(--admin-muted); }
.goals-table .goals-empty { padding:48px 20px; text-align:center; color:var(--admin-muted); }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
@media (max-width:1100px) { .has-detail .goal-owner { display:none; } }
@media (max-width:700px) {
  .goals-content.has-detail { grid-template-columns:minmax(0,1fr); }
  .has-detail .goals-list { display:none; }
  .goal-owner { display:none; }
  .goals-pager { flex-wrap:wrap; }
}
</style>
