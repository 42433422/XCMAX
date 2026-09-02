<template>
  <div class="nc">
    <div class="nc-head">
      <div class="nc-head-l">
        <h1 class="nc-title">通知中心</h1>
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

    <div v-if="loading" class="nc-loading">加载中</div>

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

        <button v-if="!n.is_read" type="button" class="nc-read" @click.stop="markOne(n.id)" title="标为已读">标为已读
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
import { asUnknownRecord, errorMessage } from '../utils/typeNarrowing'

interface NotificationItem {
  id: string | number
  is_read: boolean
  type: string
  title: string
  content: string
  created_at: string
  data?: Record<string, unknown>
}

const router = useRouter()
const notificationStore = useNotificationStore()
const loading = ref(true)
const err = ref('')
const items = ref<NotificationItem[]>([])
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
    const res = asUnknownRecord(await api.notificationsList(unreadOnly.value, 80, category.value || ''))
    items.value = Array.isArray(res.notifications) ? (res.notifications as NotificationItem[]) : []
  } catch (e: unknown) {
    err.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onItemClick(n: NotificationItem) {
  try {
    if (!n.is_read) await notificationStore.markRead(n.id)
  } catch {
    /* ignore */
  }
  const data = asUnknownRecord(n.data)
  switch (n.type) {
    case 'payment_success':
      if (data.order_no) router.push({ name: 'order-detail', params: { orderId: String(data.order_no) } })
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

async function markOne(id: string | number) {
  try {
    await notificationStore.markRead(id)
    await load()
  } catch (e: unknown) {
    err.value = errorMessage(e)
  }
}

async function markAll() {
  try {
    await notificationStore.markAllRead()
    await load()
  } catch (e: unknown) {
    err.value = errorMessage(e)
  }
}

onMounted(load)
</script>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./NotificationCenter.css，模板与逻辑保持原样。 -->
<style scoped src="./NotificationCenter.css"></style>
