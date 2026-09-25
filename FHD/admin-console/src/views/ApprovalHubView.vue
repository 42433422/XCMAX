<template>
  <main class="approval-hub-view" id="view-autonomy-approval-hub">
    <header class="page-header">
      <div><h2>产品问题工单审批</h2><p>共享 Work Order 与完整闸门时间线；每 30 秒刷新</p></div>
      <div class="header-actions">
        <span v-if="updatedAt" class="updated-at">更新于 {{ formatTime(updatedAt) }}</span>
        <button class="btn btn-secondary" :disabled="loading" @click="refresh">{{ loading ? '刷新中…' : '刷新工单' }}</button>
      </div>
    </header>
    <p v-if="error" class="banner-error">工单刷新失败：{{ error }}</p>
    <section v-if="!orders.length && !error" class="panel empty">当前没有共享工单</section>
    <section v-for="item in orders" :key="item.wo_id" class="panel work-order">
      <header class="panel-head"><h3>{{ item.wo_id }}</h3><span class="risk">{{ item.status }}</span></header>
      <dl class="facts">
        <dt>客户 / 租户</dt><dd>{{ item.context?.customer_user_id || item.context?.tenant_id || '—' }}</dd>
        <dt>客户实例</dt><dd>{{ item.context?.client_instance_id || '—' }}</dd>
        <dt>版本 / Git SHA</dt><dd>{{ item.context?.product_version || '—' }} · {{ item.context?.git_sha || '—' }}</dd>
        <dt>平台</dt><dd>{{ item.context?.platform || '—' }}</dd>
        <dt>客户问题 / 实际</dt><dd>{{ item.context?.actual || item.reason || '—' }}</dd>
        <dt>预期</dt><dd>{{ item.context?.expected || '—' }}</dd>
        <dt>支持包 SHA256</dt><dd>{{ item.context?.support_bundle_sha256 || '—' }}</dd>
        <dt>闸门</dt><dd>{{ Object.entries(item.gates || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '暂无收据' }}</dd>
      </dl>
      <details><summary>工单证据、诊断、PR、CI 与时间线</summary><pre class="payload">{{ pretty(item) }}</pre></details>
      <div v-if="item.can_decide" class="drawer-actions">
        <button class="btn btn-primary" :disabled="acting" @click="decide(item, 'approved')">批准</button>
        <button class="btn btn-danger" :disabled="acting" @click="decide(item, 'rejected')">拒绝</button>
        <button class="btn btn-secondary" :disabled="acting" @click="decide(item, 'held')">暂缓</button>
      </div>
      <p v-else class="muted">决策锁定：必须同一工单已有 RED、GREEN 和 OWNER_INSTANCE_VERIFIED 收据。</p>
    </section>
  </main>
</template>

<script lang="ts">
export default { name: 'ApprovalHubView' }
</script>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { xcmaxAdminApi, type OwnerWorkOrder } from '@/api/xcmaxAdmin'
import { appAlert, appPrompt } from '@/utils/appDialog'

const orders = ref<OwnerWorkOrder[]>([])
const loading = ref(false)
const acting = ref(false)
const error = ref('')
const updatedAt = ref('')
let timer: ReturnType<typeof setInterval> | undefined

function formatTime(value: unknown) {
  const date = new Date(String(value || ''))
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

function pretty(value: unknown) {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return String(value ?? '') }
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const result = await xcmaxAdminApi.fetchOwnerWorkOrders()
    orders.value = Array.isArray(result.items) ? result.items : []
    error.value = ''
    updatedAt.value = new Date().toISOString()
  } catch (cause: unknown) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { loading.value = false }
}

async function decide(item: OwnerWorkOrder, decision: 'approved' | 'rejected' | 'held') {
  if (!item.can_decide || acting.value) return
  const note = decision === 'approved' ? '' : await appPrompt(decision === 'held' ? '暂缓说明（可选）' : '拒绝原因（可选）', '')
  if (note === null) return
  acting.value = true
  try {
    const result = await xcmaxAdminApi.decideOwnerWorkOrder(item.wo_id, decision, note)
    await appAlert(`工单 ${item.wo_id} 已记录为 ${result.decision}，操作人 ${result.actor}`)
    await refresh()
  } catch (cause: unknown) {
    await appAlert(cause instanceof Error ? cause.message : String(cause))
  } finally { acting.value = false }
}

onMounted(() => { void refresh(); timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 30_000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped src="./ApprovalHubView.css"></style>
