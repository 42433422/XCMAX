<script setup lang="ts">
import { computed } from 'vue'
import { orchStepEmployee } from '../../../utils/orchestrationSteps'

const props = defineProps<{
  planSession: {
    phase?: string
    intentTitle?: string
    summaryTitle?: string
    summaryText?: string
    summaryNeedsClarification?: boolean
    checklistLines?: string[]
    loading?: boolean
  } | null
  pendingHandoff: {
    intentTitle?: string
    description?: string
    workflowName?: string
    intentKey?: string
  } | null
  orchestrationSession: {
    steps?: Array<{ id?: string; label?: string; status?: string }>
    status?: string
    error?: string
  } | null
  orchPhase: string
  voiceInjectQueue: string[]
  canRunOrch: boolean
  orchestrationProgress?: { done: number; total: number; percent: number }
  finalizeLoading?: boolean
  finalizeError?: string
  makeCompletionResult?: {
    title?: string
    subtitle?: string
    primaryLabel?: string
    intent?: string
  } | null
}>()

defineEmits<{
  confirmGenerate: []
  dismissHandoff: []
  dismissPlan: []
  openCompletion: []
}>()

const showPlan = computed(() => Boolean(props.planSession))
const showHandoff = computed(() => Boolean(props.pendingHandoff))
const showOrch = computed(
  () =>
    props.orchPhase === 'running' ||
    props.orchPhase === 'estimating' ||
    (props.orchestrationSession?.steps?.length ?? 0) > 0,
)
const orchActive = computed(
  () =>
    props.finalizeLoading ||
    props.orchPhase === 'running' ||
    props.orchPhase === 'estimating',
)
const showHandoffActions = computed(() => showHandoff.value && !orchActive.value)
const orchErrorText = computed(
  () => props.finalizeError || props.orchestrationSession?.error || '',
)
const showCompletion = computed(
  () =>
    Boolean(props.makeCompletionResult) &&
    props.orchestrationSession?.status === 'done' &&
    !props.finalizeLoading,
)
</script>

