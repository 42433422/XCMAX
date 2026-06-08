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
    <template v-if="status.phase !== 'idle'">
      <!-- 1. 身份 -->
      <div class="emp-card" :class="cardClass('parse_intent')">
        <div class="emp-card-head">
          <span class="emp-card-icon">🪪</span>
          <span class="emp-card-label">{{ STAGE_LABELS.parse_intent }}</span>
          <span class="emp-card-badge" :class="badgeClass('parse_intent')">{{ badgeText('parse_intent') }}</span>
        </div>
        <template v-if="stages.parse_intent.data">
          <div class="emp-card-body">
            <div class="emp-field-row">
              <label>员工 ID</label>
              <input v-model="draft.id" class="emp-input" />
            </div>
            <div class="emp-field-row">
              <label>显示名</label>
              <input v-model="draft.name" class="emp-input" />
            </div>
            <div class="emp-field-row">
              <label>职能</label>
              <input v-model="draft.role" class="emp-input" />
            </div>
            <div class="emp-field-row">
              <label>场景</label>
              <textarea v-model="draft.scenario" class="emp-input emp-textarea" rows="2" />
            </div>
            <div class="emp-field-row emp-field-row--inline">
              <div>
                <label>行业</label>
                <input v-model="draft.industry" class="emp-input" style="width:120px" />
              </div>
              <div>
                <label>复杂度</label>
                <select v-model="draft.complexity" class="emp-input" style="width:100px">
                  <option value="low">简单</option>
                  <option value="medium">中等</option>
                  <option value="high">复杂</option>
                </select>
              </div>
            </div>
          </div>
        </template>
        <p v-else-if="stages.parse_intent.status === 'running'" class="emp-card-loading muted small">解析中…</p>
        <p v-else-if="stages.parse_intent.status === 'error'" class="emp-card-err">{{ stages.parse_intent.error }}</p>
      </div>

      <!-- 2. 工作流 -->
      <div class="emp-card" :class="cardClass('resolve_workflow')">
        <div class="emp-card-head">
          <span class="emp-card-icon">🔗</span>
          <span class="emp-card-label">{{ STAGE_LABELS.resolve_workflow }}</span>
          <span class="emp-card-badge" :class="badgeClass('resolve_workflow')">{{ badgeText('resolve_workflow') }}</span>
        </div>
        <template v-if="stages.resolve_workflow.data">
          <div class="emp-card-body">
            <p class="emp-card-desc">
              <template v-if="stages.resolve_workflow.data.workflow_id">
                已绑定工作流：<strong>{{ stages.resolve_workflow.data.workflow_name || `#${stages.resolve_workflow.data.workflow_id}` }}</strong>
                <span v-if="stages.resolve_workflow.data.generated" class="emp-tag emp-tag--new">AI 生成</span>
                <span v-else class="emp-tag emp-tag--match">匹配 {{ (stages.resolve_workflow.data.match_score * 100).toFixed(0) }}%</span>
              </template>
              <template v-else>
                <span class="muted small">未绑定工作流（可发布后在员工制作页关联）</span>
              </template>
            </p>
          </div>
        </template>
        <p v-else-if="stages.resolve_workflow.status === 'running'" class="emp-card-loading muted small">
          选型中…{{ progressMessages.length ? progressMessages[progressMessages.length - 1] : '' }}
        </p>
        <p v-else-if="stages.resolve_workflow.status === 'error'" class="emp-card-err">{{ stages.resolve_workflow.error }}</p>
      </div>

      <!-- 沙箱警告横幅 -->
      <div v-if="workflowNeedsSandbox" class="emp-sandbox-warn" role="alert">
        <span class="emp-sandbox-warn__icon">⚠️</span>
        <div class="emp-sandbox-warn__body">
          <strong>所选工作流尚未通过沙箱测试</strong>
          <p class="emp-sandbox-warn__desc">绑定的工作流（#{{ sandboxWorkflowId }}）需要先在工作流页面完成沙箱运行，否则员工制作页无法加载该工作流。</p>
        </div>
        <a
          v-if="sandboxWorkflowId"
          :href="`/market/#/workbench/shell/workflow/${sandboxWorkflowId}`"
          target="_blank"
          class="btn btn-sm emp-sandbox-warn__link"
        >去沙箱测试 →</a>
      </div>

      <!-- 3. 感知 -->
      <div class="emp-card" :class="cardClass('design_v2')">
        <div class="emp-card-head">
          <span class="emp-card-icon">👁</span>
          <span class="emp-card-label">感知（Perception）</span>
          <span class="emp-card-badge" :class="badgeClass('design_v2')">{{ badgeText('design_v2') }}</span>
        </div>
        <template v-if="stages.design_v2.data">
          <div class="emp-card-body">
            <pre class="emp-json">{{ fmtJson(stages.design_v2.data.perception) }}</pre>
            <button type="button" class="btn btn-sm emp-card-edit-btn" @click="editV2Json('perception')">编辑 JSON</button>
          </div>
        </template>
        <p v-else-if="stages.design_v2.status === 'running'" class="emp-card-loading muted small">设计中…</p>
        <p v-else-if="stages.design_v2.status === 'error'" class="emp-card-err">{{ stages.design_v2.error }}</p>
      </div>

      <!-- 4. 记忆 -->
      <div class="emp-card" :class="cardClass('design_v2')">
        <div class="emp-card-head">
          <span class="emp-card-icon">🧠</span>
          <span class="emp-card-label">记忆（Memory）</span>
          <span class="emp-card-badge" :class="badgeClass('design_v2')">{{ badgeText('design_v2') }}</span>
        </div>
        <template v-if="stages.design_v2.data">
          <div class="emp-card-body">
            <pre class="emp-json">{{ fmtJson(stages.design_v2.data.memory) }}</pre>
            <button type="button" class="btn btn-sm emp-card-edit-btn" @click="editV2Json('memory')">编辑 JSON</button>
          </div>
        </template>
      </div>

      <!-- 5. 认知 / System Prompt -->
      <div class="emp-card" :class="cardClass('design_v2')">
        <div class="emp-card-head">
          <span class="emp-card-icon">💬</span>
          <span class="emp-card-label">认知 · System Prompt</span>
          <span class="emp-card-badge" :class="badgeClass('design_v2')">{{ badgeText('design_v2') }}</span>
          <button
            v-if="stages.design_v2.data"
            type="button"
            class="btn btn-sm emp-refine-btn"
            :disabled="refineLoading"
            @click="openRefinePrompt"
          >
            {{ refineLoading ? '优化中…' : 'AI 优化' }}
          </button>
        </div>
        <template v-if="stages.design_v2.data">
          <div class="emp-card-body">
            <textarea
              v-model="draft.systemPrompt"
              class="emp-input emp-textarea emp-textarea--lg"
              rows="8"
              placeholder="System Prompt…"
            />
            <div v-if="refineError" class="emp-card-err">{{ refineError }}</div>
            <div v-if="refineDiff" class="emp-refine-diff muted small">改动说明：{{ refineDiff }}</div>
          </div>
        </template>
        <p v-else-if="stages.design_v2.status === 'running'" class="emp-card-loading muted small">设计中…</p>
      </div>

      <!-- 6. 技能 -->
      <div class="emp-card" :class="cardClass('suggest_skills')">
        <div class="emp-card-head">
          <span class="emp-card-icon">🛠</span>
          <span class="emp-card-label">{{ STAGE_LABELS.suggest_skills }}</span>
          <span class="emp-card-badge" :class="badgeClass('suggest_skills')">{{ badgeText('suggest_skills') }}</span>
        </div>
        <template v-if="stages.suggest_skills.data && stages.suggest_skills.data.length">
          <div class="emp-card-body emp-skills-list">
            <span
              v-for="(sk, idx) in stages.suggest_skills.data"
              :key="idx"
              class="emp-skill-chip"
              :title="sk.brief"
            >
              {{ sk.name }}
              <span class="emp-skill-chip__unverified" title="AI 建议，不影响运行时">草稿</span>
            </span>
            <a class="btn btn-sm emp-skill-make-btn" href="/market/workbench?gear=vibe" target="_blank">制作技能 →</a>
          </div>
        </template>
        <p v-else-if="stages.suggest_skills.status === 'running'" class="emp-card-loading muted small">推荐中…</p>
        <p v-else-if="stages.suggest_skills.status === 'error'" class="muted small">{{ stages.suggest_skills.error }}</p>
        <p v-else-if="stages.suggest_skills.status === 'done'" class="muted small">暂无技能建议</p>
      </div>

      <!-- 7. 行动 -->
      <div class="emp-card" :class="cardClass('design_v2')">
        <div class="emp-card-head">
          <span class="emp-card-icon">⚡</span>
          <span class="emp-card-label">行动（Actions）</span>
          <span class="emp-card-badge" :class="badgeClass('design_v2')">{{ badgeText('design_v2') }}</span>
        </div>
        <template v-if="stages.design_v2.data">
          <div class="emp-card-body">
            <div class="emp-handlers">
              <span
                v-for="h in (stages.design_v2.data.actions as Record<string,unknown>)?.handlers as string[] ?? []"
                :key="h"
                class="emp-handler-chip"
              >{{ h }}</span>
            </div>
            <button type="button" class="btn btn-sm emp-card-edit-btn" @click="editV2Json('actions')">编辑 JSON</button>
          </div>
        </template>
      </div>

      <!-- 8. 定价 -->
      <div class="emp-card" :class="cardClass('suggest_pricing')">
        <div class="emp-card-head">
          <span class="emp-card-icon">💴</span>
          <span class="emp-card-label">{{ STAGE_LABELS.suggest_pricing }}</span>
          <span class="emp-card-badge" :class="badgeClass('suggest_pricing')">{{ badgeText('suggest_pricing') }}</span>
        </div>
        <template v-if="stages.suggest_pricing.data">
          <div class="emp-card-body emp-pricing">
            <div class="emp-field-row emp-field-row--inline">
              <div>
                <label>档位</label>
                <select v-model="draft.pricingTier" class="emp-input" style="width:120px">
                  <option value="free">免费</option>
                  <option value="basic">Basic</option>
                  <option value="standard">Standard</option>
                  <option value="pro">Pro</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </div>
              <div>
                <label>月费（元）</label>
                <input v-model.number="draft.pricingCny" type="number" min="0" class="emp-input" style="width:80px" />
              </div>
              <div>
                <label>计费周期</label>
                <select v-model="draft.pricingPeriod" class="emp-input" style="width:90px">
                  <option value="month">月付</option>
                  <option value="year">年付</option>
                  <option value="once">买断</option>
                </select>
              </div>
            </div>
            <p v-if="stages.suggest_pricing.data.reasoning" class="muted small emp-pricing-reason">
              AI 建议理由：{{ stages.suggest_pricing.data.reasoning }}
            </p>
          </div>
        </template>
        <p v-else-if="stages.suggest_pricing.status === 'running'" class="emp-card-loading muted small">定价建议中…</p>
        <p v-else-if="stages.suggest_pricing.status === 'error'" class="muted small">{{ stages.suggest_pricing.error }}</p>
      </div>
    </template>

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
import { ref, computed, watch } from 'vue'
import { useWorkbenchStore } from '../../stores/workbench'
import type { PipelineStages, SkillData } from '../../composables/useEmployeeAiDraft'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'

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
function authJsonHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const t = getAccessToken()
  if (t) h.Authorization = `Bearer ${t}`
  return h
}

