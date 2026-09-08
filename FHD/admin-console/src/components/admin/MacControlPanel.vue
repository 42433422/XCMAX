<template>
  <section class="mac-control" aria-label="Mac 主控协同">
    <header><div><h3>Mac 主控 · 四设备协同</h3><p>服务器保存任务与回执，Mac 主控编排执行。</p></div><button :disabled="loading" @click="refresh">刷新</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="fleet">{{ fleet.enabled ? '已启用' : '尚未启用新派工' }} · {{ fleet.freshness === 'fresh' && !fleet.error ? '数据已同步' : '数据缺失或过期，等待同步' }} · {{ stamp(fleet.observed_at) }}</p>
    <p v-if="fleet?.error">连接状态：{{ fleet.error }}</p>
    <div class="devices">
      <article v-for="device in fleet?.devices || []" :key="device.id">
        <strong>{{ device.name }}</strong><span>{{ fleet?.freshness !== 'fresh' ? '状态待核实' : device.status }}{{ device.id === fleet?.primary_device_id ? ' · 主设备' : '' }}</span>
        <small v-for="tool in device.tools" :key="tool.toolName">{{ tool.toolName }}：{{ tool.status }} {{ tool.currentTask || '' }}</small>
      </article>
    </div>
    <form @submit.prevent="submit">
      <label>目标<textarea v-model="draft" :disabled="sending" placeholder="查询项目情况，或描述需要处理的目标" /></label>
      <label>执行设备<select v-model="target"><option value="mac">Mac 主设备</option><option value="windows">Windows 验证设备</option></select></label>
      <label>任务类型<select v-model="mode"><option value="review">只读分析与验证</option><option value="code">开发并推进到现有审批点</option></select></label>
      <button :disabled="sending || !draft.trim() || !fleet?.enabled">{{ sending ? '保存中…' : '交给主控' }}</button>
    </form>
    <p>客户安装与业务验收独立核对；执行器报告完成不等于已交付。</p>
    <ul class="tasks"><li v-for="task in tasks" :key="task.id">
      <button @click="inspect(task.id)">{{ task.request.message }}</button>
      <span>{{ label(task.state) }} · {{ stamp(task.updated_at) }}</span><small v-if="task.reason">{{ task.reason }}</small>
    </li></ul>
    <article v-if="selected" class="detail">
      <h4>{{ selected.request.message }}</h4><p>任务 {{ selected.id }} · Para {{ selected.para_task_id || '尚未派发' }}</p>
      <p>执行：{{ label(selected.state) }} · 客户验收：待业务回执核对</p>
      <p v-for="sub in selected.execution.subtasks || []" :key="sub.id">{{ sub.device_name }} · {{ sub.status }}</p>
      <ol><li v-for="event in events" :key="event.id">{{ stamp(event.created_at) }} · {{ label(event.state) }}</li></ol>
      <button v-if="!['execution_completed', 'failed', 'cancelled'].includes(selected.state)" @click="cancel">请求取消</button>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { cancelTask, readFleet, readTask, readTasks, submitControlTask, type ControlTask, type Fleet } from '@host/api/macControl'

const fleet = ref<Fleet | null>(null)
const tasks = ref<ControlTask[]>([])
const selected = ref<ControlTask | null>(null)
const events = ref<Array<{ id: number; state: string; created_at: number }>>([])
const draft = ref(''), target = ref('mac'), mode = ref('review'), error = ref('')
const loading = ref(false), sending = ref(false)
let pending: { text: string; target: string; mode: string; key: string } | null = null
const pendingStorage = 'xcmax.mac-control.pending'
let timer: ReturnType<typeof setInterval> | undefined
function stamp(value: number | null) { return value ? new Date(value * 1000).toLocaleString() : '尚无观测' }
function label(state: string) { return ({ queued: '已受理', dispatching: '正在派发', running: '执行中', waiting_device: '等待设备或工具就绪', reconciling: '结果待核对', execution_completed: '执行完成，交付另行验收', failed: '执行失败', cancel_requested: '取消中，等待执行器确认', cancelled: '已取消' } as Record<string, string>)[state] || state }
async function refresh() {
  if (loading.value) return
  loading.value = true
  try { const [f, t] = await Promise.all([readFleet(), readTasks()]); fleet.value = f; tasks.value = t.tasks; error.value = ''; if (selected.value) await inspect(selected.value.id) }
  catch (e) { error.value = e instanceof Error ? e.message : '读取失败' }
  finally { loading.value = false }
}
async function inspect(id: string) {
  try { const detail = await readTask(id); selected.value = detail.task; events.value = detail.events }
  catch (e) { error.value = e instanceof Error ? e.message : '读取任务失败' }
}
async function submit() {
  if (sending.value) return
  const text = draft.value.trim()
  if (!pending || pending.text !== text || pending.target !== target.value || pending.mode !== mode.value) pending = { text, target: target.value, mode: mode.value, key: crypto.randomUUID() }
  try { sessionStorage.setItem(pendingStorage, JSON.stringify(pending)) } catch { error.value = '无法保存请求标识，请允许会话存储后重试'; return }
  sending.value = true
  try { const result = await submitControlTask(text, pending.key, pending.target, pending.mode); selected.value = result.task; draft.value = ''; pending = null; sessionStorage.removeItem(pendingStorage); await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '受理结果未知，请重试核对原请求' }
  finally { sending.value = false }
}
async function cancel() { if (!selected.value) return; try { await cancelTask(selected.value.id); await refresh() } catch (e) { error.value = e instanceof Error ? e.message : '取消失败' } }
onMounted(() => {
  try { const saved = JSON.parse(sessionStorage.getItem(pendingStorage) || 'null'); if (saved && typeof saved.key === 'string' && typeof saved.text === 'string') { pending = saved; draft.value = saved.text; target.value = saved.target; mode.value = saved.mode } } catch { /* No automatic resubmission. */ }
  void refresh(); timer = setInterval(() => { void refresh() }, 15000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.mac-control { padding: 20px; margin: 20px 0; border: 1px solid #cbd5e1; border-radius: 12px; background: var(--bg-card, #fff); color: var(--text-primary, #172033); }
header, form { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: center; }
.devices { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 16px 0; }
.devices article, .detail { padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; }
small, .devices span, label { display: block; margin-top: 5px; }
textarea { display: block; min-height: 70px; width: min(500px, 70vw); }
button, select { padding: 7px 12px; cursor: pointer; } button:disabled { opacity: .6; cursor: default; }
.tasks { padding-left: 20px; } .tasks li { margin: 10px 0; overflow-wrap: anywhere; } .tasks span { margin-left: 10px; }
[role=alert] { color: #b91c1c; }
</style>
