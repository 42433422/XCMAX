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

interface AutonomyDashboard {
  counts?: {
    change_requests_pending?: number
    suggestions_pending?: number
    brief_tasks_pending?: number
    collab_threads_open?: number
  }
}

interface EmployeeSuggestion {
  id: number | string
  source_employee_id?: string
  target_employee_ids?: string[]
  kind?: string
  risk_level?: string
  status?: string
  summary?: string
}

interface EmployeeBriefTask {
  id: number | string
  owner_employee_id?: string
  task_brief?: string
}

interface CollabThread {
  id: number | string
  title?: string
}

interface CollabMessage {
  id: number | string
  sender_employee_id?: string
  content?: string
}

const dashboard = ref<AutonomyDashboard>({})
const suggestions = ref<EmployeeSuggestion[]>([])
const briefTasks = ref<EmployeeBriefTask[]>([])
const threads = ref<CollabThread[]>([])
const messages = ref<CollabMessage[]>([])

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
  dashboard.value = (await api.adminEmployeeAutonomyDashboard(40)) as AutonomyDashboard
}

async function loadSuggestions() {
  const r = (await api.adminEmployeeSuggestions({
    status: suggestionStatus.value || undefined,
    limit: 120,
    offset: 0,
  })) as { items?: EmployeeSuggestion[] }
  suggestions.value = Array.isArray(r?.items) ? r.items : []
  selectedSuggestionIds.value = selectedSuggestionIds.value.filter((id) =>
    suggestions.value.some((s) => Number(s.id) === id),
  )
}

async function loadBriefTasks() {
  const r = (await api.adminEmployeeBriefTasks({
    status: 'pending',
    limit: 120,
  })) as { items?: EmployeeBriefTask[] }
  briefTasks.value = Array.isArray(r?.items) ? r.items : []
}

async function loadThreads() {
  const r = (await api.adminEmployeeCollabThreads({ status: 'open', limit: 80 })) as {
    items?: CollabThread[]
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
    items?: CollabMessage[]
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
    })) as { processed?: number; created?: number }
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
    })) as { thread_id?: number | string }
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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./AdminEmployeeAutonomyView.css，模板与逻辑保持原样。 -->
<style scoped src="./AdminEmployeeAutonomyView.css"></style>
