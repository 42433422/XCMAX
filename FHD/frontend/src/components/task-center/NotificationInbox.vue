<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api/core'
import type { ApiResponse } from '@/types/api'

interface InboxItem {
  id: number
  title: string
  body: string
  created_at: string | null
  read_at: string | null
  is_read: boolean
}
interface InboxPage {
  notifications: InboxItem[]
  next_before_id: number | null
}

const props = defineProps<{ scopeKey: string }>()
const items = ref<InboxItem[]>([])
const loading = ref(false)
const marking = ref<number | null>(null)
const error = ref('')
const nextBeforeId = ref<number | null>(null)
const path = '/api/mobile/v1/notifications'
let generation = 0
let controller = new AbortController()
let timer: ReturnType<typeof setInterval> | undefined

function reset(): void {
  generation++
  controller.abort()
  controller = new AbortController()
  items.value = []
  nextBeforeId.value = null
  loading.value = false
  marking.value = null
  error.value = ''
}

async function refresh(older = false): Promise<void> {
  if (loading.value || marking.value !== null || (older && nextBeforeId.value === null)) return
  const epoch = generation
  loading.value = true
  error.value = ''
  try {
    const result = await api.get<ApiResponse<InboxPage>>(
      path + '/inbox',
      { limit: 50, before_id: older ? nextBeforeId.value : undefined },
      { signal: controller.signal },
    )
    if (epoch !== generation) return
    if (!result.success || !Array.isArray(result.data?.notifications)) throw new Error(result.message || '无法核对通知')
    const rows = result.data.notifications
    const merged = new Map<number, InboxItem>()
    for (const row of older ? [...items.value, ...rows] : rows) merged.set(row.id, row)
    items.value = [...merged.values()]
    nextBeforeId.value = result.data.next_before_id
  } catch {
    if (epoch === generation) error.value = '通知同步失败，请重新核对服务端状态。'
  } finally {
    if (epoch === generation) loading.value = false
  }
}

async function markRead(item: InboxItem): Promise<void> {
  if (item.is_read || marking.value !== null || loading.value) return
  const epoch = generation
  marking.value = item.id
  error.value = ''
  try {
    const result = await api.post<ApiResponse<InboxItem>>(
      path + '/' + encodeURIComponent(item.id) + '/read',
      {},
      { signal: controller.signal },
    )
    if (epoch !== generation) return
    if (!result.success || result.data?.id !== item.id || result.data.is_read !== true || !result.data.read_at) {
      throw new Error('缺少原通知已读回执')
    }
    const receipt = result.data
    items.value = items.value.map(row => row.id === receipt.id ? receipt : row)
  } catch {
    if (epoch === generation) error.value = '未收到已读回执，请刷新核对原通知。'
  } finally {
    if (epoch === generation) marking.value = null
  }
}

function refreshVisible(): void {
  if (document.visibilityState === 'visible') void refresh()
}
watch(() => props.scopeKey, () => { reset(); void refresh() }, { flush: 'sync' })
onMounted(() => {
  void refresh()
  timer = setInterval(refreshVisible, 10_000)
  document.addEventListener('visibilitychange', refreshVisible)
})
onBeforeUnmount(() => {
  if (timer !== undefined) clearInterval(timer)
  document.removeEventListener('visibilitychange', refreshVisible)
  reset()
})
</script>

<template>
  <section class="notification-inbox" aria-label="通知">
    <header>
      <strong>通知</strong>
      <button type="button" :disabled="loading || marking !== null" @click="refresh()">刷新</button>
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !items.length" role="status">正在同步通知…</p>
    <p v-else-if="!items.length">暂无通知</p>
    <article v-for="item in items" :key="item.id">
      <strong>{{ item.title }}</strong>
      <span>{{ item.is_read ? '已读' : '未读' }}</span>
      <p>{{ item.body }}</p>
      <button v-if="!item.is_read" type="button" :disabled="loading || marking !== null" @click="markRead(item)">
        {{ marking === item.id ? '核对回执中…' : '标记已读' }}
      </button>
    </article>
    <button v-if="nextBeforeId !== null" type="button" :disabled="loading || marking !== null" @click="refresh(true)">更早通知</button>
  </section>
</template>

<style scoped>
.notification-inbox { display: grid; gap: 0.75rem; padding: 1rem; overflow: auto; }
.notification-inbox header { display: flex; justify-content: space-between; align-items: center; }
.notification-inbox article { padding-block: 0.75rem; border-bottom: 1px solid currentColor; overflow-wrap: anywhere; }
.notification-inbox article span { margin-inline-start: 0.5rem; opacity: 0.8; }
.notification-inbox article p { white-space: pre-wrap; }
</style>
