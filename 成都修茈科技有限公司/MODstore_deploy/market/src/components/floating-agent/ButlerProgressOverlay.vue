<template>
  <!-- 全屏遮罩：运行中拦截 ESC 和背景点击 -->
  <div
    class="butler-overlay"
    role="dialog"
    aria-modal="true"
    aria-label="AI 改造进度"
    @keydown.esc.prevent
    @click.self="onBackdropClick"
  >
    <div class="butler-overlay__card" role="status">
      <!-- 头部 -->
      <header class="butler-overlay__head">
        <span class="butler-overlay__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
        </span>
        <div class="butler-overlay__titles">
          <h2 class="butler-overlay__title">AI 正在为你改造</h2>
          <p class="butler-overlay__sub">
            {{ isDone ? '改造完成，即将刷新页面…' : isFailed ? '改造遇到问题' : '请不要关闭页面' }}
          </p>
        </div>
        <span
          v-if="isDone"
          class="butler-overlay__done-badge"
          aria-label="完成"
        >✓</span>
      </header>

      <!-- 全局进度条 -->
      <div class="butler-overlay__progress-wrap" aria-hidden="true">
        <div
          class="butler-overlay__progress-bar"
          :class="{
            'butler-overlay__progress-bar--done': isDone,
            'butler-overlay__progress-bar--error': isFailed,
          }"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>

      <!-- 步骤列表 -->
      <ol class="butler-overlay__steps" aria-label="改造步骤">
        <li
          v-for="step in steps"
          :key="step.id"
          class="butler-overlay__step"
          :class="`butler-overlay__step--${step.status}`"
        >
          <span class="butler-overlay__step-icon" aria-hidden="true">
            {{ stepIcon(step.status) }}
          </span>
          <span class="butler-overlay__step-label">{{ step.label }}</span>
          <span v-if="step.message" class="butler-overlay__step-msg">{{ step.message }}</span>
        </li>
      </ol>

      <!-- 错误展示 -->
      <div v-if="isFailed && errorMessage" class="butler-overlay__error">
        <p class="butler-overlay__error-text">{{ errorMessage }}</p>
      </div>

      <!-- 操作按钮（失败后才显示）-->
      <div v-if="isFailed" class="butler-overlay__actions">
        <button
          v-if="snapshotId && targetId"
          type="button"
          class="butler-overlay__btn butler-overlay__btn--rollback"
          :disabled="rolling"
          @click="onRollback"
        >
          {{ rolling ? '回滚中…' : '回滚到快照' }}
        </button>
        <button
          type="button"
          class="butler-overlay__btn butler-overlay__btn--close"
          @click="onClose"
        >
          关闭
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '../../stores/agent'
import { useButlerOrchestrator } from '../../composables/agent/useButlerOrchestrator'
import type { OrchestrationStep } from '../../types/agent'

const emit = defineEmits<{
  (e: 'done'): void
  (e: 'rollback'): void
  (e: 'close'): void
}>()

const agentStore = useAgentStore()
const { orchestrationSession } = storeToRefs(agentStore)
const orchestrator = useButlerOrchestrator()

const rolling = ref(false)

const steps = computed<OrchestrationStep[]>(() => orchestrationSession.value?.steps ?? [])
const status = computed(() => orchestrationSession.value?.status ?? 'running')
const errorMessage = computed(() => orchestrationSession.value?.error ?? null)

const isDone = computed(() => status.value === 'done')
const isFailed = computed(() => status.value === 'error')

// Extract snapshot ID and target from artifact for rollback
const snapshotId = computed<string | null>(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  const snap = (art as Record<string, unknown>).snapshot
  if (!snap || typeof snap !== 'object') return null
  return String((snap as Record<string, unknown>).snap_id ?? '') || null
})

const targetId = computed<string | null>(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  return String((art as Record<string, unknown>).target_id ?? '') || null
})

let _overlayMaxPercent = 0
const progressPercent = computed(() => {
  const s = steps.value
  if (!s.length) return isFailed.value ? 100 : 10
  const done = s.filter((x) => x.status === 'done' || x.status === 'error').length
  const runningCount = s.filter((x) => x.status === 'running').length
  const runningFrac = runningCount > 0 ? 0.5 : 0
  let pct = Math.min(100, Math.round(((done + runningFrac) / s.length) * 100))
  if (pct < _overlayMaxPercent) pct = _overlayMaxPercent
  else _overlayMaxPercent = pct
  if (pct >= 100 || isDone.value || isFailed.value) _overlayMaxPercent = 0
  return pct
})

