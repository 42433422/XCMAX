<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import { useTutorialV2Store } from '@/stores/tutorialV2'
import { taskNeedsApproval, taskProgressPercent, taskStatusLabel, taskUnreadCount } from '@/utils/taskWorkspacePresentation'

const store = useAgentTaskCenterStore()
const tutorialStore = useTutorialV2Store()
const router = useRouter()
const { tasks, drawerOpen, loading, connected, error, runtime, unreadCount, approvalCount, activeCount } = storeToRefs(store)
const filter = ref<'all' | 'active' | 'unread' | 'approval'>('all')
const filters = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '执行中' },
  { value: 'unread', label: '未读' },
  { value: 'approval', label: '待审批' },
] as const

const filteredTasks = computed(() =>
  tasks.value.filter((task) => {
    if (filter.value === 'active') {
      return ['queued', 'planning', 'running', 'retrying', 'paused'].includes(task.status)
    }
    if (filter.value === 'unread') return taskUnreadCount(task) > 0
    if (filter.value === 'approval') return taskNeedsApproval(task)
    return true
  }),
)

const tutorialScopeKey = computed(() => {
  const run = tutorialStore.currentRun
  return `${run?.id || ''}:${run?.status || ''}:${run?.generation || ''}`
})

const overview = computed(
  () =>
    runtime.value.progress || {
      task_count: tasks.value.length,
      active_count: activeCount.value,
      attention_count: approvalCount.value,
      completed_count: tasks.value.filter((task) => task.status === 'completed').length,
      overall_percent: tasks.value.length
        ? Math.round(tasks.value.reduce((total, task) => total + taskProgressPercent(task), 0) / tasks.value.length)
        : 0,
    },
)

function formatTime(value: string | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

async function openWorkspace(task: AgentTaskSummary): Promise<void> {
  if (taskUnreadCount(task) > 0) await store.markTaskRead(task.task_id)
  const conversationId = String(task.conversation_id || task.workspace_id || task.task_id).trim()
  await router.push({
    name: 'task-workspace',
    params: { taskId: task.task_id },
    query: { conversation: conversationId },
  })
  store.closeDrawer()
}

function toggleDrawer(): void {
  if (drawerOpen.value) {
    store.closeDrawer()
    return
  }
  drawerOpen.value = true
  void store.refresh()
}

onMounted(() => store.start())
onBeforeUnmount(() => store.stop())
watch(tutorialScopeKey, (next, previous) => {
  if (next !== previous) store.restartForScope()
})
</script>

<template>
  <button class="task-center-trigger" type="button" aria-label="打开独立工作区列表" :aria-expanded="drawerOpen" @click="toggleDrawer">
    <span class="task-center-trigger__icon">◈</span>
    <span class="task-center-trigger__label">工作区</span>
    <strong v-if="approvalCount">{{ approvalCount }}</strong>
    <em v-else-if="unreadCount">{{ unreadCount }}</em>
    <em v-else-if="activeCount">{{ activeCount }}</em>
  </button>

  <Teleport to="body">
    <Transition name="task-center-fade">
      <div v-if="drawerOpen" class="task-center-overlay" @click.self="store.closeDrawer()">
        <aside class="task-center-drawer" role="dialog" aria-modal="true" aria-label="独立工作区列表">
          <header class="task-center-header">
            <div>
              <span class="task-center-eyebrow">独立对话与执行上下文</span>
              <h2>工作区</h2>
              <p>
                <span :class="['connection-dot', { 'is-online': connected }]" />
                {{ connected ? '实时同步' : '自动重连' }} · {{ tasks.length }} 个工作区
                <template v-if="runtime.running"> · 并发 {{ runtime.active_count }}/{{ runtime.max_workers }}</template>
              </p>
            </div>
            <button class="task-center-close" type="button" aria-label="关闭" @click="store.closeDrawer()">×</button>
          </header>

          <div v-if="error" class="task-center-error">
            <span>{{ error }}</span
            ><button type="button" @click="store.refresh()">重试</button>
          </div>

          <section class="task-center-overview" aria-label="全部工作区进度概览">
            <div class="task-center-overview__head">
              <strong>统一进度 {{ overview.overall_percent }}%</strong>
              <span>完成 {{ overview.completed_count }}/{{ overview.task_count }}</span>
            </div>
            <div
              class="task-center-overview__track"
              role="progressbar"
              aria-label="全部工作区统一进度"
              :aria-valuenow="overview.overall_percent"
              aria-valuemin="0"
              aria-valuemax="100"
            >
              <span :style="{ width: `${overview.overall_percent}%` }" />
            </div>
            <div class="task-center-overview__facts">
              <span>{{ overview.active_count }} 个未结束</span>
              <span>{{ overview.attention_count }} 个需处理</span>
              <span>{{ unreadCount }} 个未读结果</span>
            </div>
          </section>

          <nav class="task-center-filters" aria-label="工作区筛选">
            <button
              v-for="item in filters"
              :key="item.value"
              type="button"
              :class="{ active: filter === item.value }"
              @click="filter = item.value"
            >
              {{ item.label }}
              <span v-if="item.value === 'unread' && unreadCount">{{ unreadCount }}</span>
              <span v-if="item.value === 'approval' && approvalCount">{{ approvalCount }}</span>
            </button>
          </nav>

          <div class="task-center-list" data-tutorial-id="task-workspace-list">
            <button
              v-for="task in filteredTasks"
              :key="task.task_id"
              class="task-center-item"
              type="button"
              :aria-label="`打开${task.title}独立工作区`"
              @click="openWorkspace(task)"
            >
              <span class="task-center-item__top">
                <strong>{{ task.title }}</strong>
                <em :data-status="task.status">{{ taskStatusLabel(task.status) }}</em>
              </span>

              <span class="task-center-item__signals">
                <span :class="['workspace-read-state', { 'is-unread': taskUnreadCount(task) > 0 }]">
                  {{ taskUnreadCount(task) > 0 ? `${taskUnreadCount(task)} 未读` : '已读' }}
                </span>
                <span v-if="taskNeedsApproval(task)" class="workspace-approval-state">待审批</span>
                <span v-else-if="['blocked', 'failed'].includes(task.status)" class="workspace-blocked-state">需处理</span>
              </span>

              <span class="task-center-progress">
                <span class="task-center-progress__head">
                  <span
                    >{{ task.progress?.stage || taskStatusLabel(task.status)
                    }}<template v-if="task.progress?.detail"> · {{ task.progress.detail }}</template></span
                  >
                  <strong>{{ taskProgressPercent(task) }}%</strong>
                </span>
                <span
                  class="task-center-progress__track"
                  role="progressbar"
                  :aria-label="`${task.title}工作区进度`"
                  :aria-valuenow="taskProgressPercent(task)"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  ><span :style="{ width: `${taskProgressPercent(task)}%` }"
                /></span>
              </span>

              <span class="task-center-item__meta">
                <small>{{ formatTime(task.updated_at) }}</small>
                <span>进入独立对话 →</span>
              </span>
            </button>
            <div v-if="!filteredTasks.length" class="task-center-empty">
              {{ loading ? '正在同步工作区…' : '这里暂时没有工作区' }}
            </div>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./GlobalTaskCenter.css"></style>
