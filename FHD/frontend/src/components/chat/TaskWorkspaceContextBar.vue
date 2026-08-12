<script setup lang="ts">
import { taskStatusLabel } from '@/utils/taskWorkspacePresentation'

const props = withDefaults(defineProps<{
  title: string
  status?: string
  stage?: string
  progress?: number
  unreadCount?: number
  approvalRequired?: boolean
  attempt?: number
  runCount?: number
  capabilities?: Record<string, boolean>
  actionPending?: string
}>(), {
  status: '',
  stage: '',
  progress: undefined,
  unreadCount: 0,
  approvalRequired: false,
  attempt: 1,
  runCount: 1,
  capabilities: () => ({}),
  actionPending: '',
})

const emit = defineEmits<{
  control: [action: 'approve' | 'pause' | 'cancel' | 'resume' | 'retry']
}>()

function can(action: 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'): boolean {
  if (action in props.capabilities) return Boolean(props.capabilities[action])
  if (action === 'approve') return props.status === 'waiting_user'
  if (action === 'pause') return ['queued', 'planning', 'running', 'retrying', 'waiting_user'].includes(props.status)
  if (action === 'resume') return props.status === 'paused'
  if (action === 'cancel') return ['queued', 'planning', 'running', 'retrying', 'waiting_user', 'paused', 'blocked'].includes(props.status)
  return ['failed', 'cancelled', 'blocked'].includes(props.status)
}
</script>

<template>
  <section class="chat-workspace-context" aria-label="当前独立工作区">
    <div>
      <span>独立对话工作区</span>
      <h1>{{ title }}</h1>
      <div class="chat-workspace-context__signals">
        <em :data-status="status">{{ taskStatusLabel(status) }}</em>
        <em v-if="approvalRequired" class="is-approval">待审批</em>
        <em v-if="unreadCount" class="is-unread">{{ unreadCount }} 未读</em>
        <small>第 {{ attempt }} 次尝试 · {{ runCount }} 次运行</small>
      </div>
    </div>
    <div class="chat-workspace-context__state">
      <div><strong>{{ stage || '正在同步工作区' }}</strong><span>{{ progress ?? 0 }}%</span></div>
      <span
        class="chat-workspace-context__track"
        role="progressbar"
        :aria-label="`${title}工作区统一进度`"
        :aria-valuenow="progress ?? 0"
        aria-valuemin="0"
        aria-valuemax="100"
      ><span :style="{ width: `${progress ?? 0}%` }" /></span>
      <div v-if="can('approve') || can('pause') || can('cancel') || can('resume') || can('retry')" class="chat-workspace-context__actions">
        <button v-if="can('approve')" type="button" :disabled="Boolean(actionPending)" @click="emit('control', 'approve')">审批并执行</button>
        <button v-if="can('resume')" type="button" :disabled="Boolean(actionPending)" @click="emit('control', 'resume')">恢复</button>
        <button v-if="can('retry')" type="button" :disabled="Boolean(actionPending)" @click="emit('control', 'retry')">重试</button>
        <button v-if="can('pause')" type="button" :disabled="Boolean(actionPending)" @click="emit('control', 'pause')">暂停</button>
        <button v-if="can('cancel')" type="button" :disabled="Boolean(actionPending)" @click="emit('control', 'cancel')">取消</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-workspace-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin: 0 0 10px;
  padding: 12px 16px;
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-lg);
  background: linear-gradient(110deg, var(--xc-color-primary-surface), var(--xc-color-surface));
}

.chat-workspace-context > div:first-child > span {
  color: var(--xc-color-primary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.chat-workspace-context h1 { margin: 2px 0 0; font-size: var(--xc-font-lg); }
.chat-workspace-context__signals { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.chat-workspace-context__signals em { padding: 2px 7px; border-radius: var(--xc-radius-full); color: var(--xc-color-muted); background: var(--xc-color-surface-3); font-size: 10px; font-style: normal; }
.chat-workspace-context__signals em.is-approval { color: var(--xc-color-warning); background: var(--xc-color-warning-bg); }
.chat-workspace-context__signals em.is-unread { color: var(--xc-color-primary); background: var(--xc-color-primary-surface); }
.chat-workspace-context__signals small { align-self: center; color: var(--xc-color-muted); font-size: 10px; }
.chat-workspace-context__state { display: grid; flex: 0 0 min(260px, 36vw); gap: 7px; color: var(--xc-color-muted); font-size: var(--xc-font-xs); }
.chat-workspace-context__state > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.chat-workspace-context__state strong { color: var(--xc-color-text-secondary); font-weight: 600; }
.chat-workspace-context__track { display: block; height: 7px; overflow: hidden; border-radius: var(--xc-radius-full); background: color-mix(in srgb, var(--xc-color-muted) 16%, transparent); }
.chat-workspace-context__track > span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--xc-color-primary), var(--xc-color-info)); }
.chat-workspace-context__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 5px; }
.chat-workspace-context__actions button { padding: 4px 8px; border: 1px solid var(--xc-color-border); border-radius: var(--xc-radius-md); color: var(--xc-color-text-secondary); background: var(--xc-color-surface); font-size: 10px; cursor: pointer; }
.chat-workspace-context__actions button:first-child { border-color: var(--xc-color-primary); color: white; background: var(--xc-color-primary); }
.chat-workspace-context__actions button:disabled { cursor: wait; opacity: .55; }
@media (max-width: 720px) { .chat-workspace-context { align-items: stretch; flex-direction: column; } .chat-workspace-context__state { flex-basis: auto; } }
</style>
