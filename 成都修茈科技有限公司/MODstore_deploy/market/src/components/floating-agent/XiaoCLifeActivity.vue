<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElTimeline, ElTimelineItem } from 'element-plus/es/components/timeline/index'
import './xiaocLife.css'
import { xiaocStateLabel, type XiaoCLifePolicy, type XiaoCPortfolioLimits } from '../../application/xiaocLifeApi'
import { useXiaoCLife } from '../../composables/useXiaoCLife'
import XiaoCLifeTaskBudget from './XiaoCLifeTaskBudget.vue'
import XiaoCLifeProposal from './XiaoCLifeProposal.vue'

const props = defineProps<{ owner: number }>()
const life = useXiaoCLife(() => props.owner)
const editing = ref(false)
const draft = ref<XiaoCLifePolicy | null>(null)
const expiresAt = ref('')
const expectedRevision = ref(0)
const formError = ref('')
const notice = ref('')
const taskBudgetPolicy = ref<XiaoCLifePolicy | null>(null)
const taskBudgetRevision = ref(0)
const reviewing = ref('')
const canPromote = computed(
  () =>
    !!life.state?.policy.portfolio_limits &&
    !!life.state.policy.employee_id &&
    life.state.owner_user_id === props.owner &&
    Date.parse(life.state.policy.portfolio_limits.expires_at) > Date.now(),
)
const assessment = computed(() => {
  const value = life.state?.self_model
  return typeof value?.title === 'string' && typeof value.description === 'string'
    ? { title: value.title, description: value.description }
    : null
})
const dateTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' })

function formatTime(value: string | null | undefined) {
  const time = value ? Date.parse(value) : NaN
  return Number.isFinite(time) ? dateTime.format(time) : '尚未安排'
}

