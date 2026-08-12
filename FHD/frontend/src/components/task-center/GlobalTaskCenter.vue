<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import type { AgentRun, AgentTaskCapabilities, AgentTaskSummary } from '@/api/agentRuns'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'

const store = useAgentTaskCenterStore()
const router = useRouter()
const {
  tasks,
  selectedTask,
  drawerOpen,
  loading,
  actionPending,
  connected,
  error,
  runtime,
  attentionCount,
  activeCount,
} = storeToRefs(store)
const filter = ref<'all' | 'active' | 'attention' | 'completed'>('all')
const filters = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '执行中' },
  { value: 'attention', label: '待处理' },
  { value: 'completed', label: '已完成' },
] as const

const filteredTasks = computed(() => tasks.value.filter((task) => {
  if (filter.value === 'active') return ['queued', 'planning', 'running', 'retrying', 'paused'].includes(task.status)
  if (filter.value === 'attention') return ['waiting_user', 'blocked', 'failed'].includes(task.status)
  if (filter.value === 'completed') return ['completed', 'cancelled'].includes(task.status)
  return true
}))
const activeRun = computed<AgentRun | null>(() => {
  const task = selectedTask.value
  if (!task) return null
  return task.active_run
    || task.runs?.find((run) => run.run_id === task.active_run_id)
    || task.runs?.[Math.max(0, (task.runs?.length || 1) - 1)]
    || null
})
const capabilities = computed<Partial<AgentTaskCapabilities>>(() => selectedTask.value?.capabilities || {})
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(selectedTask.value?.status || ''))

function statusLabel(status: string | undefined): string {
  return {
    queued: '排队中', claimed: '执行中', planning: '规划中', running: '执行中', retrying: '重试中',
    waiting_user: '等待审批', paused: '已暂停', blocked: '已阻断', completed: '已完成',
    failed: '失败', cancelled: '已取消', pending: '待执行', skipped: '已跳过',
  }[String(status || '')] || String(status || '未知')
}

function pretty(value: unknown): string {
  if (!value || typeof value !== 'object') return ''
  const text = JSON.stringify(value, null, 2)
  return text.length > 5000 ? `${text.slice(0, 5000)}\n…` : text
}

