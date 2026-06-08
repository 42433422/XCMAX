<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, post } from '../api/http'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const marketUserId = computed(() => Number(auth.user?.id || 0))

const loading = ref(false)
const error = ref('')
const requests = ref<Record<string, unknown>[]>([])
const form = ref({
  change_type: 'product_change',
  title: '',
  description: '',
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await get<{ success?: boolean; data?: { requests?: Record<string, unknown>[] } }>(
      '/api/mod/xcagi-customer-service-bridge/user-cs/change-requests',
      { market_user_id: marketUserId.value },
    )
    requests.value = res?.data?.requests || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await post('/api/mod/xcagi-customer-service-bridge/user-cs/change-requests', {
      market_user_id: marketUserId.value,
      username: auth.user?.username || '',
      ...form.value,
    })
    form.value.title = ''
    form.value.description = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page change-requests">
    <h1>需求 / Bug 变更工单</h1>
    <p class="muted">签约后可在本页提交产品变更或 Bug，工单将进入内部客服与 OPS 派发队列。</p>
    <form class="cr-form" @submit.prevent="submit">
      <label>
        类型
        <select v-model="form.change_type">
          <option value="product_change">产品需求变更</option>
          <option value="bug">Bug 反馈</option>
          <option value="feature">功能修改</option>
        </select>
      </label>
      <label>
        标题
        <input v-model="form.title" required maxlength="256" />
      </label>
      <label>
        说明
        <textarea v-model="form.description" rows="4" maxlength="8000" />
      </label>
      <button type="submit" class="btn btn-primary" :disabled="loading">提交工单</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <ul v-if="requests.length" class="cr-list">
      <li v-for="r in requests" :key="String(r.id)">
        <strong>{{ r.ticket_no }}</strong> — {{ r.title }}
        <span class="muted">（{{ r.status }}）</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.change-requests { padding: 24px; max-width: 720px; }
.cr-form { display: flex; flex-direction: column; gap: 12px; margin: 16px 0; }
.cr-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.cr-list { list-style: none; padding: 0; }
.cr-list li { padding: 8px 0; border-bottom: 1px solid var(--border, #333); }
.error { color: #f85149; }
.muted { color: var(--muted, #888); font-size: 13px; }
</style>
