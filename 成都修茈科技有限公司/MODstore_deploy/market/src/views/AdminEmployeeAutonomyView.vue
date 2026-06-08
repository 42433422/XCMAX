<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const info = ref('')

const dashboard = ref<Record<string, any>>({})
const suggestions = ref<Array<Record<string, any>>>([])
const briefTasks = ref<Array<Record<string, any>>>([])
const threads = ref<Array<Record<string, any>>>([])
const messages = ref<Array<Record<string, any>>>([])

const suggestionStatus = ref('pending')
const selectedSuggestionIds = ref<number[]>([])

const selectedThreadId = ref<number>(0)
const messageDraft = ref('')
const newThreadTitle = ref('')
const newThreadParticipants = ref('')

function toggleSuggestion(id: number) {
  if (selectedSuggestionIds.value.includes(id)) {
    selectedSuggestionIds.value = selectedSuggestionIds.value.filter((x) => x !== id)
  } else {
    selectedSuggestionIds.value = [...selectedSuggestionIds.value, id]
  }
}

async function loadDashboard() {
  dashboard.value = (await api.adminEmployeeAutonomyDashboard(40)) as Record<string, any>
}

async function loadSuggestions() {
  const r = (await api.adminEmployeeSuggestions({
    status: suggestionStatus.value || undefined,
    limit: 120,
    offset: 0,
  })) as { items?: Array<Record<string, any>> }
  suggestions.value = Array.isArray(r?.items) ? r.items : []
  selectedSuggestionIds.value = selectedSuggestionIds.value.filter((id) =>
    suggestions.value.some((s) => Number(s.id) === id),
  )
}

async function loadBriefTasks() {
  const r = (await api.adminEmployeeBriefTasks({
    status: 'pending',
    limit: 120,
  })) as { items?: Array<Record<string, any>> }
  briefTasks.value = Array.isArray(r?.items) ? r.items : []
}

async function loadThreads() {
  const r = (await api.adminEmployeeCollabThreads({ status: 'open', limit: 80 })) as {
    items?: Array<Record<string, any>>
  }
  threads.value = Array.isArray(r?.items) ? r.items : []
  if (!selectedThreadId.value && threads.value.length) {
    selectedThreadId.value = Number(threads.value[0].id || 0)
  }
}

async function loadMessages() {
  if (!selectedThreadId.value) {
    messages.value = []
    return
  }
  const r = (await api.adminEmployeeCollabMessages(selectedThreadId.value, 200)) as {
    items?: Array<Record<string, any>>
  }
  messages.value = Array.isArray(r?.items) ? r.items : []
}