<template>
  <div v-if="showPlan || showHandoff || showOrch || voiceInjectQueue.length" class="wb-voice-task-panels">
    <section v-if="showPlan" class="wb-voice-task-panel" aria-label="任务规划">
      <div class="wb-voice-task-panel__head">
        <h3 class="wb-voice-task-panel__title">{{ planSession?.intentTitle || '任务规划' }}</h3>
        <button
          type="button"
          class="wb-voice-task-panel__btn wb-voice-task-panel__btn--close"
          aria-label="关闭规划摘要"
          @click="$emit('dismissPlan')"
        >
          关闭
        </button>
      </div>
      <p v-if="planSession?.loading" class="wb-voice-task-panel__hint">规划中…</p>
      <template v-else-if="planSession?.phase === 'summary'">
        <p class="wb-voice-task-panel__phase">
          {{ planSession.summaryNeedsClarification ? '还需补充' : '摘要确认' }}
        </p>
        <p v-if="planSession.summaryText" class="wb-voice-task-panel__body">{{ planSession.summaryText }}</p>
        <p v-if="planSession.summaryNeedsClarification" class="wb-voice-task-panel__hint">
          继续用语音说明职责与目标，或点「关闭」回到纯对话。
        </p>
      </template>
      <template v-else-if="planSession?.phase === 'chat'">
        <p class="wb-voice-task-panel__phase">需求澄清中</p>
      </template>
      <template v-else-if="planSession?.phase === 'checklist'">
        <p class="wb-voice-task-panel__phase">执行清单</p>
        <ul v-if="planSession.checklistLines?.length" class="wb-voice-task-panel__list">
          <li v-for="(line, i) in planSession.checklistLines" :key="i">{{ line }}</li>
        </ul>
      </template>
    </section>

    <section v-if="showHandoff" class="wb-voice-task-panel wb-voice-task-panel--handoff" aria-label="制作草稿">
      <h3 class="wb-voice-task-panel__title">{{ pendingHandoff?.intentTitle || '制作草稿' }}</h3>
      <p class="wb-voice-task-panel__body wb-voice-task-panel__body--clip">{{ pendingHandoff?.description }}</p>
      <p v-if="pendingHandoff?.workflowName" class="wb-voice-task-panel__meta">Skill 组：{{ pendingHandoff.workflowName }}</p>
      <div v-if="showHandoffActions" class="wb-voice-task-panel__actions">
        <button
          type="button"
          class="wb-voice-task-panel__btn wb-voice-task-panel__btn--primary"
          :disabled="!canRunOrch"
          @click="$emit('confirmGenerate')"
        >
          开始生成
        </button>
        <button type="button" class="wb-voice-task-panel__btn" @click="$emit('dismissHandoff')">关闭</button>
      </div>
      <p v-else-if="orchActive" class="wb-voice-task-panel__hint">制作进行中…</p>
      <p v-if="showHandoffActions && !canRunOrch" class="wb-voice-task-panel__hint">请补充 Skill 组名称或描述后再生成</p>
    </section>

    <section v-if="showOrch" class="wb-voice-task-panel wb-voice-task-panel--orch" aria-label="制作进度">
      <div class="wb-voice-task-panel__head">
        <h3 class="wb-voice-task-panel__title">制作进度</h3>
        <span v-if="orchestrationProgress" class="wb-voice-task-panel__pct">
          {{ orchestrationProgress.done }}/{{ orchestrationProgress.total }}
        </span>
      </div>
      <div v-if="orchestrationProgress" class="wb-voice-task-bar" aria-hidden="true">
        <span class="wb-voice-task-bar__fill" :style="{ width: `${orchestrationProgress.percent}%` }" />
      </div>
      <ul v-if="orchestrationSession?.steps?.length" class="wb-voice-task-steps">
        <li
          v-for="st in orchestrationSession.steps"
          :key="st.id || st.label"
          class="wb-voice-task-step"
          :class="`wb-voice-task-step--${st.status || 'pending'}`"
        >
          {{ orchStepEmployee(st) }}<span v-if="st.status === 'running'">…</span>
        </li>
      </ul>
      <p v-else-if="orchPhase === 'estimating'" class="wb-voice-task-panel__hint">估算用时中…</p>
      <p v-if="orchErrorText" class="wb-voice-task-panel__hint wb-voice-task-panel__hint--error" role="alert">
        {{ orchErrorText }}
      </p>
    </section>

    <section v-if="showCompletion" class="wb-voice-task-panel wb-voice-task-panel--done" aria-label="制作完成">
      <h3 class="wb-voice-task-panel__title">{{ makeCompletionResult?.title || '制作完成' }}</h3>
      <p v-if="makeCompletionResult?.subtitle" class="wb-voice-task-panel__body">{{ makeCompletionResult.subtitle }}</p>
      <div class="wb-voice-task-panel__actions">
        <button
          type="button"
          class="wb-voice-task-panel__btn wb-voice-task-panel__btn--primary"
          @click="$emit('openCompletion')"
        >
          {{ makeCompletionResult?.primaryLabel || '打开员工制作' }}
        </button>
      </div>
    </section>

    <section v-if="voiceInjectQueue.length" class="wb-voice-task-panel wb-voice-task-panel--inject" aria-label="中途补充">
      <h3 class="wb-voice-task-panel__title">已记录补充</h3>
      <ul class="wb-voice-task-panel__list">
        <li v-for="(item, i) in voiceInjectQueue" :key="i">{{ item }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.wb-voice-task-panels {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 720px;
  width: 100%;
  margin: 0 auto 0.5rem;
  padding: 0 1rem;
  box-sizing: border-box;
}
.wb-voice-task-panel {
  border: none;
  border-radius: 0;
  padding: 0;
  background: transparent;
  box-shadow: none;
}
.wb-voice-task-panel__title {
  margin: 0 0 0.4rem;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: none;
  color: rgba(255, 255, 255, 0.42);
}
.wb-voice-task-panel__head .wb-voice-task-panel__title {
  margin: 0;
}
.wb-voice-task-panel__phase {
  margin: 0;
  font-size: 0.75rem;
  opacity: 0.55;
}
.wb-voice-task-panel__body {
  margin: 0.15rem 0 0;
  font-size: 0.88rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.82);
  white-space: pre-wrap;
  word-break: break-word;
}
.wb-voice-task-panel__body--clip {
  display: block;
  overflow: visible;
}
.wb-voice-task-panel__meta {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  opacity: 0.7;
}
.wb-voice-task-panel__hint {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  opacity: 0.6;
}
.wb-voice-task-panel__hint--error {
  opacity: 0.85;
  color: #f87171;
}
.wb-voice-task-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}
.wb-voice-task-panel__pct {
  font-size: 0.75rem;
  opacity: 0.65;
}
.wb-voice-task-panel__actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.65rem;
}
.wb-voice-task-panel__btn {
  font-size: 0.82rem;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.wb-voice-task-panel__btn--close {
  flex-shrink: 0;
  font-size: 0.75rem;
  opacity: 0.7;
}
.wb-voice-task-panel__btn--primary {
  color: #818cf8;
  text-decoration: none;
  font-weight: 600;
}
.wb-voice-task-panel__btn--primary:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.wb-voice-task-panel__list {
  margin: 0.35rem 0 0;
  padding-left: 1.1rem;
  font-size: 0.78rem;
  opacity: 0.85;
}
.wb-voice-task-bar {
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.08);
  margin: 0.35rem 0 0.5rem;
  overflow: hidden;
}
.wb-voice-task-bar__fill {
  display: block;
  height: 100%;
  background: rgba(129, 140, 248, 0.75);
  border-radius: 2px;
  transition: width 0.3s ease;
}
.wb-voice-task-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.wb-voice-task-step {
  font-size: 0.82rem;
  opacity: 0.5;
  padding-left: 0.65rem;
  border-left: 2px solid transparent;
}
.wb-voice-task-step--running {
  opacity: 1;
  color: rgba(255, 255, 255, 0.92);
  border-left-color: rgba(129, 140, 248, 0.65);
}
.wb-voice-task-step--done {
  opacity: 0.38;
  text-decoration: none;
}

html[data-workbench-theme='light'] .wb-voice-task-panel__title {
  color: #86868b;
}
html[data-workbench-theme='light'] .wb-voice-task-panel__body {
  color: #334155;
}
html[data-workbench-theme='light'] .wb-voice-task-panel__btn {
  color: #86868b;
}
html[data-workbench-theme='light'] .wb-voice-task-panel__btn--primary {
  color: #4f46e5;
}
</style>
