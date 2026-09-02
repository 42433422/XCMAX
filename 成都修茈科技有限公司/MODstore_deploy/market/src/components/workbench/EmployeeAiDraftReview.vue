<template>
  <section
    class="emp-draft-review"
    :class="{ 'emp-draft-review--embedded': embedded }"
    role="region"
    aria-label="AI 制作草稿审核"
  >
    <!-- 顶部标题栏 -->
    <header class="emp-draft-head">
      <div class="emp-draft-title-row">
        <h2 class="emp-draft-title">AI 制作草稿</h2>
        <button
          v-if="!embedded"
          type="button"
          class="emp-draft-close"
          aria-label="关闭"
          @click="$emit('close')"
        >
          ×
        </button>
      </div>
      <p class="emp-draft-sub muted small">
        {{ statusLabel }}
      </p>
    </header>

    <!-- 对话审核 -->
    <section v-if="status.phase !== 'idle'" class="emp-draft-chat" aria-label="对话审核">
      <div class="emp-draft-chat__head">
        <span class="emp-draft-chat__title">对话审核</span>
        <span class="emp-draft-chat__hint muted small">流水线可推送 review_reply / clarification_question</span>
      </div>
      <ul v-if="reviewMessages.length" class="emp-draft-chat__thread" aria-live="polite">
        <li
          v-for="m in reviewMessages"
          :key="m.id"
          class="emp-draft-chat__msg"
          :class="`emp-draft-chat__msg--${m.role}`"
        >
          {{ m.content }}
        </li>
      </ul>
      <div class="emp-draft-chat__composer">
        <textarea
          v-model="reviewInput"
          class="emp-input emp-draft-chat__input"
          rows="2"
          placeholder="追问草稿、澄清约束…（Enter 发送）"
          :disabled="reviewSending"
          @keydown.enter.exact.prevent="sendReview"
        />
        <button
          type="button"
          class="btn btn-sm btn-primary emp-draft-chat__send"
          :disabled="reviewSending || !reviewInput.trim()"
          @click="sendReview"
        >
          {{ reviewSending ? '发送中…' : '发送' }}
        </button>
      </div>
    </section>

    <!-- 流水线进度条 -->
    <div class="emp-draft-progress-track" role="progressbar" :aria-valuenow="doneCount" :aria-valuemax="STAGE_KEYS.length">
      <div
        v-for="k in STAGE_KEYS"
        :key="k"
        class="emp-draft-pip"
        :class="{
          'emp-draft-pip--done': stages[k].status === 'done',
          'emp-draft-pip--running': stages[k].status === 'running',
          'emp-draft-pip--error': stages[k].status === 'error',
        }"
        :title="STAGE_LABELS[k]"
      />
    </div>

    <!-- 进行中的子提示 -->
    <p v-if="progressMessages.length" class="emp-draft-progress-msg muted small">
      {{ progressMessages[progressMessages.length - 1] }}
    </p>

    <!-- 致命错误 -->
    <div v-if="status.phase === 'error' && status.fatalError" class="emp-draft-fatal" role="alert">
      <strong>生成失败：</strong>{{ status.fatalError }}
      <button type="button" class="btn btn-sm btn-primary emp-draft-retry" @click="$emit('retry')">重新生成</button>
    </div>

    <!-- 8 张模块卡片（仅在有数据时显示） -->
    <DraftStageCards
      v-if="status.phase !== 'idle'"
      :stages="stages"
      :progress-messages="progressMessages"
      :workflow-needs-sandbox="workflowNeedsSandbox"
      :sandbox-workflow-id="sandboxWorkflowId"
      :refine-loading="refineLoading"
      :refine-error="refineError"
      :refine-diff="refineDiff"
      @edit-json="editV2Json"
      @refine="openRefinePrompt"
    />

    <!-- JSON 编辑器弹窗 -->
    <div v-if="jsonEditTarget" class="emp-json-modal" @click.self="jsonEditTarget = null">
      <div class="emp-json-modal-inner">
        <h3 class="emp-json-modal-title">编辑 {{ jsonEditTarget }}</h3>
        <textarea v-model="jsonEditContent" class="emp-json-editor" rows="16" spellcheck="false" />
        <p v-if="jsonEditError" class="emp-card-err">{{ jsonEditError }}</p>
        <div class="emp-json-modal-actions">
          <button type="button" class="btn btn-primary" @click="applyJsonEdit">应用</button>
          <button type="button" class="btn" @click="jsonEditTarget = null">取消</button>
        </div>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <footer class="emp-draft-footer">
      <div v-if="publishError" class="emp-card-err">{{ publishError }}</div>
      <div class="emp-draft-footer-actions">
        <button
          type="button"
          class="btn btn-primary emp-publish-btn"
          :disabled="!canPublish || publishLoading"
          @click="publish"
        >
          {{ publishLoading ? '发布中…' : '一键发布到员工库' }}
        </button>
        <button
          type="button"
          class="btn emp-author-btn"
          :disabled="!canPublish"
          @click="openInAuthoring"
        >
          打开员工制作进一步调整
        </button>
        <button v-if="!embedded" type="button" class="btn btn-ghost" @click="$emit('close')">关闭</button>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：8 张模块卡片在 ./employee-ai-draft-review/DraftStageCards.vue，
