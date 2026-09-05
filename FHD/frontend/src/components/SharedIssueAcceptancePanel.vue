<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

interface Repair { id: number; ticket_no: string; summary: string; ready: boolean }
const account = useAccountProfileStore()
const repairs = ref<Repair[]>([])
const notes = ref<Record<number, string>>({})
const error = ref('')
const busy = ref<number | null>(null)
let generation = 0
let pending: AbortController | undefined

async function refresh() {
  const current = ++generation
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  repairs.value = []
  notes.value = {}
  busy.value = null
  error.value = ''
  if (account.marketUserId === null) return
  try {
    const response = await apiFetch('/api/mod-store/issue-runtime', { signal: controller.signal })
    if (response.status === 401) return
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error('修复交付状态暂时无法同步，请重试')
    if (current === generation) repairs.value = Array.isArray(body.data?.items) ? body.data.items : []
  } catch (cause) {
    if (current === generation && !controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '修复交付状态暂时无法同步'
  }
}

async function confirm(repair: Repair) {
  const note = (notes.value[repair.id] || '').trim()
  if (!repair.ready || note.length < 4 || busy.value !== null) return
  const current = generation
  busy.value = repair.id
  error.value = ''
  try {
    const response = await apiFetch(`/api/mod-store/issue-runtime/${repair.id}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: true, note }), signal: pending?.signal,
    })
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : '确认未成功保存，请重试')
    if (current === generation) await refresh()
  } catch (cause) {
    if (current === generation && !pending?.signal.aborted) error.value = cause instanceof Error ? cause.message : '确认未成功保存'
  } finally {
    if (current === generation) busy.value = null
  }
}

watch(() => [account.tenantId, account.marketUserId, account.localUserId, account.impersonatingMarketUserId], refresh, { immediate: true })
onBeforeUnmount(() => { generation++; pending?.abort() })
</script>

<template>
  <section v-if="repairs.length || error" class="repair-acceptance" aria-label="问题修复交付">
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="refresh">重试</button></p>
    <article v-for="repair in repairs" :key="repair.id">
      <strong>{{ repair.ticket_no }} · {{ repair.summary }}</strong>
      <template v-if="repair.ready">
        <p>修复已到达当前客户端，请按原来的操作验证是否恢复。</p>
        <label :for="`repair-result-${repair.id}`">使用结果</label>
        <input :id="`repair-result-${repair.id}`" v-model="notes[repair.id]" maxlength="2000" placeholder="例如：现在可以正常保存订单了" />
        <button type="button" :disabled="busy !== null || (notes[repair.id] || '').trim().length < 4" @click="confirm(repair)">
          {{ busy === repair.id ? '正在保存…' : '确认原问题已解决' }}
        </button>
      </template>
      <p v-else>修复尚未到达当前客户端，工单将继续跟进交付。</p>
    </article>
  </section>
</template>

<style scoped>
.repair-acceptance { padding: 16px 24px; border-bottom: 1px solid var(--border-color, #ddd); max-height: 40vh; overflow: auto; }
article + article { margin-top: 16px; }
p { margin: 8px 0; }
input { margin: 0 12px; padding: 8px; min-width: 240px; max-width: 100%; }
button { padding: 8px 12px; cursor: pointer; }
button:disabled { cursor: default; opacity: .6; }
</style>