async function loadAll() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  info.value = ''
  try {
    await Promise.all([loadDashboard(), loadSuggestions(), loadBriefTasks(), loadThreads()])
    await loadMessages()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function approveSuggestion(id: number) {
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    await api.adminEmployeeSuggestionApprove(id, true)
    info.value = `建议 #${id} 已批准并分发`
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function rejectSuggestion(id: number) {
  const reason = window.prompt('请输入驳回原因', '') || ''
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    await api.adminEmployeeSuggestionReject(id, reason)
    info.value = `建议 #${id} 已驳回`
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function batchReview(action: 'approve' | 'reject') {
  if (!selectedSuggestionIds.value.length) {
    info.value = '请先勾选建议单'
    return
  }
  const reason =
    action === 'reject' ? window.prompt('请输入批量驳回原因', '') || '(batch reject)' : ''
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    await api.adminEmployeeSuggestionBatchReview({
      ids: selectedSuggestionIds.value,
      action,
      reason,
      dispatch_now: true,
    })
    info.value = `批量${action === 'approve' ? '批准' : '驳回'}完成`
    selectedSuggestionIds.value = []
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function dispatchQueues() {
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    const [a, b] = await Promise.all([
      api.adminEmployeeDispatchBriefTasks(40),
      api.adminEmployeeDispatchSuggestions(40),
    ])
    info.value = `已触发分发：brief=${JSON.stringify(a)} suggestion=${JSON.stringify(b)}`
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function triggerEvolutionScan() {
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    const out = (await api.adminEmployeeEvolutionScan({
      lookback_hours: 24,
      min_failures: 3,
      limit: 30,
    })) as Record<string, any>
    info.value = `进化扫描完成：processed=${out?.processed ?? 0} created=${out?.created ?? 0}`
    await loadDashboard()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function createThread() {
  const title = newThreadTitle.value.trim()
  if (!title) {
    info.value = '请输入线程标题'
    return
  }
  const participants = newThreadParticipants.value
    .split(/[,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    const out = (await api.adminEmployeeCreateCollabThread({
      title,
      participants,
      created_by_employee_id: 'admin',
    })) as Record<string, any>
    selectedThreadId.value = Number(out?.thread_id || 0)
    newThreadTitle.value = ''
    newThreadParticipants.value = ''
    await loadThreads()
    await loadMessages()
    info.value = '协作线程已创建'
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

async function sendMessage() {
  if (!selectedThreadId.value) return
  const content = messageDraft.value.trim()
  if (!content) return
  actionLoading.value = true
  error.value = ''
  info.value = ''
  try {
    await api.adminEmployeePostCollabMessage(selectedThreadId.value, {
      sender_employee_id: 'admin',
      content,
    })
    messageDraft.value = ''
    await loadMessages()
    await loadSuggestions()
    info.value = '消息已发送'
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionLoading.value = false
  }
}

watch(suggestionStatus, () => {
  void loadSuggestions()
})

watch(selectedThreadId, () => {
  void loadMessages()
})

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <div v-if="!isAdmin" class="autonomy-denied">
    <p>需要管理员权限</p>
    <router-link to="/" class="btn">返回</router-link>
  </div>
  <div v-else class="autonomy-page">
    <header class="autonomy-header">
      <h1>员工自治统一面板</h1>
      <div class="autonomy-actions">
        <button type="button" class="btn ghost" :disabled="loading || actionLoading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <button type="button" class="btn ghost" :disabled="loading || actionLoading" @click="dispatchQueues">
          触发待办/建议分发
        </button>
        <button type="button" class="btn ghost" :disabled="loading || actionLoading" @click="triggerEvolutionScan">
          运行进化扫描
        </button>
        <router-link :to="{ name: 'admin-duty-employees' }" class="btn ghost">返回值班图</router-link>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="info" class="info">{{ info }}</p>

    <section class="panel">
      <h2>闭环总览</h2>
      <div class="stats">
        <div class="stat"><span>待审 CR</span><strong>{{ dashboard?.counts?.change_requests_pending ?? 0 }}</strong></div>
        <div class="stat"><span>待审建议</span><strong>{{ dashboard?.counts?.suggestions_pending ?? 0 }}</strong></div>
        <div class="stat"><span>待办任务</span><strong>{{ dashboard?.counts?.brief_tasks_pending ?? 0 }}</strong></div>
        <div class="stat"><span>协作线程</span><strong>{{ dashboard?.counts?.collab_threads_open ?? 0 }}</strong></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title-row">
        <h2>建议单</h2>
        <div class="panel-actions">
          <label>
            状态
            <select v-model="suggestionStatus">
              <option value="">全部</option>
              <option value="pending">pending</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="done">done</option>
              <option value="dispatched">dispatched</option>
            </select>
          </label>
          <button type="button" class="btn ghost" :disabled="actionLoading" @click="batchReview('approve')">批量批准</button>
          <button type="button" class="btn ghost" :disabled="actionLoading" @click="batchReview('reject')">批量驳回</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th />
              <th>ID</th>
              <th>来源</th>
              <th>目标</th>
              <th>类型</th>
              <th>风险</th>
              <th>状态</th>
              <th>摘要</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in suggestions" :key="s.id">
              <td>
                <input
                  type="checkbox"
                  :checked="selectedSuggestionIds.includes(Number(s.id))"
                  @change="toggleSuggestion(Number(s.id))"
                >
              </td>
              <td>{{ s.id }}</td>
              <td><code>{{ s.source_employee_id }}</code></td>
              <td class="mono">{{ (s.target_employee_ids || []).join(', ') }}</td>
              <td>{{ s.kind }}</td>
              <td>{{ s.risk_level }}</td>
              <td>{{ s.status }}</td>
              <td class="summary">{{ (s.summary || '').slice(0, 80) }}</td>
              <td>
                <button
                  v-if="s.status === 'pending'"
                  type="button"
                  class="btn link"
                  :disabled="actionLoading"
                  @click="approveSuggestion(Number(s.id))"
                >批准</button>
                <button
                  v-if="s.status === 'pending'"
                  type="button"
                  class="btn link"
                  :disabled="actionLoading"
                  @click="rejectSuggestion(Number(s.id))"
                >驳回</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !suggestions.length" class="muted">暂无建议单</p>
      </div>
    </section>

    <section class="panel">
      <h2>待办任务（pending）</h2>
      <ul class="list">
        <li v-for="t in briefTasks" :key="t.id">
          <code>#{{ t.id }}</code>
          <span class="mono">{{ t.owner_employee_id }}</span>
          <span>{{ t.task_brief }}</span>
        </li>
      </ul>
      <p v-if="!loading && !briefTasks.length" class="muted">暂无待办</p>
    </section>

    <section class="panel panel-collab">
      <div class="thread-col">
        <h2>协作线程</h2>
        <div class="thread-create">
          <input v-model="newThreadTitle" placeholder="线程标题">
          <input v-model="newThreadParticipants" placeholder="参与者（逗号分隔）">
          <button type="button" class="btn ghost" :disabled="actionLoading" @click="createThread">创建</button>
        </div>
        <ul class="list">
          <li
            v-for="th in threads"
            :key="th.id"
            :class="{ active: Number(th.id) === selectedThreadId }"
            @click="selectedThreadId = Number(th.id)"
          >
            <code>#{{ th.id }}</code>
            <span>{{ th.title }}</span>
          </li>
        </ul>
      </div>
      <div class="msg-col">
        <h2>线程消息</h2>
        <ul class="list msg-list">
          <li v-for="m in messages" :key="m.id">
            <span class="mono">@{{ m.sender_employee_id }}</span>
            <span>{{ m.content }}</span>
          </li>
        </ul>
        <div class="msg-input">
          <input
            v-model="messageDraft"
            placeholder="发送消息（支持 @employee-id）"
            @keydown.enter.prevent="sendMessage"
          >
          <button type="button" class="btn ghost" :disabled="actionLoading || !selectedThreadId" @click="sendMessage">
            发送
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.autonomy-page {
  padding: 1rem 1.25rem;
  max-width: 1300px;
  margin: 0 auto;
}
.autonomy-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.autonomy-header h1 {
  margin: 0;
  font-size: 1.2rem;
}
.autonomy-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.panel {
  margin-top: 0.9rem;
  border: 1px solid rgba(127, 127, 127, 0.25);
  border-radius: 8px;
  padding: 0.75rem;
}
.panel h2 {
  margin: 0 0 0.6rem;
  font-size: 1rem;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 0.5rem;
}
.stat {
  border: 1px dashed rgba(127, 127, 127, 0.35);
  border-radius: 6px;
  padding: 0.55rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.table-wrap {
  overflow-x: auto;
}
.table {
  width: 100%;
  border-collapse: collapse;
}
.table th,
.table td {
  border-bottom: 1px solid rgba(127, 127, 127, 0.2);
  padding: 0.35rem 0.4rem;
  text-align: left;
  vertical-align: top;
  font-size: 0.82rem;
}
.summary {
  max-width: 260px;
  word-break: break-word;
}
.panel-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.panel-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.list li {
  border-bottom: 1px solid rgba(127, 127, 127, 0.2);
  padding: 0.35rem 0.2rem;
  display: flex;
  gap: 0.45rem;
  align-items: flex-start;
}
.list li.active {
  background: rgba(59, 130, 246, 0.12);
}
.panel-collab {
  display: grid;
  grid-template-columns: minmax(320px, 38%) minmax(420px, 1fr);
  gap: 0.8rem;
}
.thread-create,
.msg-input {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 0.5rem;
}
.thread-create input,
.msg-input input,
select {
  border: 1px solid rgba(127, 127, 127, 0.35);
  border-radius: 6px;
  background: transparent;
  color: inherit;
  padding: 0.28rem 0.45rem;
}
.thread-create input:first-child {
  flex: 1.2;
}
.thread-create input:nth-child(2) {
  flex: 1;
}
.msg-input input {
  flex: 1;
}
.msg-list {
  max-height: 260px;
  overflow: auto;
  margin-bottom: 0.45rem;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.err {
  color: #c44;
}
.info {
  color: #0f766e;
}
.muted {
  color: rgba(127, 127, 127, 0.95);
}
.btn {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(127, 127, 127, 0.35);
  border-radius: 6px;
  padding: 0.3rem 0.65rem;
  background: transparent;
  color: inherit;
  text-decoration: none;
  cursor: pointer;
}
.btn.link {
  border: none;
  padding: 0;
  margin-right: 0.35rem;
  color: var(--color-primary, #60a5fa);
}
.autonomy-denied {
  text-align: center;
  padding: 2rem;
}
html[data-workbench-theme='light'] .panel{border-color:#e2e8f0}
html[data-workbench-theme='light'] .stat{border-color:#e2e8f0}
html[data-workbench-theme='light'] .table th,html[data-workbench-theme='light'] .table td{border-color:#e2e8f0}
html[data-workbench-theme='light'] .list li{border-color:#e2e8f0}
html[data-workbench-theme='light'] .list li.active{background:rgba(59,130,246,0.06)}
html[data-workbench-theme='light'] input,html[data-workbench-theme='light'] select{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .err{color:#dc2626}
html[data-workbench-theme='light'] .info{color:#0f766e}
html[data-workbench-theme='light'] .muted{color:#94a3b8}
html[data-workbench-theme='light'] .btn{border-color:#d1d5db}
html[data-workbench-theme='light'] .btn.link{color:#2563eb}
</style>

