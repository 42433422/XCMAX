<template>
  <section class="mac-control" aria-label="Mac 主控协同">
    <header><div><h3>Mac 主控 · 四设备协同</h3><p>服务器保存任务与回执，Mac 主控编排执行。</p></div><button :disabled="loading" @click="refresh">刷新</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="fleet">{{ fleet.enabled ? '已启用' : '尚未启用新派工' }} · {{ fleet.freshness === 'fresh' && !fleet.error ? '数据已同步' : '数据缺失或过期，等待同步' }} · {{ stamp(fleet.observed_at) }}</p>
    <p v-if="fleet?.error">连接状态：{{ fleet.error }}</p>
    <div class="devices">
      <article v-for="device in fleet?.devices || []" :key="device.id">
        <strong>{{ device.name }}</strong><span>{{ fleet?.freshness !== 'fresh' ? '状态待核实' : deviceLabel(device.status) }}{{ device.id === fleet?.primary_device_id ? ' · 主设备' : '' }}</span>
        <small>设备 ID：{{ device.id }} · 最后心跳：{{ device.last_seen || '未提供' }}</small>
        <small v-for="tool in device.tools" :key="tool.toolName">{{ tool.toolName }}：{{ deviceLabel(tool.status) }} {{ tool.currentTask || '' }}</small>
      </article>
    </div>
    <form @submit.prevent="submit">
      <label>目标<textarea v-model="draft" :disabled="sending" placeholder="查询项目情况，或描述需要处理的目标" /></label>
      <label>执行设备<select v-model="target"><option value="mac">Mac 主设备</option><option value="windows">Windows 验证设备</option></select></label>
      <label>任务类型<select v-model="mode"><option value="review">只读分析与验证</option><option value="code">开发并推进到现有审批点</option></select></label>
      <label>关联工单（可选）<input v-model="ticketId" type="number" min="1" /></label>
      <label v-if="target === 'mac' && mode === 'code'"><input v-model="verifyWindows" type="checkbox" />代码推送后交给 Windows 验证同一提交</label>
      <button :disabled="sending || !draft.trim() || !fleet?.enabled">{{ sending ? '保存中…' : '交给主控' }}</button>
    </form>
    <p>客户安装与业务验收独立核对；执行器报告完成不等于已交付。</p>
    <ul class="tasks"><li v-for="task in tasks" :key="task.id">
      <button @click="inspect(task.id)">{{ task.request.message }}</button>
      <span>{{ label(task.state) }} · {{ stamp(task.updated_at) }}</span><small v-if="task.reason">{{ task.reason }}</small>
    </li></ul>
    <article v-if="selected" class="detail">
      <h4>{{ selected.request.message }}</h4><p>任务 {{ selected.id }} · Para {{ selected.para_task_id || '尚未派发' }}</p>
      <p v-if="selected.request.parent_task_id">上游任务 <button @click="inspect(selected.request.parent_task_id!)">{{ selected.request.parent_task_id }}</button> · 提交 {{ selected.request.source_sha }} · 源码包摘要 {{ selected.request.source_archive_sha256 }}</p>
      <p>执行：{{ label(selected.state) }} · 客户验收：待业务回执核对</p>
      <p v-for="sub in selected.execution.subtasks || []" :key="sub.id">{{ sub.device_name }} · {{ sub.status }}</p>
      <section v-if="selected.execution.reports?.length"><h4>执行器答复与证据</h4><article v-for="report in selected.execution.reports.filter(r => r.report)" :key="report.event_id"><small>来源：Para 设备回写 · {{ report.received_at }} · {{ report.applied ? '已记录为当前尝试结果' : '历史回执，未推进状态' }}</small><pre class="report">{{ report.report }}</pre></article></section>
      <section v-if="selected.facts"><h4>客户工单事实</h4><p>读取时间：{{ stamp(selected.facts.observed_at) }}</p><article v-for="ticket in selected.facts.tickets" :key="ticket.id"><p>{{ ticket.title }} · 工单：{{ ticket.status }} · 交付阶段：{{ ticket.resolution.state || '待核对' }} · 安装回执 {{ ticket.receipt_counts.install_receipts }} 条</p><p v-if="ticket.delivery_verification">客户验收：{{ ticket.delivery_verification.customer_acceptance === 'accepted' ? '已确认' : '待确认' }} · 运行与业务证据：{{ ticket.delivery_verification.runtime_business_verified ? '已核验' : '尚未齐全' }} · 交付：{{ ticket.delivery_verification.completed ? '业务系统已完成交付' : '尚未完成闭环' }}</p><small v-for="receipt in ticket.delivery_verification?.receipts || []" :key="receipt.receipt_id">回执 {{ receipt.receipt_id }} · {{ receipt.stage }} · 版本 {{ receipt.version }} · 宿主提交 {{ receipt.host_sha || '未提供' }}</small></article></section>
      <ol><li v-for="event in events" :key="event.id">{{ stamp(event.created_at) }} · {{ label(event.state) }}</li></ol>
      <button v-if="!['execution_completed', 'failed', 'cancelled'].includes(selected.state)" @click="cancel">请求取消</button>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { cancelTask, readFleet, readTask, readTasks, submitControlTask, type ControlTask, type Fleet } from '../../../../frontend/src/api/macControl'

