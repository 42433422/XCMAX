<template>
  <section class="cs-progress-panel">
    <div class="cs-progress-bar">
      <div class="cs-progress-track">
        <div class="cs-progress-fill" :style="{ width: progressPercent + '%' }" />
      </div>
      <ol class="cs-progress-steps">
        <li
          v-for="(st, idx) in pipelineStages"
          :key="st.id"
          class="cs-progress-step"
          :class="[stepperItemClass(st.id, idx), { 'is-pick': stageDraft === st.id }]"
          role="button"
          tabindex="0"
          :title="st.id === currentStageId ? `当前阶段：${st.label}` : `预选：${st.label}（需点保存阶段）`"
          @click="onPickStage(st.id)"
          @keydown.enter.prevent="onPickStage(st.id)"
        >
          <span class="cs-progress-dot">{{ idx + 1 }}</span>
          <span class="cs-progress-label">{{ st.label }}</span>
        </li>
      </ol>
    </div>

    <div class="cs-stage-intro">
      <div class="cs-stage-intro-head">
        <div class="cs-stage-intro-title">
          <span class="cs-stage-badge">{{ stageDraftDirty ? '预选阶段' : '当前阶段' }}</span>
          <strong>{{ stageLabel(viewingStageId) }}</strong>
          <span v-if="stageDraftDirty" class="cpp-muted cs-stage-viewing-from">（当前为「{{ stageLabel(currentStageId) }}」）</span>
        </div>
        <div v-if="showIntakeStageShortcuts" class="cs-stage-intake-quick">
          <button
            type="button"
            class="btn cpp-btn-xs"
            :disabled="intakeLinkLoading"
            @click="onOpenIntakeForm"
          >
            帮客户填写
          </button>
          <button
            type="button"
            class="btn cpp-btn-xs"
            :disabled="intakeLinkLoading"
            @click="onCopyIntakeUrl"
          >
            {{ intakeLinkLoading ? '获取中…' : '复制表单链接' }}
          </button>
        </div>
        <div v-if="currentStageId === 'intake' || currentStageId === 'intake_done'" class="cs-audit-code-row">
          <label class="cs-audit-code-label">
            <span class="cpp-muted">客户审核码</span>
            <input
              :value="intakeAuditCode"
              @input="$emit('update:intakeAuditCode', ($event.target as HTMLInputElement).value)"
              type="text"
              class="cs-input cs-audit-code-input"
              placeholder="XC-000123"
              autocomplete="off"
              @keydown.enter.prevent="onFetchAudit"
            />
          </label>
          <button
            type="button"
            class="btn cpp-btn-xs"
            :disabled="auditCodeFetching || auditCodeRedeeming || !intakeAuditCode.trim()"
            @click="onFetchAudit"
          >
            {{ auditCodeFetching ? '获取中…' : '获取表单' }}
          </button>
          <button
            type="button"
            class="btn cpp-btn-xs cpp-btn-accent"
            :disabled="auditCodeRedeeming || auditCodeFetching || !intakeAuditCode.trim()"
            @click="onRedeemAudit"
          >
            {{ auditCodeRedeeming ? '确认中…' : '确认并进入下一阶段' }}
          </button>
        </div>
        <p v-if="auditCodeError" class="cpp-form-error cs-audit-code-error">{{ auditCodeError }}</p>
        <div v-if="intakeAuditPreviewRows?.length" class="cs-intake-summary cs-audit-preview">
          <p class="cs-intake-summary__title">
            已拉取官网问卷（审核码 {{ intakeAuditPreviewCode }}）
            <span v-if="intakeAuditPreviewAt" class="cs-intake-summary__time">{{ formatPassivePollTime(intakeAuditPreviewAt) }}</span>
          </p>
          <dl class="cs-intake-summary__dl">
            <template v-for="row in intakeAuditPreviewRows" :key="'audit-' + row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </template>
          </dl>
          <p class="cpp-muted cs-audit-preview-hint">核对无误后点击「确认并进入下一阶段」写入客户档案。</p>
        </div>
        <div class="cs-stage-intro-actions">
          <label class="cs-stage-edit">
            <span class="cpp-muted">调整阶段</span>
            <select :value="stageDraft" @change="$emit('update:stageDraft', ($event.target as HTMLSelectElement).value)" class="cs-stage-select" :disabled="stageSaving">
              <option v-for="st in pipelineStages" :key="'sel-' + st.id" :value="st.id">
                {{ st.label }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="btn cpp-btn-xs cpp-btn-accent"
            :class="{ 'is-pending': stageDraftDirty }"
            :disabled="!canSavePipelineStage"
            :title="saveStageButtonTitle"
            @click="onSaveStage()"
          >
            {{ stageSaving ? '保存中…' : (stageDraftDirty ? `保存为「${stageLabel(stageDraft)}」` : '保存阶段') }}
          </button>
          <button type="button" class="btn cpp-btn-xs cs-analyze-btn" :disabled="pipelineAnalyzing" @click="onAnalyze">
            {{ pipelineAnalyzing ? '分析中…' : '分析进度' }}
          </button>
        </div>
      </div>
      <p v-if="stageDraftDirty" class="cs-stage-pending-hint">
        已预选「{{ stageLabel(stageDraft) }}」，请确认后点击「保存为…」才会写入（点进度条不会自动保存）。
      </p>
      <p class="cpp-muted cs-stage-edit-hint">调整阶段：在进度条或下拉框预选，再点「保存阶段」。「分析进度」仅根据群聊建议阶段，不会自动改当前阶段。</p>
      <p v-if="currentStageGuide.headline" class="cs-stage-lead">{{ currentStageGuide.headline }}</p>
      <p class="cs-stage-desc">{{ currentStageGuide.description }}</p>
      <ul v-if="currentStageGuide.checklist.length" class="cs-stage-checklist">
        <li
          v-for="item in currentStageGuide.checklist"
          :key="item.key"
          :class="{ 'is-done': checklistItemDone(item.key) }"
        >
          <span class="cs-check-mark">{{ checklistItemDone(item.key) ? '✓' : '○' }}</span>
          {{ item.text }}
        </li>
      </ul>
      <p v-if="intakeSubmittedAwaitingAdvance && !autoStageAdvancing" class="cs-stage-pending-hint">
        检测到需求表单已提交，系统应自动进入「需求已提交」。若仍停在本阶段，请点「分析进度」或重新展开本客户卡片。
      </p>
      <p v-if="autoStageAdvancing" class="cpp-muted cs-auto-advance-hint">清单已完成，正在进入下一阶段…</p>
      <p v-if="currentStageGuide.actionHint" class="cs-stage-hint">{{ currentStageGuide.actionHint }}</p>
      <p v-if="stageRank(currentStageId) >= stageRank('connected')" class="cs-stage-done-hint cpp-muted">
        客户提交需求表单（审核码兑换或官网填写）后，将自动设为企业客户，并把卡片名称改为表单中的公司名。
      </p>
      <div v-if="currentStageId === 'intake'" class="cs-stage-actions">
        <button type="button" class="btn cpp-btn-xs" :disabled="intakeLinkLoading" @click="onCopyIntakeUrl">
          复制表单链接
        </button>
      </div>
      <div v-if="showCrmFinalizeActions" class="cs-stage-actions cs-intake-done-actions">
        <button
          type="button"
          class="btn cpp-btn-xs cpp-btn-accent"
          :disabled="intakeFinalizeLoading"
          @click="onFinalize"
        >
          {{ intakeFinalizeLoading ? '同步中…' : '同步 CRM 并关联 ERP' }}
        </button>
        <button
          type="button"
          class="btn cpp-btn-xs"
          :disabled="intakeFinalizeLoading || !customers.intake_submitted_at"
          @click="onSyncMarket"
        >
          拉取官网最新提交
        </button>
      </div>
      <p v-if="showCrmFinalizeActions && customers.erp_customer_name" class="cs-stage-done-hint">
        已关联 ERP：{{ customers.erp_customer_name }}
        <span v-if="customers.crm_funnel_synced_at" class="cpp-muted">
          · {{ formatPassivePollTime(customers.crm_funnel_synced_at) }}
        </span>
      </p>
      <p
        v-else-if="showCrmFinalizeActions && customers.intake_submitted_at"
        class="cs-stage-done-hint cs-stage-warn-hint"
      >
        需求已入库，CRM/ERP 未完全关联；打开客户时将自动尝试同步。也可手动点「同步 CRM 并关联 ERP」。
      </p>
      <p
        v-if="showIntakeFunnelWarn"
        class="cs-stage-done-hint cs-stage-warn-hint"
      >
        官网/contact 表单提交会自动进入 CRM 漏斗；内部手工录入请点「同步 CRM 并关联 ERP」。
      </p>
      <p v-if="currentStageGuide.groupTip" class="cs-stage-group-tip">{{ currentStageGuide.groupTip }}</p>
      <div v-if="showCrmLinkagePanel" class="cs-crm-panel">
        <p class="cs-crm-panel__title">销售 CRM（线索 → 商机 → 报价）</p>
        <dl class="cs-crm-panel__dl">
          <dt>商机 ID</dt>
          <dd>{{ customers.crm_opportunity_id || '未入库' }}</dd>
          <dt>官网需求单</dt>
          <dd>{{ formatAuditCodeFromLandingId(customers.landing_contact_id) || '—' }}</dd>
          <dt>ERP 客户</dt>
          <dd>{{ customers.erp_customer_name || '未关联' }}</dd>
          <dt>报价单</dt>
          <dd>
            <template v-if="customers.crm_quote_id">
              #{{ customers.crm_quote_id }}
              <span v-if="crmQuoteStatus" class="cpp-muted">（{{ crmQuoteStatus }}）</span>
              <span v-if="crmQuoteSummary" class="cs-crm-quote-sum">{{ crmQuoteSummary }}</span>
            </template>
            <template v-else>待生成</template>
          </dd>
        </dl>
        <button
          type="button"
          class="btn cpp-btn-xs"
          :disabled="crmSyncLoading || !selectedUserId"
          @click="onSyncCrm"
        >
          {{ crmSyncLoading ? '同步中…' : '刷新 CRM / 报价记录' }}
        </button>
        <button
          v-if="showCrmFinalizeActions"
          type="button"
          class="btn cpp-btn-xs cpp-btn-secondary"
          :disabled="crmRepairLoading || !selectedUserId"
          @click="onRepairCrm"
        >
          {{ crmRepairLoading ? '修复中…' : '一键修复 CRM/ERP' }}
        </button>
        <div class="cs-external-crm">
          <p class="cs-external-crm__title cpp-muted">外部 CRM（HubSpot 等）</p>
          <p class="cs-external-crm__hint cpp-muted">
            出站推送商机；可手动从 HubSpot / Salesforce 拉取阶段回写 Pipeline（非 webhook 实时同步）。
            自建 Pipeline ↔ CRM SQLite 仍为双向同步。
          </p>
          <p v-if="customers.external_crm_deal_id" class="cpp-muted cs-external-crm__meta">
            Deal ID：<code>{{ customers.external_crm_deal_id }}</code>
          </p>
          <p v-if="customers.external_crm_last_at" class="cpp-muted cs-external-crm__meta">
            最近推送 {{ formatPassivePollTime(customers.external_crm_last_at) }}
            <span v-if="externalCrmStatusLabel"> · {{ externalCrmStatusLabel }}</span>
          </p>
          <p v-else class="cpp-muted">尚未推送到 HubSpot / Salesforce</p>
          <p
            v-if="customers.external_crm_last_pull_at"
            class="cpp-muted cs-external-crm__meta"
          >
            最近拉取 {{ formatPassivePollTime(customers.external_crm_last_pull_at) }}
            <span v-if="externalCrmPullStatusLabel"> · {{ externalCrmPullStatusLabel }}</span>
          </p>
          <p v-if="customers.external_crm_last_error" class="cs-stage-warn-hint">
            {{ customers.external_crm_last_error }}
          </p>
          <p v-if="customers.external_crm_last_pull_error" class="cs-stage-warn-hint">
            {{ customers.external_crm_last_pull_error }}
          </p>
          <div class="cs-external-crm__actions">
            <button
              type="button"
              class="btn cpp-btn-xs"
              :disabled="externalCrmPushLoading || !selectedUserId"
              @click="onPushCrm"
            >
              {{ externalCrmPushLoading ? '推送中…' : '推送到外部 CRM' }}
            </button>
            <button
              type="button"
              class="btn cpp-btn-xs cpp-btn-secondary"
              :disabled="externalCrmPullLoading || !selectedUserId"
              @click="onPullCrm"
            >
              {{ externalCrmPullLoading ? '拉取中…' : '从外部 CRM 拉取阶段' }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="showCrmLinkagePanel" class="cs-crm-panel cs-finance-panel">
        <p class="cs-crm-panel__title">财务单据（统一）</p>
        <p v-if="financeLedgerLoading" class="cpp-muted">加载中…</p>
        <p v-else-if="!financeLedgerItems.length" class="cpp-muted">
          到款或开票后自动归档；也可在侧栏「财务统计」查看全局列表。
        </p>
        <table v-else class="cs-finance-table">
          <thead>
            <tr>
              <th>轨道</th>
              <th>单号</th>
              <th>金额</th>
              <th>状态</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in financeLedgerItems" :key="`${row.source_type}-${row.source_id}`">
              <td>{{ financeTrackLabel(String(row.track)) }}</td>
              <td>{{ String(row.invoice_no || row.payment_ref || `${row.source_type}#${row.source_id}`) }}</td>
              <td>¥{{ formatLedgerYuan(Number(row.amount_cents)) }}</td>
              <td>{{ String(row.status) }}</td>
              <td>{{ formatLedgerTime(String(row.occurred_at)) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="showQuoteNegotiateActions" class="cs-stage-actions cs-stage-actions--quote">
        <button type="button" class="btn cpp-btn-xs" @click="onCopyScript(groupScriptForStage())">
          复制{{ groupScriptActionLabel }}话术
        </button>
        <button
          type="button"
          class="btn cpp-btn-xs cpp-btn-ghost"
          :disabled="pipelineAnalyzing"
          @click="onAnalyze"
        >
          {{ pipelineAnalyzing ? '分析中…' : '分析进度' }}
        </button>
        <button
          v-if="currentStageId === 'intake_done'"
          type="button"
          class="btn cpp-btn-xs cpp-btn-accent"
          :disabled="stageSaving"
          @click="onSaveStage('quoted', { confirmMessage: '群内已报价？将阶段标记为「已报价」。' })"
        >
          标记为已报价
        </button>
        <button
          v-if="currentStageId === 'quoted'"
          type="button"
          class="btn cpp-btn-xs cpp-btn-accent"
          :disabled="stageSaving"
          @click="onSaveStage('negotiating', { confirmMessage: '进入议价？将阶段标记为「议价」。' })"
        >
          标记为议价中
        </button>
        <button
          v-if="currentStageId === 'negotiating'"
          type="button"
          class="btn cpp-btn-xs cpp-btn-accent"
          :disabled="stageSaving"
          @click="onSaveStage('contract_pending', { confirmMessage: '群内已谈妥？将阶段标记为「待签」。' })"
        >
          标记为待签
        </button>
      </div>
      <p v-if="currentStageGuide.comingSoon" class="cs-coming-soon cs-coming-soon-inline">{{ currentStageGuide.comingSoon }}</p>
    </div>

    <details class="cs-stage-roadmap">
      <summary>查看全流程 · 各阶段要做什么</summary>
      <div class="cs-roadmap-grid">
        <article
          v-for="st in pipelineStages"
          :key="'roadmap-' + st.id"
          class="cs-roadmap-item"
          :class="stepperItemClass(st.id, 0)"
        >
          <h5 class="cs-roadmap-title">{{ st.label }}</h5>
          <p class="cs-roadmap-headline">{{ stageGuideFor(st.id).headline }}</p>
          <ul v-if="stageGuideFor(st.id).checklist.length" class="cs-roadmap-todos">
            <li v-for="item in stageGuideFor(st.id).checklist" :key="item.key">{{ item.text }}</li>
          </ul>
        </article>
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import './CustomerPipelineProgressPanel.css'
import type { PhaseGuide } from '../composables/usePipelineGuide'
import type { CustomerPipelineState } from '../composables/useCustomerWorkbench'
import {
  formatAuditCodeFromLandingId,
  formatLedgerTime,
  formatLedgerYuan,
  financeTrackLabel,
  formatPassivePollTime,
} from '../composables/useCustomerServiceFormat'

export type StageSaveOpts = { silent?: boolean; confirmMessage?: string; auto?: boolean }

defineProps<{
  pipelineStages: Array<{ id: string; label: string }>
  progressPercent: number
  stageDraft: string
  stageDraftDirty: boolean
  currentStageId: string
  viewingStageId: string
  stageLabel: (stageId: string) => string
  stageRank: (stageId: string) => number
  stepperItemClass: (stageId: string, idx: number) => string
  stageGuideFor: (stageId: string) => PhaseGuide
  currentStageGuide: PhaseGuide
  checklistItemDone: (key: string) => boolean
  customers: CustomerPipelineState
  intakeAuditPreviewRows: Array<{ label: string; value: string }> | null
  intakeAuditPreviewCode: string
  intakeAuditPreviewAt: string
  intakeAuditCode: string
  auditCodeError: string
  crmQuoteStatus: string
  crmQuoteSummary: string
  intakeSubmittedAwaitingAdvance: boolean
  autoStageAdvancing: boolean
  showIntakeStageShortcuts: boolean
  showQuoteNegotiateActions: boolean
  showCrmLinkagePanel: boolean
  showCrmFinalizeActions: boolean
  showIntakeFunnelWarn: boolean
  canSavePipelineStage: boolean
  saveStageButtonTitle: string
  stageSaving: boolean
  pipelineAnalyzing: boolean
  intakeFinalizeLoading: boolean
  intakeLinkLoading: boolean
  auditCodeFetching: boolean
  auditCodeRedeeming: boolean
  crmSyncLoading: boolean
  crmRepairLoading: boolean
  externalCrmPushLoading: boolean
  externalCrmPullLoading: boolean
  externalCrmStatusLabel: string
  externalCrmPullStatusLabel: string
  financeLedgerItems: Array<Record<string, unknown>>
  financeLedgerLoading: boolean
  selectedUserId: number | null
  groupScriptActionLabel: string
  groupScriptForStage: () => string
  onPickStage: (id: string) => void
  onSaveStage: (targetStage?: string, opts?: StageSaveOpts) => void
  onOpenIntakeForm: () => void
  onCopyIntakeUrl: () => void
  onFetchAudit: () => void
  onRedeemAudit: () => void
  onAnalyze: () => void
  onFinalize: () => void
  onSyncMarket: () => void
  onSyncCrm: () => void
  onRepairCrm: () => void
  onPushCrm: () => void
  onPullCrm: () => void
  onCopyScript: (text: string) => void
}>()

defineEmits<{
  (e: 'update:stageDraft', value: string): void
  (e: 'update:intakeAuditCode', value: string): void
}>()
</script>