async function sendReview() {
  const t = reviewInput.value.trim()
  if (!t || wb.employeeDraftReviewSending) return
  reviewInput.value = ''
  await wb.submitEmployeeDraftReviewChat(t)
}

// ── stage metadata ────────────────────────────────────────────────────────────

const STAGE_KEYS = ['parse_intent', 'resolve_workflow', 'design_v2', 'suggest_skills', 'suggest_pricing', 'assemble'] as const

const STAGE_LABELS: Record<string, string> = {
  parse_intent: '身份解析',
  resolve_workflow: '工作流选型',
  design_v2: '配置设计',
  suggest_skills: '技能建议',
  suggest_pricing: '定价建议',
  assemble: '清单装配',
}

// ── draft (editable copy of pipeline output) ─────────────────────────────────

const draft = ref({
  id: '',
  name: '',
  role: '',
  scenario: '',
  industry: '',
  complexity: 'medium',
  systemPrompt: '',
  pricingTier: 'free',
  pricingCny: 0,
  pricingPeriod: 'month',
  skills: [] as SkillData[],
})

watch(
  () => stages.suggest_skills.data,
  (list) => {
    if (!list || !list.length) return
    draft.value.skills = list.map((s) => ({
      name: s.name,
      brief: s.brief,
      unverified: Boolean(s.unverified),
    }))
  },
  { immediate: true },
)