// 草稿表单 / JSON 编辑 / AI 优化 / 发布 composables 在 ./employee-ai-draft-review/，样式在 ./employee-ai-draft-review/employeeAiDraftReview.css。
import { computed, provide, ref } from 'vue'
import { useWorkbenchStore } from '../../stores/workbench'
import type { PipelineStages } from '../../composables/useEmployeeAiDraft'
import DraftStageCards from './employee-ai-draft-review/DraftStageCards.vue'
import {
  badgeClassFor,
  badgeTextFor,
  cardClassFor,
  EMP_DRAFT_FORM_KEY,
  fmtJson as fmtJsonHelper,
  STAGE_KEYS,
  STAGE_LABELS,
} from './employee-ai-draft-review/employeeDraftReviewHelpers'
import { useDraftForm } from './employee-ai-draft-review/useDraftForm'
import { useV2JsonEditor } from './employee-ai-draft-review/useV2JsonEditor'
import { usePromptRefine } from './employee-ai-draft-review/usePromptRefine'
import { useDraftPublish } from './employee-ai-draft-review/useDraftPublish'

withDefaults(
  defineProps<{
    /** 嵌入侧栏时收紧布局并隐藏关闭按钮 */
    embedded?: boolean
  }>(),
  { embedded: false },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry'): void
  (e: 'published', modId: string): void
}>()

const wb = useWorkbenchStore()

const stages = wb.employeeDraftStages
const status = wb.employeeDraftStatus
const progressMessages = wb.employeeDraftProgressMessages
const reviewMessages = wb.employeeDraftReviewMessages
const reviewSending = wb.employeeDraftReviewSending

const reviewInput = ref('')

async function sendReview() {
  const t = reviewInput.value.trim()
  if (!t || wb.employeeDraftReviewSending) return
  reviewInput.value = ''
  await wb.submitEmployeeDraftReviewChat(t)
}

// ── draft (editable copy of pipeline output) ─────────────────────────────────

const { draft } = useDraftForm(stages)
provide(EMP_DRAFT_FORM_KEY, draft.value)

// ── stage metadata & card helpers（测试兼容面：既有测试经 setupState 访问） ──

const cardClass = (stage: keyof PipelineStages) => cardClassFor(stages, stage)
const badgeClass = (stage: keyof PipelineStages) => badgeClassFor(stages, stage)
const badgeText = (stage: keyof PipelineStages) => badgeTextFor(stages, stage)
const fmtJson = fmtJsonHelper

const doneCount = computed(() => STAGE_KEYS.filter((k) => stages[k].status === 'done').length)

const statusLabel = computed(() => {
  if (status.phase === 'idle') return '等待开始'
  if (status.phase === 'running') return `正在处理：${STAGE_LABELS[status.current] || status.current}…`
  if (status.phase === 'done') return '草稿已就绪，请检查后发布'
  return `失败：${status.fatalError}`
})

const canPublish = computed(() => status.phase === 'done' && !!status.manifest)

const workflowNeedsSandbox = computed(() => {
  const meta = (status.manifest as Record<string, unknown> | null)?.employee_config_v2 as
    | Record<string, unknown>
    | undefined
  return !!(meta?.metadata as Record<string, unknown> | undefined)?.workflow_needs_sandbox
})

const sandboxWorkflowId = computed(() => {
  const wfData = stages.resolve_workflow.data
  return wfData?.workflow_id ?? null
})

// ── JSON inline editor / AI refine / publish ─────────────────────────────────

const { jsonEditTarget, jsonEditContent, jsonEditError, v2Override, editV2Json, applyJsonEdit } = useV2JsonEditor(stages)

const { refineLoading, refineError, refineDiff, openRefinePrompt } = usePromptRefine(draft)

const { publishLoading, publishError, publish, openInAuthoring } = useDraftPublish({
  status,
  draft,
  v2Override,
  canPublish,
  emitPublished: (modId: string) => emit('published', modId),
})
</script>

<style scoped src="./employee-ai-draft-review/employeeAiDraftReview.css"></style>