function stepIcon(status: OrchestrationStep['status']): string {
  if (status === 'done') return '✓'
  if (status === 'running') return '◎'
  if (status === 'error') return '✕'
  return '○'
}

// Auto-emit done 1.2s after status=done
watch(isDone, (v) => {
  if (v) {
    setTimeout(() => emit('done'), 1200)
  }
})

async function onRollback() {
  const sid = snapshotId.value
  const tid = targetId.value
  if (!sid || !tid) return
  rolling.value = true
  try {
    await orchestrator.rollbackToSnapshot(tid, sid)
    emit('rollback')
  } finally {
    rolling.value = false
  }
}

function onClose() {
  agentStore.clearOrchestration()
  emit('close')
}

// Prevent accidental close while running
function onBackdropClick() {
  if (isFailed.value || isDone.value) {
    onClose()
  }
}

// Block ESC key globally while overlay is open
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !isFailed.value && !isDone.value) {
    e.preventDefault()
    e.stopPropagation()
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown, true))
</script>

<style scoped>
.butler-overlay {
  position: fixed;
  inset: 0;
  z-index: 12000;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.butler-overlay__card {
  background: rgba(10, 11, 18, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow:
    0 24px 64px rgba(0, 0, 0, 0.7),
    0 0 0 1px rgba(255, 255, 255, 0.04);
  width: 100%;
  max-width: 480px;
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ── head ── */
.butler-overlay__head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.butler-overlay__icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.18);
  border: 1px solid rgba(99, 102, 241, 0.28);
  color: #818cf8;
}

.butler-overlay__icon svg { width: 20px; height: 20px; }

.butler-overlay__titles { flex: 1; }

.butler-overlay__title {
  font-size: 1rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  margin: 0 0 2px;
}

.butler-overlay__sub {
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.44);
  margin: 0;
}

.butler-overlay__done-badge {
  font-size: 1.2rem;
  color: #4ade80;
  font-weight: 700;
  flex-shrink: 0;
}

/* ── progress bar ── */
.butler-overlay__progress-wrap {
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 99px;
  overflow: hidden;
}

.butler-overlay__progress-bar {
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, #6366f1, #818cf8);
  transition: width 0.5s ease;
}

.butler-overlay__progress-bar--done {
  background: #4ade80;
  width: 100% !important;
}

.butler-overlay__progress-bar--error {
  background: #f87171;
}

/* ── steps ── */
.butler-overlay__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.butler-overlay__step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 0.82rem;
}

.butler-overlay__step-icon {
  flex-shrink: 0;
  width: 18px;
  text-align: center;
  font-size: 0.85rem;
}

.butler-overlay__step--pending .butler-overlay__step-icon { color: rgba(255, 255, 255, 0.24); }
.butler-overlay__step--running .butler-overlay__step-icon { color: #fbbf24; animation: pulse-icon 1s ease-in-out infinite; }
.butler-overlay__step--done    .butler-overlay__step-icon { color: #4ade80; }
.butler-overlay__step--error   .butler-overlay__step-icon { color: #f87171; }

.butler-overlay__step-label {
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.4;
}

.butler-overlay__step--pending .butler-overlay__step-label { color: rgba(255, 255, 255, 0.36); }
.butler-overlay__step--done    .butler-overlay__step-label { color: rgba(255, 255, 255, 0.56); text-decoration: line-through; }

.butler-overlay__step-msg {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.36);
  margin-left: auto;
  text-align: right;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── error ── */
.butler-overlay__error {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: 8px;
  padding: 10px 14px;
}

.butler-overlay__error-text {
  margin: 0;
  font-size: 0.8rem;
  color: #fca5a5;
  line-height: 1.5;
}

/* ── actions ── */
.butler-overlay__actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.butler-overlay__btn {
  padding: 7px 16px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.butler-overlay__btn--rollback {
  background: rgba(251, 191, 36, 0.15);
  border: 1px solid rgba(251, 191, 36, 0.35);
  color: #fbbf24;
}

.butler-overlay__btn--rollback:hover:not(:disabled) {
  background: rgba(251, 191, 36, 0.25);
}

.butler-overlay__btn--rollback:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.butler-overlay__btn--close {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.6);
}

.butler-overlay__btn--close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.88);
}

@keyframes pulse-icon {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
</style>