function formatTime(value: string | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function can(action: 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'): boolean {
  return Boolean(capabilities.value[action])
}

async function openConversation(task: AgentTaskSummary): Promise<void> {
  await router.push({
    name: 'chat',
    query: {
      task: task.task_id,
      ...(task.conversation_id ? { conversation: task.conversation_id } : {}),
    },
  })
  store.closeDrawer()
}

onMounted(() => store.start())
onBeforeUnmount(() => store.stop())
</script>

<template>
  <button
    class="task-center-trigger"
    type="button"
    aria-label="打开全局任务中心"
    :aria-expanded="drawerOpen"
    @click="drawerOpen ? store.closeDrawer() : (drawerOpen = true)"
  >
    <span class="task-center-trigger__icon">✓</span>
    <span>任务</span>
    <strong v-if="attentionCount">{{ attentionCount }}</strong>
    <em v-else-if="activeCount">{{ activeCount }}</em>
  </button>

  <Teleport to="body">
    <Transition name="task-center-fade">
      <div v-if="drawerOpen" class="task-center-overlay" @click.self="store.closeDrawer()">
        <aside class="task-center-drawer" role="dialog" aria-modal="true" aria-label="全局任务中心">
          <header class="task-center-header">
            <div>
              <button v-if="selectedTask" class="task-center-back" type="button" @click="store.showTaskList()">← 全部任务</button>
              <h2>{{ selectedTask?.title || '任务中心' }}</h2>
              <p v-if="!selectedTask">
                <span :class="['connection-dot', { 'is-online': connected }]" />
                {{ connected ? '实时连接' : '自动重连' }} · {{ runtime.running ? `并发 ${runtime.active_count}/${runtime.max_workers}` : '执行器未启动' }}
              </p>
            </div>
            <button class="task-center-close" type="button" aria-label="关闭" @click="store.closeDrawer()">×</button>
          </header>

          <div v-if="error" class="task-center-error">
            <span>{{ error }}</span><button type="button" @click="store.refresh()">重试</button>
          </div>

          <template v-if="!selectedTask">
            <nav class="task-center-filters" aria-label="任务筛选">
              <button v-for="item in filters" :key="item.value" type="button" :class="{ active: filter === item.value }" @click="filter = item.value">
                {{ item.label }}
              </button>
            </nav>
            <div class="task-center-list">
              <button
                v-for="task in filteredTasks"
                :key="task.task_id"
                class="task-center-item"
                type="button"
                @click="store.openTask(task.task_id)"
              >
                <span class="task-center-item__top">
                  <strong>{{ task.title }}</strong>
                  <em :data-status="task.status">{{ statusLabel(task.status) }}</em>
                </span>
                <span class="task-center-item__meta">
                  第 {{ task.attempt || 1 }} 次 · {{ task.execution ? statusLabel(task.execution.state) : '等待调度' }}
                  <small>{{ formatTime(task.updated_at) }}</small>
                </span>
                <span v-if="task.attention_state" class="task-center-attention">需要你处理</span>
              </button>
              <div v-if="!filteredTasks.length" class="task-center-empty">
                {{ loading ? '正在同步任务…' : '这里暂时没有任务' }}
              </div>
            </div>
          </template>

          <div v-else class="task-center-detail">
            <section class="task-center-summary">
              <span class="task-status" :data-status="selectedTask.status">{{ statusLabel(selectedTask.status) }}</span>
              <span>第 {{ selectedTask.attempt }} 次 / 共 {{ selectedTask.run_count }} 次</span>
              <span v-if="selectedTask.execution">执行 {{ selectedTask.execution.execution_count }} 次 · 恢复 {{ selectedTask.execution.recovery_count }} 次</span>
            </section>

            <section v-if="activeRun?.steps?.length" class="task-center-section">
              <h3>执行步骤</h3>
              <ol class="task-center-steps">
                <li v-for="step in activeRun.steps" :key="step.step_id">
                  <span class="step-marker" :data-status="step.status" />
                  <div><strong>{{ step.description || `${step.tool_id}.${step.action}` }}</strong><small>{{ statusLabel(step.status) }} · {{ step.idempotent ? '可安全恢复' : '禁止未知重放' }}</small></div>
                </li>
              </ol>
            </section>

            <section v-if="can('approve')" class="task-center-approval">
              <strong>此任务正在等待审批</strong>
              <p>批准后由后台工作线程独立执行；关闭页面不会中断任务。</p>
            </section>

            <section class="task-center-actions">
              <button v-if="can('approve')" class="is-primary" type="button" :disabled="!!actionPending" @click="store.control('approve')">批准并执行</button>
              <button v-if="can('pause')" type="button" :disabled="!!actionPending" @click="store.control('pause')">暂停</button>
              <button v-if="can('resume')" class="is-primary" type="button" :disabled="!!actionPending" @click="store.control('resume')">恢复</button>
              <button v-if="can('retry')" class="is-primary" type="button" :disabled="!!actionPending" @click="store.control('retry')">重试</button>
              <button v-if="can('cancel')" type="button" :disabled="!!actionPending" @click="store.control('cancel')">取消</button>
              <button type="button" @click="openConversation(selectedTask)">打开对话</button>
              <button v-if="terminal" type="button" :disabled="!!actionPending" @click="store.archiveSelected()">归档</button>
            </section>

            <section class="task-center-section task-center-evidence">
              <h3>结果证据</h3>
              <div class="evidence-facts">
                <span>{{ activeRun?.events?.length || 0 }} 条事件</span>
                <span>{{ activeRun?.tool_calls?.filter((call) => call.status === 'completed').length || 0 }} 次工具执行</span>
                <span>{{ activeRun?.artifacts?.length || 0 }} 个产物</span>
              </div>
              <details v-if="activeRun?.final_output && Object.keys(activeRun.final_output).length">
                <summary>最终结果</summary><pre>{{ pretty(activeRun.final_output) }}</pre>
              </details>
              <details v-if="activeRun?.tool_calls?.length">
                <summary>工具调用记录</summary>
                <ul><li v-for="call in activeRun.tool_calls" :key="call.call_id">{{ call.tool_id }}.{{ call.action }} · {{ statusLabel(call.status) }} · {{ call.duration_ms || 0 }}ms</li></ul>
              </details>
              <details v-if="activeRun?.artifacts?.length">
                <summary>任务产物</summary>
                <ul><li v-for="artifact in activeRun.artifacts" :key="artifact.artifact_id">{{ artifact.name || artifact.artifact_type }}<small v-if="artifact.uri">{{ artifact.uri }}</small></li></ul>
              </details>
              <details v-if="activeRun?.events?.length">
                <summary>事件时间线</summary>
                <ul><li v-for="event in activeRun.events" :key="event.event_id">{{ formatTime(event.created_at) }} · {{ event.message || event.event_type }}</li></ul>
              </details>
            </section>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./GlobalTaskCenter.css"></style>
