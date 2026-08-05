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
          <span v-if="stageDraftDirty" class="muted cs-stage-viewing-from">（当前为「{{ stageLabel(currentStageId) }}」）</span>
        </div>
        <div v-if="showIntakeStageShortcuts" class="cs-stage-intake-quick">
          <button
            type="button"
            class="btn btn-xs"
            :disabled="intakeLinkLoading"
            @click="onOpenIntakeForm"
          >
            帮客户填写
          </button>
          <button
            type="button"
            class="btn btn-xs"
            :disabled="intakeLinkLoading"
            @click="onCopyIntakeUrl"
          >
            {{ intakeLinkLoading ? '获取中…' : '复制表单链接' }}
          </button>
        </div>
        <div v-if="currentStageId === 'intake' || currentStageId === 'intake_done'" class="cs-audit-code-row">
          <label class="cs-audit-code-label">
            <span class="muted">客户审核码</span>
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
            class="btn btn-xs"
            :disabled="auditCodeFetching || auditCodeRedeeming || !intakeAuditCode.trim()"
            @click="onFetchAudit"
          >
            {{ auditCodeFetching ? '获取中…' : '获取表单' }}
          </button>
          <button
            type="button"
            class="btn btn-xs btn-accent"
            :disabled="auditCodeRedeeming || auditCodeFetching || !intakeAuditCode.trim()"
            @click="onRedeemAudit"
          >
            {{ auditCodeRedeeming ? '确认中…' : '确认并进入下一阶段' }}
          </button>
        </div>
        <p v-if="auditCodeError" class="form-error cs-audit-code-error">{{ auditCodeError }}</p>
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
          <p class="muted cs-audit-preview-hint">核对无误后点击「确认并进入下一阶段」写入客户档案。</p>
        </div>
        <div class="cs-stage-intro-actions">
          <label class="cs-stage-edit">
            <span class="muted">调整阶段</span>
            <select :value="stageDraft" @change="$emit('update:stageDraft', ($event.target as HTMLSelectElement).value)" class="cs-stage-select" :disabled="stageSaving">
              <option v-for="st in pipelineStages" :key="'sel-' + st.id" :value="st.id">
                {{ st.label }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="btn btn-xs btn-accent"
            :class="{ 'is-pending': stageDraftDirty }"
            :disabled="!canSavePipelineStage"
            :title="saveStageButtonTitle"
            @click="onSaveStage()"
          >
            {{ stageSaving ? '保存中…' : (stageDraftDirty ? `保存为「${stageLabel(stageDraft)}」` : '保存阶段') }}
          </button>
          <button type="button" class="btn btn-xs cs-analyze-btn" :disabled="pipelineAnalyzing" @click="onAnalyze">
            {{ pipelineAnalyzing ? '分析中…' : '分析进度' }}
          </button>
        </div>
      </div>
      <p v-if="stageDraftDirty" class="cs-stage-pending-hint">
        已预选「{{ stageLabel(stageDraft) }}」，请确认后点击「保存为…」才会写入（点进度条不会自动保存）。
      </p>
      <p class="muted cs-stage-edit-hint">调整阶段：在进度条或下拉框预选，再点「保存阶段」。「分析进度」仅根据群聊建议阶段，不会自动改当前阶段。</p>
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
      <p v-if="autoStageAdvancing" class="muted cs-auto-advance-hint">清单已完成，正在进入下一阶段…</p>
      <p v-if="currentStageGuide.actionHint" class="cs-stage-hint">{{ currentStageGuide.actionHint }}</p>
      <p v-if="stageRank(currentStageId) >= stageRank('connected')" class="cs-stage-done-hint muted">
        客户提交需求表单（审核码兑换或官网填写）后，将自动设为企业客户，并把卡片名称改为表单中的公司名。
      </p>
      <div v-if="currentStageId === 'intake'" class="cs-stage-actions">
        <button type="button" class="btn btn-xs" :disabled="intakeLinkLoading" @click="onCopyIntakeUrl">
          复制表单链接
        </button>
      </div>
      <div v-if="showCrmFinalizeActions" class="cs-stage-actions cs-intake-done-actions">
        <button
          type="button"
          class="btn btn-xs btn-accent"
          :disabled="intakeFinalizeLoading"
          @click="onFinalize"
        >
          {{ intakeFinalizeLoading ? '同步中…' : '同步 CRM 并关联 ERP' }}
        </button>
        <button
          type="button"
          class="btn btn-xs"
          :disabled="intakeFinalizeLoading || !customers.intake_submitted_at"
          @click="onSyncMarket"
        >
          拉取官网最新提交
        </button>
      </div>
      <p v-if="showCrmFinalizeActions && customers.erp_customer_name" class="cs-stage-done-hint">
        已关联 ERP：{{ customers.erp_customer_name }}
        <span v-if="customers.crm_funnel_synced_at" class="muted">
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
              <span v-if="crmQuoteStatus" class="muted">（{{ crmQuoteStatus }}）</span>
              <span v-if="crmQuoteSummary" class="cs-crm-quote-sum">{{ crmQuoteSummary }}</span>
            </template>
            <template v-else>待生成</template>
          </dd>
        </dl>
        <button
          type="button"
          class="btn btn-xs"
          :disabled="crmSyncLoading || !selectedUserId"
          @click="onSyncCrm"
        >
          {{ crmSyncLoading ? '同步中…' : '刷新 CRM / 报价记录' }}
        </button>
        <button
          v-if="showCrmFinalizeActions"
          type="button"
          class="btn btn-xs btn-secondary"
          :disabled="crmRepairLoading || !selectedUserId"
          @click="onRepairCrm"
        >
          {{ crmRepairLoading ? '修复中…' : '一键修复 CRM/ERP' }}
        </button>
        <div class="cs-external-crm">
          <p class="cs-external-crm__title muted">外部 CRM（HubSpot 等）</p>
          <p class="cs-external-crm__hint muted">
            出站推送商机；可手动从 HubSpot / Salesforce 拉取阶段回写 Pipeline（非 webhook 实时同步）。
            自建 Pipeline ↔ CRM SQLite 仍为双向同步。
          </p>
          <p v-if="customers.external_crm_deal_id" class="muted cs-external-crm__meta">
            Deal ID：<code>{{ customers.external_crm_deal_id }}</code>
          </p>
          <p v-if="customers.external_crm_last_at" class="muted cs-external-crm__meta">
            最近推送 {{ formatPassivePollTime(customers.external_crm_last_at) }}
            <span v-if="externalCrmStatusLabel"> · {{ externalCrmStatusLabel }}</span>
          </p>
          <p v-else class="muted">尚未推送到 HubSpot / Salesforce</p>
          <p
            v-if="customers.external_crm_last_pull_at"
            class="muted cs-external-crm__meta"
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
              class="btn btn-xs"
              :disabled="externalCrmPushLoading || !selectedUserId"
              @click="onPushCrm"
            >
              {{ externalCrmPushLoading ? '推送中…' : '推送到外部 CRM' }}
            </button>
            <button
              type="button"
              class="btn btn-xs btn-secondary"
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
        <p v-if="financeLedgerLoading" class="muted">加载中…</p>
        <p v-else-if="!financeLedgerItems.length" class="muted">
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
        <button type="button" class="btn btn-xs" @click="onCopyScript(groupScriptForStage())">
          复制{{ groupScriptActionLabel }}话术
        </button>
        <button
          type="button"
          class="btn btn-xs btn-ghost"
          :disabled="pipelineAnalyzing"
          @click="onAnalyze"
        >
          {{ pipelineAnalyzing ? '分析中…' : '分析进度' }}
        </button>
        <button
          v-if="currentStageId === 'intake_done'"
          type="button"
          class="btn btn-xs btn-accent"
          :disabled="stageSaving"
          @click="onSaveStage('quoted', { confirmMessage: '群内已报价？将阶段标记为「已报价」。' })"
        >
          标记为已报价
        </button>
        <button
          v-if="currentStageId === 'quoted'"
          type="button"
          class="btn btn-xs btn-accent"
          :disabled="stageSaving"
          @click="onSaveStage('negotiating', { confirmMessage: '进入议价？将阶段标记为「议价」。' })"
        >
          标记为议价中
        </button>
        <button
          v-if="currentStageId === 'negotiating'"
          type="button"
          class="btn btn-xs btn-accent"
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

<style scoped>
.cs-progress-panel {
  background: linear-gradient(180deg, #f8faff 0%, #fff 100%);
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cs-progress-bar { margin-bottom: 2px; }
.cs-progress-track { height: 8px; background: #eef2f7; border-radius: 4px; overflow: hidden; margin-bottom: 10px; }
.cs-progress-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #4a6cf7); border-radius: 4px; transition: width 0.3s; }
.cs-progress-steps {
  display: flex; gap: 2px; list-style: none; margin: 0; padding: 0;
  overflow-x: auto; scrollbar-width: thin;
}
.cs-progress-step {
  flex: 1; min-width: 52px; display: flex; flex-direction: column; align-items: center; gap: 4px;
  text-align: center;
}
.cs-progress-dot {
  width: 22px; height: 22px; border-radius: 50%; font-size: 10px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  background: #e2e8f0; color: #64748b; flex-shrink: 0;
}
.cs-progress-label { font-size: 10px; color: #94a3b8; line-height: 1.2; white-space: nowrap; }
.cs-progress-step.is-done .cs-progress-dot { background: #dcfce7; color: #16a34a; }
.cs-progress-step.is-done .cs-progress-label { color: #64748b; }
.cs-progress-step.is-current .cs-progress-dot {
  background: #4a6cf7; color: #fff; box-shadow: 0 0 0 3px rgba(74,108,247,0.18);
}
.cs-progress-step.is-current .cs-progress-label { color: #4a6cf7; font-weight: 600; }
.cs-progress-step.is-pick:not(.is-current) .cs-progress-dot {
  box-shadow: 0 0 0 2px rgba(74, 108, 247, 0.35);
}
.cs-progress-step[role='button'] { cursor: pointer; }
.cs-progress-step[role='button']:hover .cs-progress-label { color: #475569; }
.cs-stage-intro {
  background: #fff; border: 1px solid #e8ecf2; border-radius: 10px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.cs-stage-intro-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap;
}
.cs-audit-code-row {
  display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 12px;
  margin-top: 10px; padding-top: 10px; border-top: 1px dashed rgba(148, 163, 184, 0.45);
}
.cs-audit-code-label { display: flex; flex-direction: column; gap: 4px; flex: 1 1 160px; min-width: 140px; }
.cs-audit-code-input { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: 0.04em; }
.cs-audit-code-error { margin: 4px 0 0; width: 100%; }
.cs-audit-preview { margin-top: 10px; }
.cs-audit-preview-hint { margin: 8px 0 0; font-size: 12px; }
.cs-stage-intake-quick { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cs-stage-intro-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cs-stage-edit { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.cs-stage-select { font-size: 12px; padding: 4px 8px; border-radius: 6px; border: 1px solid #e2e8f0; max-width: 120px; }
.cs-stage-edit-hint { margin: 0; font-size: 11px; line-height: 1.45; }
.cs-auto-advance-hint { margin: 8px 0 0; font-size: 12px; color: #4a6cf7; }
.cs-stage-intro-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cs-stage-intro-title strong { font-size: 15px; color: #1e293b; }
.cs-stage-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #eff6ff; color: #4a6cf7; font-weight: 500; }
.cs-stage-viewing-from { font-size: 12px; font-weight: 400; }
.cs-stage-lead { margin: 0; font-size: 13px; font-weight: 500; color: #334155; }
.cs-stage-desc { margin: 0; font-size: 12px; color: #64748b; line-height: 1.55; }
.cs-stage-hint { margin: 0; font-size: 12px; color: #475569; line-height: 1.5; }
.cs-stage-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.cs-stage-done-hint { margin: 0; font-size: 12px; color: #16a34a; }
.cs-stage-warn-hint { color: #b45309; }
.cs-intake-done-actions { flex-wrap: wrap; gap: 6px; }
.cs-crm-panel { margin: 10px 0 0; padding: 10px 12px; border-radius: 8px; background: #f8fafc; border: 1px solid #e2e8f0; }
.cs-crm-panel__title { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #334155; }
.cs-crm-panel__dl { margin: 0 0 8px; display: grid; grid-template-columns: 5.5em 1fr; gap: 4px 10px; font-size: 12px; }
.cs-crm-panel__dl dt { color: #64748b; margin: 0; }
.cs-crm-panel__dl dd { margin: 0; color: #1e293b; }
.cs-finance-panel { margin-top: 10px; }
.cs-external-crm { margin-top: 10px; padding-top: 10px; border-top: 1px dashed #e2e8f0; }
.cs-external-crm__title { margin: 0 0 4px; font-size: 11px; }
.cs-external-crm__hint { margin: 0 0 8px; font-size: 12px; line-height: 1.45; }
.cs-external-crm__meta { margin: 0 0 6px; font-size: 12px; }
.cs-external-crm__meta code { font-size: 11px; }
.cs-external-crm__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.cs-finance-table { width: 100%; font-size: 11px; border-collapse: collapse; margin-top: 6px; }
.cs-finance-table th, .cs-finance-table td { border: 1px solid #e2e8f0; padding: 4px 6px; text-align: left; }
.cs-crm-quote-sum { display: block; margin-top: 2px; color: #475569; }
.cs-stage-checklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.cs-stage-checklist li { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: #64748b; line-height: 1.45; }
.cs-stage-checklist li.is-done { color: #16a34a; }
.cs-check-mark { width: 14px; flex-shrink: 0; text-align: center; font-size: 11px; }
.cs-analyze-btn { flex-shrink: 0; }
.cs-stage-roadmap { font-size: 12px; }
.cs-stage-roadmap summary { cursor: pointer; color: #4a6cf7; font-weight: 500; padding: 4px 0; list-style: none; }
.cs-stage-roadmap summary::-webkit-details-marker { display: none; }
.cs-stage-roadmap summary::before { content: '▸ '; }
.cs-stage-roadmap[open] summary::before { content: '▾ '; }
.cs-roadmap-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
@media (max-width: 900px) { .cs-roadmap-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px) { .cs-roadmap-grid { grid-template-columns: 1fr; } }
.cs-roadmap-item { background: #fff; border: 1px solid #e8ecf2; border-radius: 8px; padding: 10px; }
.cs-roadmap-item.is-current { border-color: #93c5fd; background: #f8fbff; }
.cs-roadmap-item.is-done { border-color: #bbf7d0; }
.cs-roadmap-title { margin: 0 0 4px; font-size: 12px; font-weight: 600; color: #334155; }
.cs-roadmap-headline { margin: 0 0 6px; font-size: 11px; color: #64748b; line-height: 1.4; }
.cs-roadmap-todos { margin: 0; padding-left: 16px; color: #94a3b8; font-size: 11px; line-height: 1.45; }
.cs-roadmap-todos li { margin-bottom: 2px; }
.cs-coming-soon-inline { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px; }
.cs-stage-group-tip { margin: 8px 0 0; padding: 8px 10px; font-size: 12px; line-height: 1.45; color: #1e40af; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; }
.cs-stage-actions--quote { margin-top: 8px; }
.cs-stage-pending-hint { margin: 6px 0 0; font-size: 12px; color: #b45309; }
.btn.btn-xs.btn-accent.is-pending { box-shadow: 0 0 0 2px rgba(74, 108, 247, 0.35); }
.cs-coming-soon { font-size: 12px; color: #b45309; margin: 0; }
.cs-intake-summary { margin-top: 10px; padding: 10px 12px; border-radius: 8px; background: #f0fdf4; border: 1px solid #bbf7d0; }
.cs-intake-summary__title { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #166534; }
.cs-intake-summary__time { font-weight: 400; color: #64748b; margin-left: 6px; }
.cs-intake-summary__dl { margin: 0; display: grid; grid-template-columns: 4.5em 1fr; gap: 4px 10px; font-size: 12px; }
.cs-intake-summary__dl dt { color: #64748b; margin: 0; }
.cs-intake-summary__dl dd { margin: 0; color: #1e293b; white-space: pre-wrap; }
.muted { color: #94a3b8; }
.form-error { color: #b91c1c; font-size: 12px; margin: 0; }
.cs-input { width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; font-size: 13px; box-sizing: border-box; background: #fff; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: #4a6cf7; border-color: #4a6cf7; color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; border: 1px solid #e8ecf2; color: #64748b; }
.btn-ghost:hover { border-color: #4a6cf7; color: #4a6cf7; }
.btn-secondary { background: #fff; border: 1px solid #e8ecf2; color: #334155; }
.btn-secondary:hover { border-color: #cbd5e1; }
</style>