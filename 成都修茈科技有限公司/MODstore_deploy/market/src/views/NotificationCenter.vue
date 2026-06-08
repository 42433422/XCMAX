<template>
  <div class="nc">
    <div class="nc-head">
      <div class="nc-head-l">
        <h1 class="nc-title">通知</h1>
        <span v-if="totalUnread > 0" class="nc-badge">{{ totalUnread }}</span>
      </div>
      <div class="nc-head-r">
        <label class="nc-chk"><input type="checkbox" v-model="unreadOnly" @change="load" /><span>仅未读</span></label>
        <button type="button" class="nc-btn-text" :disabled="!items.length" @click="markAll">全部已读</button>
      </div>
    </div>

    <div class="nc-tabs">
      <button
        v-for="c in categories"
        :key="c.value"
        type="button"
        :class="['nc-tab', { 'nc-tab--on': category === c.value }]"
        @click="setCategory(c.value)"
      >
        {{ c.label }}
        <span v-if="c.unread > 0" class="nc-tab-dot" />
      </button>
    </div>

    <div v-if="err" class="nc-err">{{ err }}</div>

    <div v-if="loading" class="nc-loading">
      <div class="nc-spin" />
    </div>

    <div v-else-if="items.length" class="nc-list">
      <div
        v-for="n in items"
        :key="n.id"
        class="nc-item"
        :class="{ 'nc-item--unread': !n.is_read }"
        @click="onItemClick(n)"
      >
        <span class="nc-icon" :class="'nc-icon--' + (n.type || 'system')">
          <svg v-if="n.type === 'payment_success'" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M2 6h12"/><path d="M5 9h2"/></svg>
          <svg v-else-if="n.type === 'employee_execution_done'" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><rect x="3" y="4" width="10" height="7" rx="1.5"/><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5"/></svg>
          <svg v-else-if="n.type === 'quota_warning'" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M8 2L1.5 13h13L8 2z"/><path d="M8 6.5v3"/><circle cx="8" cy="11" r="0.5" fill="currentColor" stroke="none"/></svg>
          <svg v-else width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="8" cy="8" r="6"/><path d="M8 5v3.5M8 10.5v0"/></svg>
        </span>

        <div class="nc-body">
          <div class="nc-row">
            <span class="nc-name">{{ n.title }}</span>
            <span class="nc-time">{{ formatTime(n.created_at) }}</span>
          </div>
          <p class="nc-desc" :class="{ 'nc-desc--clip': !expandedItems.has(n.id) }" @click.stop="toggleItem(n.id)">{{ n.content }}</p>
        </div>

        <button v-if="!n.is_read" type="button" class="nc-read" @click.stop="markOne(n.id)" title="标为已读">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8.5 6.5 12 13 4.5"/></svg>
        </button>
      </div>
    </div>

    <div v-else class="nc-empty">
      <svg width="40" height="40" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><rect x="10" y="8" width="28" height="32" rx="4"/><path d="M17 18h14M17 24h10M17 30h6"/></svg>
      <p>暂无通知</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useNotificationStore } from '../stores/notifications'

const router = useRouter()
const notificationStore = useNotificationStore()
const loading = ref(true)
const err = ref('')
const items = ref<any[]>([])
const unreadOnly = ref(false)
const category = ref('')
const expandedItems = ref(new Set<string | number>())

const categoryMeta: Record<string, { label: string }> = {
  payment_success: { label: '支付' },
  employee_execution_done: { label: '员工' },
  quota_warning: { label: '配额' },
  system: { label: '系统' },
}

const totalUnread = computed(() => items.value.filter(n => !n.is_read).length)

const categories = computed(() => {
  const cats = [
    { value: '', label: '全部', unread: 0 },
    ...Object.entries(categoryMeta).map(([value, { label }]) => ({
      value,
      label,
      unread: items.value.filter(n => n.type === value && !n.is_read).length,
    })),
  ]
  cats[0].unread = items.value.filter(n => !n.is_read).length
  return cats
})