watch(
  () => stages.parse_intent.data,
  (d) => {
    if (!d) return
    draft.value.id = d.id
    draft.value.name = d.name
    draft.value.role = d.role
    draft.value.scenario = d.scenario
    draft.value.industry = d.industry
    draft.value.complexity = d.complexity
  },
  { immediate: true },
)

watch(
  () => stages.design_v2.data,
  (d) => {
    if (!d) return
    const agent = (d.cognition as Record<string, unknown>)?.agent as Record<string, unknown>
    if (agent?.system_prompt) draft.value.systemPrompt = String(agent.system_prompt)
  },
  { immediate: true },
)

watch(
  () => stages.suggest_pricing.data,
  (d) => {
    if (!d) return
    draft.value.pricingTier = d.tier
    draft.value.pricingCny = d.cny
    draft.value.pricingPeriod = d.period
  },
  { immediate: true },
)

// ── computed helpers ──────────────────────────────────────────────────────────

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

function cardClass(stage: keyof PipelineStages) {
  const s = stages[stage].status
  return {
    'emp-card--running': s === 'running',
    'emp-card--done': s === 'done',
    'emp-card--error': s === 'error',
  }
}

function badgeClass(stage: keyof PipelineStages) {
  const s = stages[stage].status
  return {
    'emp-badge--running': s === 'running',
    'emp-badge--done': s === 'done',
    'emp-badge--error': s === 'error',
  }
}