function toLocalInput(value: string | null) {
  const date = value ? new Date(value) : null
  if (!date || !Number.isFinite(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function editPolicy() {
  if (!life.state) return
  draft.value = { ...life.state.policy }
  expiresAt.value = toLocalInput(life.state.policy.authorization_expires_at)
  expectedRevision.value = life.state.revision
  formError.value = ''
  notice.value = ''
  editing.value = true
}

function setPolicyNumber(
  key: 'daily_token_limit' | 'daily_cycle_limit' | 'exploration_percent' | 'wake_interval_seconds',
  value: number | undefined,
) {
  if (!draft.value) return
  const minimum = { daily_token_limit: 0, daily_cycle_limit: 1, exploration_percent: 0, wake_interval_seconds: 60 }
  draft.value[key] = value ?? minimum[key]
}

async function savePolicy() {
  if (!draft.value) return
  formError.value = ''
  const expiry = expiresAt.value ? new Date(expiresAt.value).getTime() : NaN
  if (expiresAt.value && (!Number.isFinite(expiry) || expiry <= Date.now() || expiry > Date.now() + 31 * 86_400_000)) {
    formError.value = '授权到期时间须在未来 31 天内。'
    return
  }
  if (draft.value.daily_token_limit > 0 && !Number.isFinite(expiry)) {
    formError.value = '开启后台模型预算时，请填写授权到期时间。'
    return
  }
  const saved = await life.save(
    {
      policy: {
        ...draft.value,
        authorization_expires_at: Number.isFinite(expiry) ? new Date(expiry).toISOString() : null,
      },
    },
    expectedRevision.value,
  )
  if (saved) {
    editing.value = false
    notice.value = '企业预算设置已保存；实际运行以状态与执行回执为准。'
  }
}

function domainLabel(domain: string) {
  return (
    (
      {
        enterprise: '企业任务',
        business: '企业任务',
        exploration: '自主探索',
        reflection: '自身改进',
        self_improvement: '自身改进',
      } as Record<string, string>
    )[domain] ?? '目标'
  )
}

function eventKind(kind: string) {
  return (
    (
      {
        enterprise: '企业研判',
        cognition: '自主思考',
        exploration: '自主探索',
        reflection: '自身复盘',
        policy: '设置变更',
        execution: '任务执行',
        reconciliation: '用量核对',
      } as Record<string, string>
    )[kind] ?? kind
  )
}

function editTaskBudget() {
  if (!life.state) return
  taskBudgetPolicy.value = { ...life.state.policy }
  taskBudgetRevision.value = life.state.revision
}

async function saveTaskBudget(value: { employee_id: string; portfolio_limits: XiaoCPortfolioLimits; task_input: Record<string, unknown> }) {
  if (!taskBudgetPolicy.value) return
  if (await life.save({ policy: { ...taskBudgetPolicy.value, ...value } }, taskBudgetRevision.value)) {
    taskBudgetPolicy.value = null
    notice.value = '企业任务模板已保存；每个新提案仍需分别审核批准。'
  }
}

async function promote(goalId: string) {
  if (!canPromote.value) return
  notice.value = ''
  if (await life.promote(goalId)) notice.value = '已转成待审核企业提案，尚未批准或执行。'
}
</script>

<template>
  <section
    class="life-activity"
    v-bind="{ 'data-xiaoc-control-plane': '' }"
    aria-label="小 C 自主状态"
    :aria-busy="life.loading || life.saving"
  >
    <p class="xiaoc-muted">企业只有一个小 C。自主模式调节行动范围；记忆与经历持续保留。</p>
    <div class="xiaoc-toolbar">
      <button type="button" :disabled="life.loading || life.saving" @click="life.refresh()">刷新状态</button>
      <button type="button" :disabled="!life.state || life.saving" @click="editPolicy">设置预算</button>
      <button type="button" :disabled="!life.state || life.saving" @click="editTaskBudget">企业任务模板</button>
    </div>
    <p v-if="life.error" class="xiaoc-error" role="alert">{{ life.error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="life.state">
      <dl class="life-facts">
        <dt>当前状态</dt>
        <dd>{{ life.error ? '待同步' : life.state.paused ? '自主活动已暂停' : xiaocStateLabel(life.state.status) }}</dd>
        <dt>当前使命</dt>
        <dd>{{ life.state.mission || '尚未设置' }}</dd>
        <dt>下一次唤醒</dt>
        <dd>{{ formatTime(life.state.next_wake_at) }}</dd>
        <dt>今日 tokens</dt>
        <dd>
          {{ life.state.budget.used_tokens }} 已用 · {{ life.state.budget.reserved_tokens }} 预留 /
          {{ life.state.policy.daily_token_limit }} 上限（北京时间）
        </dd>
        <dt>今日自主轮次</dt>
        <dd>{{ life.state.budget.cycles }} / {{ life.state.policy.daily_cycle_limit }}</dd>
        <dt>自主探索</dt>
        <dd>{{ life.state.budget.exploration_tokens }} tokens · 预算占比 {{ life.state.policy.exploration_percent }}%</dd>
        <dt>授权到期</dt>
        <dd>
          {{ life.state.policy.authorization_expires_at ? formatTime(life.state.policy.authorization_expires_at) : '未授权后台模型消费' }}
        </dd>
      </dl>
      <ul v-if="life.state.blockers.length" class="life-blockers" aria-label="运行等待原因">
        <li v-for="blocker in life.state.blockers" :key="blocker">{{ blocker }}</li>
      </ul>

      <ElDialog
        v-model="editing"
        title="小 C 自主思考预算"
        width="min(520px, calc(100vw - 24px))"
        :z-index="12120"
        append-to-body
        :close-on-click-modal="false"
        :close-on-press-escape="!life.saving"
        :show-close="!life.saving"
      >
        <div v-if="draft" v-bind="{ 'data-xiaoc-control-plane': '' }" @submit.prevent="savePolicy">
          <ElForm class="life-policy" label-position="top">
            <p>
              由当前管理员授权使用平台额度，思考和探索共用每日总额度；不扣管理员个人钱包。提高等级不会自动开通预算；0 表示停止新增模型消费。
            </p>
            <ElFormItem label="每日模型 token 上限">
              <ElInputNumber
                :model-value="draft.daily_token_limit"
                @update:model-value="setPolicyNumber('daily_token_limit', $event)"
                :min="0"
                :max="1000000"
                :step="1000"
                :precision="0"
                :disabled="life.saving"
                v-bind="{ ariaLabel: '每日模型 token 上限' }"
              />
            </ElFormItem>
            <ElFormItem label="每日自主轮次上限">
              <ElInputNumber
                :model-value="draft.daily_cycle_limit"
                @update:model-value="setPolicyNumber('daily_cycle_limit', $event)"
                :min="1"
                :max="96"
                :precision="0"
                :disabled="life.saving"
                v-bind="{ ariaLabel: '每日自主轮次上限' }"
              />
            </ElFormItem>
            <ElFormItem label="自主探索预算占比（%）">
              <ElInputNumber
                :model-value="draft.exploration_percent"
                @update:model-value="setPolicyNumber('exploration_percent', $event)"
                :min="0"
                :max="50"
                :precision="0"
                :disabled="life.saving"
                v-bind="{ ariaLabel: '自主探索预算占比' }"
              />
            </ElFormItem>
            <ElFormItem label="唤醒间隔（秒）">
              <ElInputNumber
                :model-value="draft.wake_interval_seconds"
                @update:model-value="setPolicyNumber('wake_interval_seconds', $event)"
                :min="60"
                :max="86400"
                :step="60"
                :precision="0"
                :disabled="life.saving"
                v-bind="{ ariaLabel: '唤醒间隔秒数' }"
              />
            </ElFormItem>
            <ElFormItem label="L6 自身改进验收方案">
              <input
                v-model="draft.retort_template_id"
                type="text"
                maxlength="100"
                aria-label="自身改进验收方案编号"
                :disabled="life.saving"
                placeholder="已配置的改进验收方案编号"
              />
              <p class="xiaoc-muted">有来源的反思将进入这个方案的原审核流程；工程执行继续使用已批准的公司预算。</p>
            </ElFormItem>
            <ElFormItem label="授权到期时间（本地时间，最多 31 天）">
              <input v-model="expiresAt" type="datetime-local" aria-label="授权到期时间" :disabled="life.saving" />
            </ElFormItem>
            <p v-if="formError || life.error" class="xiaoc-error" role="alert">{{ formError || life.error }}</p>
            <div class="xiaoc-toolbar">
              <button type="submit" :disabled="life.saving">保存预算授权</button>
              <button type="button" :disabled="life.saving" @click="editing = false">取消</button>
            </div>
          </ElForm>
        </div>
      </ElDialog>

      <XiaoCLifeTaskBudget
        v-if="taskBudgetPolicy"
        :policy="taskBudgetPolicy"
        :busy="life.saving"
        :error="life.error"
        @close="taskBudgetPolicy = null"
        @save="saveTaskBudget"
      />
      <XiaoCLifeProposal v-if="reviewing" :decision-id="reviewing" @close="reviewing = ''" @changed="life.refresh()" />

      <h3>企业任务与自主探索</h3>
      <ul v-if="life.state.goals.length" class="life-goals">
        <li v-for="goal in life.state.goals" :key="goal.id">
          <span class="xiaoc-muted">{{ domainLabel(goal.domain) }} · {{ xiaocStateLabel(goal.status) }}</span>
          <p>{{ goal.title }}</p>
          <p v-if="goal.description" class="xiaoc-muted">{{ goal.description }}</p>
          <p v-if="goal.retort_request_id" class="xiaoc-muted">
            原改进任务：{{ goal.retort_request_id }} · 可在改进闭环中审核与查看发布回执。
          </p>
          <div class="xiaoc-toolbar">
            <button v-if="goal.decision_id" type="button" @click="reviewing = String(goal.decision_id)">
              查看企业提案 {{ goal.decision_id }}
            </button>
            <button v-else-if="!goal.retort_request_id" type="button" :disabled="!canPromote || life.saving" @click="promote(goal.id)">
              转为企业提案
            </button>
          </div>
          <small v-if="!goal.decision_id && !goal.retort_request_id && !canPromote" class="xiaoc-muted"
            >由预算授权管理员设置有效的企业任务模板后，可转为提案。</small
          >
          <details v-if="goal.evidence_refs?.length">
            <summary>依据</summary>
            <ul>
              <li v-for="evidence in goal.evidence_refs" :key="evidence">{{ evidence }}</li>
            </ul>
          </details>
        </li>
      </ul>
      <p v-else class="xiaoc-muted">还没有记录目标。</p>

      <h3>正在关注</h3>
      <ul v-if="life.state.interests.length" class="life-interests">
        <li v-for="interest in life.state.interests" :key="interest.topic">{{ interest.topic }}</li>
      </ul>
      <p v-else class="xiaoc-muted">兴趣会随真实经历逐步积累。</p>

      <template v-if="assessment"
        ><h3>自我评估 · 待核验</h3>
        <strong>{{ assessment.title }}</strong>
        <p>{{ assessment.description }}</p></template
      >

      <h3>经历与执行回执</h3>
      <ElTimeline v-if="life.state.events.length">
        <ElTimelineItem v-for="event in life.state.events" :key="event.id" :timestamp="formatTime(event.created_at)" placement="top">
          <p>{{ event.summary }}</p>
          <small
            >{{ eventKind(event.kind) }} · {{ xiaocStateLabel(event.status) }}<template v-if="event.model"> · {{ event.model }}</template
            ><template v-if="event.actual_tokens != null"> · {{ event.actual_tokens }} tokens</template></small
          >
          <details v-if="event.evidence_refs?.length">
            <summary>执行依据</summary>
            <ul>
              <li v-for="evidence in event.evidence_refs" :key="evidence">{{ evidence }}</li>
            </ul>
          </details>
        </ElTimelineItem>
      </ElTimeline>
      <p v-else class="xiaoc-muted">还没有自主活动回执。</p>
      <p class="xiaoc-muted life-footnote">L1–L6 是运行模式。已提出、已排队和已验证分别按真实回执显示。</p>
    </template>
    <p v-else-if="!life.loading && !life.error" class="xiaoc-muted">尚未读取企业小 C 状态。</p>
  </section>
</template>

<style scoped>
.life-activity {
  --el-text-color-regular: inherit;
  --el-text-color-primary: inherit;
  --el-text-color-secondary: var(--xiaoc-muted);
}
.life-facts {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 7px 12px;
}
.life-facts dt {
  color: var(--xiaoc-muted);
}
.life-facts dd {
  margin: 0;
}
.life-blockers {
  color: var(--xiaoc-alert);
  padding-left: 18px;
}
.life-policy {
  --xiaoc-border: #cdd6e2;
  --xiaoc-bg: #f2f6fc;
  --xiaoc-alert: #8a311d;
  color: #18283d;
  padding: 10px;
  max-height: 70vh;
  overflow: auto;
}
.life-policy button {
  border: 1px solid #c5d1e3;
  border-radius: 6px;
  background: #f5f8fc;
  color: #184994;
  padding: 6px 10px;
  font: inherit;
  cursor: pointer;
}
.life-policy .xiaoc-toolbar {
  display: flex;
  gap: 8px;
}
.life-policy .xiaoc-error {
  color: var(--xiaoc-alert);
}
.life-policy input[type='datetime-local'] {
  min-width: 0;
  max-width: 100%;
  padding: 6px;
  color: inherit;
  background: var(--xiaoc-bg);
  border: 1px solid var(--xiaoc-border);
  border-radius: 6px;
  font: inherit;
}
.life-policy :deep(.el-form-item__label) {
  color: inherit;
}
.life-goals {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.life-goals > li {
  border: 1px solid var(--xiaoc-border);
  border-radius: 8px;
  padding: 9px;
}
.life-goals p,
.life-activity :deep(.el-timeline-item__content p) {
  margin: 5px 0;
  white-space: pre-wrap;
}
.life-activity h3 {
  margin: 18px 0 10px;
  font-size: 0.9rem;
}
.life-activity :deep(.el-timeline) {
  padding-left: 3px;
}
.life-activity :deep(.el-timeline-item__content) {
  color: inherit;
}
.life-activity summary {
  cursor: pointer;
  color: var(--xiaoc-muted);
  margin-top: 6px;
}
.life-activity details li {
  overflow-wrap: anywhere;
}
.life-interests {
  display: flex;
  flex-wrap: wrap;
  list-style: none;
  padding: 0;
  gap: 6px;
}
.life-interests li {
  padding: 4px 8px;
  border: 1px solid var(--xiaoc-border);
  border-radius: 12px;
}
.life-footnote {
  margin-top: 18px;
  font-size: 0.75rem;
}
</style>
