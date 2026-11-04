<template>
  <section class="mac-control" aria-label="Mac 主控协同">
    <header><div><h3>Mac 主控 · {{ fleet?.devices.length || 0 }} 台设备</h3><p>服务器保存任务与回执，Mac 主控编排执行。</p></div><button :disabled="loading" @click="refresh">刷新</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="fleet">{{ fleet.enabled ? '已启用' : '尚未启用新派工' }} · {{ fleet.freshness === 'fresh' && !fleet.error ? '数据已同步' : '数据缺失或过期，等待同步' }} · {{ stamp(fleet.observed_at) }}</p>
    <p v-if="fleet?.error">连接状态：{{ fleet.error }}</p>
    <div class="devices">
      <article v-for="device in fleet?.devices || []" :key="device.id">
        <strong>{{ deviceTitle(device) }}</strong><span>{{ fleet?.freshness !== 'fresh' || fleet?.error ? '状态待核实' : deviceLabel(device.status) }}{{ device.id === fleet?.primary_device_id ? ' · 主设备' : '' }}</span>
        <small>设备 ID：{{ device.id }} · 最后心跳：{{ device.last_seen || '未提供' }}</small>
        <small v-for="tool in device.tools" :key="tool.toolName">{{ tool.toolName }}：{{ toolLabel(device, tool) }}</small>
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
    <ul class="tasks"><li v-for="task in tasks" :key="task.id"><button @click="inspect(task.id)">{{ promptPreview(task.request.message) }}</button><span>{{ label(task.state) }} · {{ stamp(task.updated_at) }}</span><small v-if="task.reason" :title="task.reason">{{ reasonText(task.reason) }}</small><details><summary>查看完整任务提示词</summary><pre>{{ task.request.message }}</pre></details></li></ul>
    <article v-if="selected" class="detail">
      <details><summary>{{ promptPreview(selected.request.message) }}</summary><pre>{{ selected.request.message }}</pre></details><p>任务 {{ selected.id }} · Para {{ selected.para_task_id || '尚未派发' }} · 执行：{{ label(selected.state) }} · 客户验收：待业务回执核对</p>
      <p v-if="selected.request.parent_task_id">上游任务 <button @click="inspect(selected.request.parent_task_id!)">{{ selected.request.parent_task_id }}</button> · 提交 {{ selected.request.source_sha }} · 源码包摘要 {{ selected.request.source_archive_sha256 }}</p>
      <section v-if="selected.delivery_trace"><h4>交付阶段与来源</h4><p>采集时间：{{ stamp(selected.delivery_trace.observed_at) }} · {{ selected.delivery_trace.freshness === 'fresh' ? '来源已核对' : '部分证据缺失或待核实' }}</p><p v-if="selected.delivery_trace.error">来源读取：{{ selected.delivery_trace.error }}</p><p v-if="selected.delivery_trace.source_commit">源码提交 {{ selected.delivery_trace.source_commit }} · 源码包摘要 {{ selected.delivery_trace.source_archive_sha256 || '未提供' }}</p><p v-if="selected.delivery_trace.runtime">运行提交 {{ selected.delivery_trace.runtime.git_sha || '未提供' }} · 发布身份 {{ selected.delivery_trace.runtime.release_id || '未提供' }} · 产物摘要 {{ selected.delivery_trace.runtime.artifact_sha256 || '未提供' }}</p><a v-if="selected.delivery_trace.pull_request" :href="selected.delivery_trace.pull_request.url" target="_blank" rel="noopener noreferrer">PR #{{ selected.delivery_trace.pull_request.number }}</a><p v-for="phase in selected.delivery_trace.stages" :key="phase.name">{{ phaseName(phase.name) }}：{{ phaseState(phase.state) }}<small> · 来源 {{ phase.source || '尚无证据' }} · {{ phase.reference }}</small></p></section>
      <p v-for="sub in selected.execution.subtasks || []" :key="sub.id">{{ sub.device_name }} · {{ statusLabel(sub.status) }}</p>
      <section v-if="selected.execution.reports?.length"><h4>执行器答复与证据</h4><details v-for="report in selected.execution.reports.filter(r => r.report)" :key="report.event_id"><summary>{{ report.received_at }} · {{ report.applied ? '当前尝试' : '历史回执' }}</summary><pre class="report">{{ report.report }}</pre></details></section>
      <section v-if="selected.facts"><h4>客户工单事实</h4><p>读取时间：{{ stamp(selected.facts.observed_at) }}</p><article v-for="ticket in selected.facts.tickets" :key="ticket.id"><p v-if="ticket.error">工单 {{ ticket.id }}：证据读取失败，状态待核实。</p><p v-else>{{ ticket.title }} · 工单：{{ statusLabel(ticket.status) }} · 交付阶段：{{ ticket.resolution.state || '待核对' }} · 安装回执 {{ ticket.receipt_counts.install_receipts }} 条</p><p v-if="!ticket.error && ticket.delivery_verification">客户验收：{{ ticket.delivery_verification.customer_acceptance === 'accepted' ? '已确认' : '待确认' }} · 运行与业务证据：{{ ticket.delivery_verification.runtime_business_verified ? '已核验' : '尚未齐全' }} · 交付：{{ ticket.delivery_verification.completed ? '业务系统已完成交付' : '尚未完成闭环' }}</p><small v-for="receipt in ticket.delivery_verification?.receipts || []" :key="receipt.receipt_id">回执 {{ receipt.receipt_id }} · {{ receipt.stage }} · 版本 {{ receipt.version }} · 宿主提交 {{ receipt.host_sha || '未提供' }}</small></article></section>
      <details><summary>任务事件（{{ events.length }}）</summary><ol><li v-for="event in events" :key="event.id">{{ stamp(event.created_at) }} · {{ label(event.state) }}</li></ol></details><button v-if="!['execution_completed', 'failed', 'cancelled'].includes(selected.state)" @click="cancel">请求取消</button>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { statusLabel } from '../../utils/statusLabel'
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
const duplicateDeviceNames = computed(() => new Set((fleet.value?.devices || []).map(device => device.name).filter(name => (fleet.value?.devices || []).filter(device => device.name === name).length > 1)))
function deviceTitle(device: Fleet['devices'][number]) { return `${device.name || '未命名设备'}${duplicateDeviceNames.value.has(device.name) ? ` · ${device.id}` : ''}` }
function promptPreview(value: string) { const text = String(value || '').trim(); return text.length > 120 ? `${text.slice(0, 120)}…` : text }
function stamp(value: number | null) { return value ? new Date(value * 1000).toLocaleString() : '尚无观测' }
function label(state: string) { return ({ queued: '已受理', dispatching: '正在派发', running: '执行中', waiting_device: '等待设备或工具就绪', reconciling: '结果待核对', execution_completed: '执行完成，交付另行验收', failed: '执行失败', cancel_requested: '取消中，等待执行器确认', cancelled: '已取消', delivery_evidence_updated: '交付证据已更新' } as Record<string, string>)[state] || state }
function phaseName(name: string) { return ({ code: '代码提交', tests: 'CI 测试', approval: '代码审核', merged: '主线合并', deployed: '生产部署', installed: '客户安装', business: '客户业务验收' } as Record<string, string>)[name] || name }
function phaseState(state: string) { return ({ recorded: '已有执行器源码回执', passed: '检查通过', failed: '检查失败', pending: '等待中', approved: '已有审核通过记录', changes_requested: '审核要求修改', not_recorded: '尚无独立审核记录', verified: '来源已核验', receipt_received: '已收到回执，仍待核验', version_or_artifact_unverified: '运行版本或产物尚未对应', unknown: '待核实' } as Record<string, string>)[state] || state }
function deviceLabel(state: string) { return ({ online: '在线', offline: '离线', stale: '状态已过期', idle: '空闲', running: '执行中', not_installed: '未安装', unknown: '待核实' } as Record<string, string>)[state] || state }
function toolLabel(device: Fleet['devices'][number], tool: Fleet['devices'][number]['tools'][number]) {
  const reported = `${deviceLabel(tool.status)} ${tool.currentTask || ''}`.trim()
  return device.status === 'online' && fleet.value?.freshness === 'fresh' && !fleet.value.error ? reported : `上次上报：${reported}；当前执行情况待核实`
}
function reasonText(reason: string) { return reason === 'dispatch_outcome_unknown_no_automatic_resubmit' ? '派发结果尚未核实，系统不会自动重复派发；请核对原任务回执。' : reason }
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
.mac-control { padding: 18px 20px; margin: 16px 0 0; border: 1px solid; color: #172033; font-size: 13px; }
header { display: flex; gap: 12px; justify-content: space-between; align-items: center; margin-bottom: 8px; }
header h3 { margin: 0; font-size: 15px; font-weight: 700; }
header p, .mac-control > p { margin: 4px 0 0; color: #64748b; line-height: 1.6; }
form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: end; margin-top: 12px; }
form label:first-child { grid-column: 1 / -1; }
form button { justify-self: start; }
.devices { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 14px 0; }
.devices article, .detail { min-width: 0; overflow-wrap: anywhere; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #f8fafc; }
.devices strong { font-size: 14px; }
small, .devices span, label { display: block; margin-top: 5px; }
small { color: #64748b; }
label { color: #475569; font-weight: 600; }
textarea { display: block; box-sizing: border-box; min-height: 90px; width: 100%; resize: vertical; padding: 10px 12px; margin-top: 6px; }
input, select, textarea { border: 1px solid #d0d7e2; border-radius: 10px; background: #fff; color: inherit; font: inherit; font-weight: 400; }
input:focus, select:focus, textarea:focus { outline: none; border-color: #1677ff; box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.15); }
input { display: block; width: 100%; padding: 8px 10px; max-width: 100%; box-sizing: border-box; margin-top: 6px; }
select { display: block; width: 100%; margin-top: 6px; }
input[type="checkbox"] { display: inline-block; width: auto; margin: 0 6px 0 0; vertical-align: middle; }
@media (max-width: 700px) { form { grid-template-columns: 1fr; } }
button, select { padding: 8px 14px; cursor: pointer; }
button { border: 1px solid #d0d7e2; border-radius: 10px; background: #fff; color: #0f6fc6; font: inherit; font-weight: 600; }
button:hover:not(:disabled) { border-color: #1677ff; color: #1677ff; }
form > button { border-color: #1677ff; background: #1677ff; color: #fff; }
form > button:hover:not(:disabled) { background: #0f6fc6; color: #fff; }
button:disabled { opacity: .55; cursor: default; }
.tasks { padding-left: 20px; } .tasks li { margin: 10px 0; overflow-wrap: anywhere; } .tasks span { margin-left: 10px; color: #64748b; }
.tasks button { padding: 4px 10px; text-align: left; }
[role=alert] { color: #b42318; }
.report { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
</style>