function badgeText(stage: keyof PipelineStages) {
  const map: Record<string, string> = { idle: '', running: '处理中', done: '✓', error: '✗' }
  return map[stages[stage].status] ?? ''
}

function fmtJson(val: unknown) {
  try {
    return JSON.stringify(val, null, 2)
  } catch {
    return String(val)
  }
}

// ── JSON inline editor ────────────────────────────────────────────────────────

const jsonEditTarget = ref<string | null>(null)
const jsonEditContent = ref('')
const jsonEditError = ref('')
const v2Override = ref<Record<string, unknown>>({})

function editV2Json(field: 'perception' | 'memory' | 'actions') {
  const d = stages.design_v2.data
  if (!d) return
  jsonEditTarget.value = field
  const current = v2Override.value[field] ?? d[field]
  jsonEditContent.value = JSON.stringify(current, null, 2)
  jsonEditError.value = ''
}

function applyJsonEdit() {
  try {
    const parsed = JSON.parse(jsonEditContent.value)
    if (jsonEditTarget.value) {
      v2Override.value[jsonEditTarget.value] = parsed
    }
    jsonEditTarget.value = null
    jsonEditError.value = ''
  } catch (e: unknown) {
    jsonEditError.value = `JSON 格式错误: ${(e as Error)?.message}`
  }
}

// ── AI refine prompt ──────────────────────────────────────────────────────────

const refineLoading = ref(false)
const refineError = ref('')
const refineDiff = ref('')
const refineInstruction = ref('')