function toggleItem(id: string | number) {
  const s = new Set(expandedItems.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expandedItems.value = s
}

function formatTime(t: string) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function setCategory(v: string) {
  category.value = v
  void load()
}

async function load() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.notificationsList(unreadOnly.value, 80, category.value || '')
    items.value = res.notifications || []
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

async function onItemClick(n: any) {
  try {
    if (!n.is_read) await notificationStore.markRead(n.id)
  } catch {
    /* ignore */
  }
  const data = n.data || {}
  switch (n.type) {
    case 'payment_success':
      if (data.order_no) router.push({ name: 'order-detail', params: { orderId: data.order_no } })
      break
    case 'employee_execution_done':
      router.push({ path: '/workbench', query: { focus: 'employee' } })
      break
    case 'quota_warning':
      router.push({ name: 'wallet' })
      break
    default:
      break
  }
}

async function markOne(id: string) {
  try {
    await notificationStore.markRead(id)
    await load()
  } catch (e: any) {
    err.value = e?.message || String(e)
  }
}

async function markAll() {
  try {
    await notificationStore.markAllRead()
    await load()
  } catch (e: any) {
    err.value = e?.message || String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.nc {
  max-width: 600px;
  margin: 0 auto;
  padding: var(--page-pad-y, 1.5rem) var(--layout-pad-x, 1rem);
}

.nc-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}
.nc-head-l {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.nc-title {
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin: 0;
  color: #fff;
}
.nc-badge {
  background: #6366f1;
  color: #fff;
  font-size: 0.68rem;
  font-weight: 700;
  min-width: 1.2rem;
  height: 1.2rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 0.35rem;
}
.nc-head-r {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.nc-chk {
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.5);
  display: flex;
  align-items: center;
  gap: 0.3rem;
  cursor: pointer;
}
.nc-btn-text {
  border: none;
  background: none;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.82rem;
  cursor: pointer;
  padding: 0.25rem 0.4rem;
  border-radius: 6px;
  transition: color 0.2s, background 0.2s;
}
.nc-btn-text:hover:not(:disabled) {
  color: #fff;
  background: rgba(255, 255, 255, 0.06);
}
.nc-btn-text:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.nc-tabs {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 1.25rem;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.nc-tabs::-webkit-scrollbar { display: none; }
.nc-tab {
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  transition: all 0.2s;
}
.nc-tab:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.75);
}
.nc-tab--on {
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
}
.nc-tab-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #6366f1;
  flex-shrink: 0;
}

.nc-err {
  background: rgba(220, 53, 69, 0.1);
  color: #f8a0a8;
  padding: 0.6rem 0.8rem;
  border-radius: 10px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.nc-loading {
  display: flex;
  justify-content: center;
  padding: 4rem 0;
}
.nc-spin {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.08);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: nc-rot 0.65s linear infinite;
}
@keyframes nc-rot { to { transform: rotate(360deg); } }

.nc-list {
  display: flex;
  flex-direction: column;
}
.nc-item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
}
.nc-item:last-child {
  border-bottom: none;
}
.nc-item:hover {
  background: rgba(255, 255, 255, 0.02);
  border-radius: 8px;
}
.nc-item--unread {
  background: rgba(99, 102, 241, 0.025);
  border-radius: 8px;
  padding-left: 0.5rem;
  padding-right: 0.5rem;
  margin: 0 -0.5rem;
  border-bottom-color: transparent;
  margin-bottom: 2px;
}
.nc-item--unread + .nc-item--unread {
  margin-top: -2px;
}

.nc-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.1rem;
}
.nc-icon--payment_success {
  background: rgba(52, 199, 89, 0.12);
  color: #34c759;
}
.nc-icon--employee_execution_done {
  background: rgba(99, 102, 241, 0.12);
  color: #818cf8;
}
.nc-icon--quota_warning {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}
.nc-icon--system {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.4);
}

.nc-body {
  flex: 1;
  min-width: 0;
}
.nc-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.15rem;
}
.nc-name {
  font-weight: 600;
  font-size: 0.88rem;
  color: #fff;
  line-height: 1.35;
}
.nc-time {
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.28);
  flex-shrink: 0;
}
.nc-desc {
  margin: 0;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.82rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.nc-desc--clip {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: pointer;
}

.nc-read {
  border: none;
  background: none;
  color: rgba(255, 255, 255, 0.2);
  cursor: pointer;
  padding: 0.3rem;
  border-radius: 6px;
  flex-shrink: 0;
  margin-top: 0.1rem;
  opacity: 0;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.nc-item:hover .nc-read,
.nc-item--unread .nc-read {
  opacity: 1;
}
.nc-read:hover {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
}

.nc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 5rem 0;
  color: rgba(255, 255, 255, 0.2);
}
.nc-empty p {
  margin: 0;
  font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.35);
}

html[data-workbench-theme='light'] .nc {
  background: #f5f5f7;
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .nc-title {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .nc-badge {
  background: #0071e3;
}
html[data-workbench-theme='light'] .nc-chk {
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-btn-text {
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-btn-text:hover:not(:disabled) {
  color: #1d1d1f;
  background: rgba(0, 0, 0, 0.04);
}
html[data-workbench-theme='light'] .nc-tab {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-tab:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .nc-tab--on {
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
}
html[data-workbench-theme='light'] .nc-tab-dot {
  background: #0071e3;
}
html[data-workbench-theme='light'] .nc-err {
  background: rgba(220, 53, 69, 0.06);
  color: #d63040;
}
html[data-workbench-theme='light'] .nc-spin {
  border-color: rgba(0, 0, 0, 0.06);
  border-top-color: #0071e3;
}
html[data-workbench-theme='light'] .nc-item {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .nc-item:hover {
  background: rgba(0, 0, 0, 0.02);
}
html[data-workbench-theme='light'] .nc-item--unread {
  background: rgba(0, 113, 227, 0.03);
}
html[data-workbench-theme='light'] .nc-icon--payment_success {
  background: rgba(52, 199, 89, 0.1);
  color: #248a3d;
}
html[data-workbench-theme='light'] .nc-icon--employee_execution_done {
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
}
html[data-workbench-theme='light'] .nc-icon--quota_warning {
  background: rgba(245, 158, 11, 0.1);
  color: #b45309;
}
html[data-workbench-theme='light'] .nc-icon--system {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-name {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .nc-time {
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-desc {
  color: #86868b;
}
html[data-workbench-theme='light'] .nc-read {
  color: rgba(0, 0, 0, 0.15);
}
html[data-workbench-theme='light'] .nc-read:hover {
  color: #0071e3;
  background: rgba(0, 113, 227, 0.06);
}
html[data-workbench-theme='light'] .nc-empty {
  color: #c7c7cc;
}
html[data-workbench-theme='light'] .nc-empty p {
  color: #86868b;
}
</style>
