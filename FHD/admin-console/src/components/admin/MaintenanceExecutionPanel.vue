<template>
  <section class="maintenance card" aria-label="自治与维护执行">
    <header><div><h3>自治与维护执行</h3></div><button :disabled="loading" @click="load">刷新状态</button></header>
    <p role="status">{{ loading ? '正在读取维护状态…' : connected ? '执行服务已连接' : '执行服务未连接或尚未配置' }} · {{ environment }}</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="actions"><button v-for="task in tasks" :key="task.action" :disabled="busy || !connected" @click="run(task)">申请{{ task.label }}</button></div>
    <p v-if="!loading && !tasks.length">暂无可用维护任务。</p>
    <h4>待审批</h4>
    <p v-if="!pending.length">{{ connected ? '当前没有待审批维护任务。' : '待审批状态尚未核实。' }}</p>
    <div v-for="item in pending" :key="item.action_id" class="approval">
      <span>{{ item.label }} · 等待管理员处理</span>
      <button :disabled="busy" @click="review(item.action_id, 'resume')">批准并执行</button>
      <button :disabled="busy" @click="review(item.action_id, 'reject')">拒绝</button>
    </div>
    <h4>执行记录</h4>
    <table v-if="executions.length"><thead><tr><th>任务</th><th>执行状态</th><th>开始时间</th><th>恢复结果</th><th>操作</th></tr></thead>
      <tbody><tr v-for="row in executions" :key="row.id"><td>{{ row.label }}<small>编号 {{ row.id }}</small></td><td>{{ statusLabel(row.status) }}</td><td>{{ row.started_at || '未提供' }}</td><td>{{ row.recovery === 'verified' ? '已核实恢复' : '尚未核实' }}</td><td><button v-if="['running', 'scheduled'].includes(row.status)" :disabled="cancelling" @click="cancel(row.id)">取消任务</button><span v-else>—</span></td></tr></tbody>
    </table>
    <p v-else>{{ connected ? '暂无执行记录。' : '执行记录尚未读取成功。' }}</p>
  </section>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import api from '@/api/core'
import { appConfirm } from '@/utils/appDialog'
const prefix = '/api/xcmax/admin/autonomy'
type Task = { action: string; label: string }
type Execution = Task & { id: string; status: string; started_at?: string; recovery: string }
const tasks = ref<Task[]>([]), executions = ref<Execution[]>([])
const pending = ref<Array<{ action_id: string; label: string }>>([])
const connected = ref(false), loading = ref(false), busy = ref(false), cancelling = ref(false)
const environment = ref('环境尚未核实'), error = ref(''), message = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let request = 0
function statusLabel(status: string) { return ({ succeeded: '执行成功', failed: '执行失败', running: '执行中', scheduled: '等待执行', aborted: '已取消', timedout: '执行超时' } as Record<string, string>)[status] || '结果待核实' }
async function load() {
  const current = ++request
  loading.value = true
  try {
    const data = await api.get<{ ok: boolean; connected: boolean; environment: string; tasks: Task[]; executions: Execution[]; pending: Array<{ action_id: string; label: string }> }>(`${prefix}/maintenance`)
    if (current !== request) return
    if (!data.ok || !Array.isArray(data.tasks) || !Array.isArray(data.executions) || !Array.isArray(data.pending)) throw new Error('维护状态返回不完整')
    connected.value = data.connected; environment.value = data.environment
    tasks.value = data.tasks; executions.value = data.executions; pending.value = data.pending; error.value = ''
  } catch (cause) {
    if (current !== request) return
    connected.value = false; tasks.value = []; executions.value = []; pending.value = []
    error.value = cause instanceof Error ? cause.message : '维护状态读取失败，请重新读取。'
  } finally { if (current === request) loading.value = false }
}
async function mutate(path: string, body: Record<string, unknown>, confirmation: string) {
  const isCancel = path.endsWith('/cancel')
  if ((isCancel ? cancelling.value : busy.value) || !await appConfirm(confirmation)) return
  if (isCancel) cancelling.value = true; else busy.value = true; error.value = ''; message.value = ''
  try {
    const result = await api.post<{ ok: boolean; state?: string }>(`${prefix}/${path}`, body)
    if (!result.ok) throw new Error('操作未确认成功，请刷新查看真实状态。')
    message.value = result.state === 'pending_approval' ? '已提交审批，尚未执行。' : result.state === 'execution_failed' ? '执行未成功，请查看任务记录。' : result.state === 'cancel_requested' ? '已请求取消，最终状态以任务记录为准。' : '处理已返回，请查看执行记录和恢复结果。'
    await load()
  } catch (cause) { error.value = `${cause instanceof Error ? cause.message : '操作结果未确认'}；请刷新核对，避免重复申请。` }
  finally { if (isCancel) cancelling.value = false; else busy.value = false }
}
function run(task: Task) { return mutate('maintenance/run', { action: task.action, request_id: crypto.randomUUID() }, `申请${task.label}？该动作将经过风险检查，需要审批时会进入待办。`) }
function review(id: string, action: string) { return mutate(`actions/${encodeURIComponent(id)}/${action}`, { reason: '管理端拒绝维护申请' }, action === 'resume' ? '批准并执行此维护任务？' : '拒绝此维护申请？') }
function cancel(id: string) { return mutate(`maintenance/${encodeURIComponent(id)}/cancel`, {}, '请求取消此任务？已经发生的操作不会自动撤销。') }
onMounted(() => { void load(); timer = setInterval(() => { if (!loading.value) void load() }, 10000) })
onUnmounted(() => { ++request; if (timer) clearInterval(timer) })
</script>
<style scoped>
.maintenance { padding: 20px; border: 1px solid var(--admin-border, #dce3ed); border-radius: 12px; }
header,.actions,.approval { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
h3 { margin:0; font-size:18px; } p,small { color:var(--admin-muted,#64748b); } small { display:block; }
.actions { justify-content:flex-start; } button { padding:8px 14px; border:1px solid #cbd5e1; border-radius:7px; background:var(--admin-card-bg,#fff); color:inherit; cursor:pointer; } button:disabled { opacity:.5; cursor:not-allowed; }
table { width:100%; border-collapse:collapse; } th,td { text-align:left; padding:12px 8px; border-bottom:1px solid #e2e8f0; } .error { color:#b42318; } .approval { padding:12px 0; }
</style>
