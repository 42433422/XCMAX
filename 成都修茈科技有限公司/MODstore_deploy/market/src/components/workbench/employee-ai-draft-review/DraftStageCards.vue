<script setup lang="ts">
/**
 * AI 制作草稿 · 8 张模块卡片与沙箱警告横幅。
 *
 * 由 EmployeeAiDraftReview.vue 模板块机械切分而来（行为与视觉保持不变）：
 * 可编辑草稿对象经 EMP_DRAFT_FORM_KEY 注入（与入口同一响应式对象，字段编辑行为不变），
 * JSON 编辑与 AI 优化交互经 emit 回到入口。
 */
import { inject } from 'vue'
import type { PipelineStages } from '../../../composables/useEmployeeAiDraft'
import {
  badgeClassFor,
  badgeTextFor,
  cardClassFor,
  EMP_DRAFT_FORM_KEY,
  fmtJson,
  STAGE_LABELS,
} from './employeeDraftReviewHelpers'
import type { DraftForm } from './employeeDraftReviewHelpers'

const props = defineProps<{
  stages: PipelineStages
  progressMessages: string[]
  workflowNeedsSandbox: boolean
  sandboxWorkflowId: number | null
  refineLoading: boolean
  refineError: string
  refineDiff: string
}>()

defineEmits<{
  (e: 'edit-json', field: 'perception' | 'memory' | 'actions'): void
  (e: 'refine'): void
}>()

const draft = inject(EMP_DRAFT_FORM_KEY) as DraftForm

const cardClass = (stage: keyof PipelineStages) => cardClassFor(props.stages, stage)
const badgeClass = (stage: keyof PipelineStages) => badgeClassFor(props.stages, stage)
const badgeText = (stage: keyof PipelineStages) => badgeTextFor(props.stages, stage)
</script>

<template>
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
        <button type="button" class="btn btn-sm emp-card-edit-btn" @click="$emit('edit-json', 'perception')">编辑 JSON</button>
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
        <button type="button" class="btn btn-sm emp-card-edit-btn" @click="$emit('edit-json', 'memory')">编辑 JSON</button>
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
        @click="$emit('refine')"
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
        <button type="button" class="btn btn-sm emp-card-edit-btn" @click="$emit('edit-json', 'actions')">编辑 JSON</button>
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

<style scoped src="./employeeAiDraftReview.css"></style>