const fleet = ref<Fleet | null>(null)
const tasks = ref<ControlTask[]>([])
const selected = ref<ControlTask | null>(null)
const events = ref<Array<{ id: number; state: string; created_at: number }>>([])
const draft = ref(''), target = ref('mac'), mode = ref('review'), error = ref('')
const ticketId = ref('')
const verifyWindows = ref(false)
const loading = ref(false), sending = ref(false)
let pending: { text: string; target: string; mode: string; key: string; ticketId?: number; verifyWindows?: boolean } | null = null
const pendingStorage = 'xcmax.mac-control.pending'
let timer: ReturnType<typeof setInterval> | undefined
let detailRequest = 0
function stamp(value: number | null) { return value ? new Date(value * 1000).toLocaleString() : '尚无观测' }
function label(state: string) { return ({ queued: '已受理', dispatching: '正在派发', running: '执行中', waiting_device: '等待设备或工具就绪', reconciling: '结果待核对', execution_completed: '执行完成，交付另行验收', failed: '执行失败', cancel_requested: '取消中，等待执行器确认', cancelled: '已取消' } as Record<string, string>)[state] || state }
function deviceLabel(state: string) { return ({ online: '在线', offline: '离线', stale: '状态已过期', idle: '空闲', running: '执行中', not_installed: '未安装', unknown: '待核实' } as Record<string, string>)[state] || state }
async function refresh() {
  if (loading.value) return
  loading.value = true
  try { const [f, t] = await Promise.all([readFleet(), readTasks()]); fleet.value = f; tasks.value = t.tasks; error.value = ''; if (selected.value) await inspect(selected.value.id) }
  catch (e) { error.value = e instanceof Error ? e.message : '读取失败' }
  finally { loading.value = false }
}
async function inspect(id: string) {
  const request = ++detailRequest
  let accumulated = selected.value?.id === id ? [...events.value] : []
  try {
    for (let page = 0; page < 5; page++) {
      const after = accumulated.at(-1)?.id || 0
      const detail = await readTask(id, after)
      if (request !== detailRequest) return
      selected.value = detail.task
      const known = new Set(accumulated.map(event => event.id))
      accumulated = [...accumulated, ...detail.events.filter(event => !known.has(event.id))]
      events.value = accumulated
      if (detail.events.length < 200 || accumulated.at(-1)?.id === after) break
    }
  }
  catch (e) { if (request === detailRequest) error.value = e instanceof Error ? e.message : '读取任务失败' }
}
async function submit() {
  if (sending.value) return
  const text = draft.value.trim()
  const ticket = ticketId.value ? Number(ticketId.value) : undefined
  const verify = verifyWindows.value && target.value === 'mac' && mode.value === 'code'
  if (!pending || pending.text !== text || pending.target !== target.value || pending.mode !== mode.value || pending.ticketId !== ticket || Boolean(pending.verifyWindows) !== verify) pending = { text, target: target.value, mode: mode.value, key: crypto.randomUUID(), ticketId: ticket, verifyWindows: verify }
  try { sessionStorage.setItem(pendingStorage, JSON.stringify(pending)) } catch { error.value = '无法保存请求标识，请允许会话存储后重试'; return }
  sending.value = true
  try { const result = await submitControlTask(text, pending.key, pending.target, pending.mode, pending.ticketId, pending.verifyWindows); detailRequest++; events.value = []; selected.value = result.task; draft.value = ''; pending = null; sessionStorage.removeItem(pendingStorage); await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '受理结果未知，请重试核对原请求' }
  finally { sending.value = false }
}
async function cancel() { if (!selected.value) return; try { await cancelTask(selected.value.id); await refresh() } catch (e) { error.value = e instanceof Error ? e.message : '取消失败' } }
onMounted(() => {
  try { const saved = JSON.parse(sessionStorage.getItem(pendingStorage) || 'null'); if (saved && typeof saved.key === 'string' && typeof saved.text === 'string') { pending = saved; draft.value = saved.text; target.value = saved.target; mode.value = saved.mode; ticketId.value = saved.ticketId ? String(saved.ticketId) : ''; verifyWindows.value = saved.verifyWindows === true } } catch { /* No automatic resubmission. */ }
  void refresh(); timer = setInterval(() => { void refresh() }, 15000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.mac-control { padding: 20px; margin: 20px 0; border: 1px solid #cbd5e1; border-radius: 12px; background: var(--bg-card, #fff); color: var(--text-primary, #172033); }
header { display: flex; gap: 12px; justify-content: space-between; align-items: center; }
form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: end; }
form label:first-child { grid-column: 1 / -1; }
form button { justify-self: start; }
.devices { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 16px 0; }
.devices article, .detail { padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; }
small, .devices span, label { display: block; margin-top: 5px; }
textarea { display: block; box-sizing: border-box; min-height: 90px; width: 100%; resize: vertical; padding: 10px; }
input, select, textarea { border: 1px solid #cbd5e1; border-radius: 6px; background: inherit; color: inherit; }
input { padding: 7px; max-width: 100%; box-sizing: border-box; }
@media (max-width: 700px) { form { grid-template-columns: 1fr; } }
button, select { padding: 7px 12px; cursor: pointer; } button:disabled { opacity: .6; cursor: default; }
.tasks { padding-left: 20px; } .tasks li { margin: 10px 0; overflow-wrap: anywhere; } .tasks span { margin-left: 10px; }
[role=alert] { color: #b91c1c; }
.report { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
</style>