async function openRefinePrompt() {
  const instruction = window.prompt('优化指令（例如：增加拒绝服务的边界说明）', '')
  if (!instruction) return
  refineLoading.value = true
  refineError.value = ''
  refineDiff.value = ''
  try {
    const res = await fetch('/api/workbench/employee-ai/refine-prompt', {
      method: 'POST',
      headers: authJsonHeaders(),
      body: JSON.stringify({
        current_prompt: draft.value.systemPrompt,
        instruction,
        role_context: `${draft.value.role} - ${draft.value.scenario}`,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    draft.value.systemPrompt = data.improved_prompt
    refineDiff.value = data.diff_explanation || ''
  } catch (e: unknown) {
    refineError.value = `优化失败: ${(e as Error)?.message || String(e)}`
  } finally {
    refineLoading.value = false
  }
}

// ── publish ───────────────────────────────────────────────────────────────────

const publishLoading = ref(false)
const publishError = ref('')

function _buildManifest(): Record<string, unknown> {
  const base = JSON.parse(JSON.stringify(status.manifest || {})) as Record<string, unknown>
  base.id = draft.value.id || base.id
  base.name = draft.value.name || base.name
  base.description = draft.value.scenario || base.description
  base.industry = draft.value.industry || base.industry

  const emp = (base.employee as Record<string, unknown>) || {}
  emp.label = draft.value.name || String(emp.label || '')
  base.employee = emp

  const v2 = (base.employee_config_v2 as Record<string, unknown>) || {}
  const identity = (v2.identity as Record<string, unknown>) || {}
  identity.id = draft.value.id
  identity.name = draft.value.name
  identity.description = draft.value.scenario
  v2.identity = identity

  if (v2Override.value.perception) v2.perception = v2Override.value.perception
  if (v2Override.value.memory) v2.memory = v2Override.value.memory
  if (v2Override.value.actions) v2.actions = v2Override.value.actions

  const cog = (v2.cognition as Record<string, unknown>) || {}
  const agent = (cog.agent as Record<string, unknown>) || {}
  agent.system_prompt = draft.value.systemPrompt
  cog.agent = agent
  if (draft.value.skills.length) {
    cog.skills = draft.value.skills.map((s) => ({
      name: s.name,
      brief: s.brief,
      unverified: s.unverified,
    }))
  }
  v2.cognition = cog

  const meta = (v2.metadata as Record<string, unknown>) || {}
  if (draft.value.skills.length) {
    meta.suggested_skills = draft.value.skills.map((s) => ({
      name: s.name,
      brief: s.brief,
      unverified: s.unverified,
    }))
  }
  if (draft.value.pricingCny > 0 || draft.value.pricingTier !== 'free') {
    meta.suggested_pricing = {
      tier: draft.value.pricingTier,
      cny: draft.value.pricingCny,
      period: draft.value.pricingPeriod,
    }
  }
  v2.metadata = meta
  base.employee_config_v2 = v2

  return base
}

async function publish() {
  if (!canPublish.value) return
  publishLoading.value = true
  publishError.value = ''
  try {
    const manifest = _buildManifest()
    const res = await fetch('/api/mods/ai-scaffold', {
      method: 'POST',
      headers: authJsonHeaders(),
      body: JSON.stringify({
        brief: `${draft.value.role}: ${draft.value.scenario}`,
        suggested_id: draft.value.id,
        replace: true,
        _manifest_override: manifest,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail || body?.error || `HTTP ${res.status}`)
    }
    const data = await res.json()
    const modId = data?.id || draft.value.id
    emit('published', String(modId))
  } catch (e: unknown) {
    publishError.value = `发布失败: ${(e as Error)?.message || String(e)}`
  } finally {
    publishLoading.value = false
  }
}

function openInAuthoring() {
  if (!canPublish.value) return
  const id = draft.value.id
  if (!id) return
  // Persist full manifest so WorkbenchShell can hydrate without an API round-trip
  const manifest = _buildManifest()
  sessionStorage.setItem('modstore_employee_prefill', JSON.stringify(manifest))
  window.open(`/market/#/workbench/shell/employee/${encodeURIComponent(id)}?fromAi=1`, '_blank')
}
</script>

<style scoped>
.emp-draft-review {
  background: var(--wb-surface-elevated, var(--surface-2, #1a1a2e));
  border: 1px solid var(--wb-border-default, var(--border, #2a2a4a));
  border-radius: var(--wb-radius-lg, 12px);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 90vh;
  overflow-y: auto;
}

.emp-draft-review--embedded {
  max-height: min(52vh, 560px);
  padding: 12px 14px;
  flex-shrink: 1;
  min-height: 0;
}

.emp-draft-chat {
  border: 1px solid var(--wb-border-muted, var(--border, #2a2a4a));
  border-radius: var(--wb-radius-md, 10px);
  padding: 10px 12px;
  background: var(--wb-surface-sunken, rgba(0, 0, 0, 0.2));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.emp-draft-chat__head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.emp-draft-chat__title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--wb-text-secondary, rgba(255, 255, 255, 0.82));
}

.emp-draft-chat__hint {
  font-size: 0.72rem;
}

.emp-draft-chat__thread {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.emp-draft-chat__msg {
  font-size: 0.78rem;
  line-height: 1.45;
  padding: 6px 8px;
  border-radius: 8px;
  margin: 0;
}

.emp-draft-chat__msg--user {
  align-self: flex-end;
  background: var(--wb-accent-soft, rgba(99, 102, 241, 0.2));
  color: var(--wb-text-primary, #f8fafc);
}

.emp-draft-chat__msg--assistant {
  align-self: flex-start;
  background: var(--wb-surface-overlay, rgba(255, 255, 255, 0.06));
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.88));
}

.emp-draft-chat__composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.emp-draft-chat__input {
  flex: 1;
  min-width: 0;
}

.emp-draft-chat__send {
  flex-shrink: 0;
}

.emp-draft-head { display: flex; flex-direction: column; gap: 4px; }
.emp-draft-title-row { display: flex; align-items: center; justify-content: space-between; }
.emp-draft-title { margin: 0; font-size: 1.1rem; font-weight: 600; }
.emp-draft-sub { margin: 0; }
.emp-draft-close {
  background: none; border: none; cursor: pointer;
  font-size: 1.4rem; color: var(--text-muted, #aaa); line-height: 1;
}
.emp-draft-close:hover { color: var(--text, #fff); }

.emp-draft-progress-track { display: flex; gap: 6px; }
.emp-draft-pip {
  flex: 1; height: 4px; border-radius: 2px;
  background: var(--border, #2a2a4a);
  transition: background 0.3s;
}
.emp-draft-pip--running { background: var(--accent, #6c63ff); animation: pulse 1.2s infinite; }
.emp-draft-pip--done { background: var(--success, #4caf50); }
.emp-draft-pip--error { background: var(--error, #e53935); }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.emp-draft-progress-msg { margin: 0; }
.emp-draft-fatal {
  background: var(--error-surface, #2d1a1a); border: 1px solid var(--error, #e53935);
  border-radius: 8px; padding: 12px; display: flex; align-items: center; gap: 12px;
}
.emp-draft-retry { margin-left: auto; }

/* cards */
.emp-card {
  border: 1px solid var(--border, #2a2a4a);
  border-radius: 10px; padding: 14px;
  transition: border-color 0.2s;
}
.emp-card--running { border-color: var(--accent, #6c63ff); }
.emp-card--done { border-color: var(--success, #4caf50); }
.emp-card--error { border-color: var(--error, #e53935); }

.emp-card-head {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px; flex-wrap: wrap;
}
.emp-card-icon { font-size: 1.1rem; }
.emp-card-label { font-weight: 600; flex: 1; }
.emp-card-badge {
  font-size: 0.72rem; padding: 2px 7px; border-radius: 10px;
  background: var(--surface-3, #222240); color: var(--text-muted, #aaa);
}
.emp-badge--running { background: var(--accent-dim, #2a2050); color: var(--accent, #6c63ff); }
.emp-badge--done { background: var(--success-dim, #1a2d1a); color: var(--success, #4caf50); }
.emp-badge--error { background: var(--error-dim, #2d1a1a); color: var(--error, #e53935); }

.emp-card-body { display: flex; flex-direction: column; gap: 8px; }
.emp-card-loading, .emp-card-desc { margin: 0; }
.emp-card-err { color: var(--error, #e53935); margin: 0; font-size: 0.85rem; }

.emp-field-row { display: flex; flex-direction: column; gap: 4px; }
.emp-field-row label { font-size: 0.78rem; color: var(--text-muted, #aaa); }
.emp-field-row--inline { flex-direction: row; gap: 16px; }

.emp-input {
  background: var(--surface-3, #1e1e3a); border: 1px solid var(--border, #2a2a4a);
  border-radius: 6px; color: var(--text, #e0e0e0); padding: 6px 10px;
  font-size: 0.9rem; width: 100%; box-sizing: border-box;
}
.emp-input:focus { outline: none; border-color: var(--accent, #6c63ff); }
.emp-textarea { resize: vertical; font-family: inherit; }
.emp-textarea--lg { min-height: 160px; }

.emp-json {
  background: var(--surface-3, #1e1e3a); border-radius: 6px;
  padding: 8px 10px; font-size: 0.8rem; overflow: auto;
  max-height: 120px; white-space: pre-wrap; word-break: break-all; margin: 0;
}
.emp-card-edit-btn { align-self: flex-start; }

.emp-refine-btn { margin-left: auto; }
.emp-refine-diff { margin: 0; }

/* skills */
.emp-skills-list { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }
.emp-skill-chip {
  background: var(--surface-3, #1e1e3a); border: 1px solid var(--border, #2a2a4a);
  border-radius: 16px; padding: 4px 10px; font-size: 0.82rem;
  display: inline-flex; align-items: center; gap: 4px;
}
.emp-skill-chip__unverified {
  font-size: 0.68rem; opacity: 0.6;
  background: var(--warn-dim, #2d2a1a); border-radius: 8px; padding: 1px 5px;
}
.emp-skill-make-btn { margin-left: 4px; }

/* handlers */
.emp-handlers { display: flex; flex-wrap: wrap; gap: 6px; }
.emp-handler-chip {
  background: var(--accent-dim, #2a2050); color: var(--accent, #6c63ff);
  border-radius: 12px; padding: 3px 10px; font-size: 0.82rem;
}

/* pricing */
.emp-pricing-reason { margin: 4px 0 0; }

/* tags */
.emp-tag {
  font-size: 0.7rem; border-radius: 8px; padding: 1px 6px; margin-left: 4px;
}
.emp-tag--new { background: var(--accent-dim, #2a2050); color: var(--accent, #6c63ff); }
.emp-tag--match { background: var(--success-dim, #1a2d1a); color: var(--success, #4caf50); }

/* JSON modal */
.emp-json-modal {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
}
.emp-json-modal-inner {
  background: var(--surface-2, #1a1a2e); border: 1px solid var(--border, #2a2a4a);
  border-radius: 12px; padding: 20px; width: min(600px, 90vw);
  display: flex; flex-direction: column; gap: 10px;
}
.emp-json-modal-title { margin: 0; font-size: 1rem; }
.emp-json-editor {
  background: var(--surface-3, #1e1e3a); border: 1px solid var(--border, #2a2a4a);
  border-radius: 6px; color: var(--text, #e0e0e0); font-family: monospace;
  font-size: 0.85rem; padding: 10px; width: 100%; box-sizing: border-box; resize: vertical;
}
.emp-json-modal-actions { display: flex; gap: 8px; justify-content: flex-end; }

/* sandbox warning banner */
.emp-sandbox-warn {
  display: flex; align-items: flex-start; gap: 10px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 10px; padding: 12px 14px;
}
.emp-sandbox-warn__icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }
.emp-sandbox-warn__body { flex: 1; }
.emp-sandbox-warn__body strong { font-size: 0.88rem; color: #fde68a; }
.emp-sandbox-warn__desc { margin: 4px 0 0; font-size: 0.8rem; color: rgba(253, 230, 138, 0.75); line-height: 1.5; }
.emp-sandbox-warn__link {
  flex-shrink: 0; align-self: center;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fde68a; font-size: 0.78rem;
  padding: 5px 10px; border-radius: 8px; text-decoration: none; white-space: nowrap;
}
.emp-sandbox-warn__link:hover { background: rgba(245, 158, 11, 0.25); }

/* footer */
.emp-draft-footer { border-top: 1px solid var(--border, #2a2a4a); padding-top: 14px; }
.emp-draft-footer-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.emp-publish-btn { min-width: 160px; }
</style>
