<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import { asRecord, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  visible: boolean
  uiBridge: AnyRecord
  employeeSpaceBridge: AnyRecord
  dutyRosterBridge: AnyRecord
  uiBridgeGovernanceAction: AnyRecord
  governanceAuditLast: AnyRecord
  uiBridgeDutyRosterLocation: RouteLocationRaw | null
  uiBridgeEmployeeSpaceLocation: RouteLocationRaw | null
  canReviewGovernanceAudit: boolean
  governanceReviewBusy: boolean
  governanceReviewError: string
  governanceReviewResult: AnyRecord | null
  uiBridgeTargets: string[]
  uiBridgePath: string[]
  uiBridgeActions: string[]
  uiBridgeBlockedIds: string[]
  governanceAuditLastSummary: string
  governanceAuditLastTargets: string[]
  onReviewGovernanceAudit: () => void
}>()
</script>

<template>
  <div v-if="visible" class="selp-ui-bridge" :class="`selp-ui-bridge--${firstText(uiBridge.tone, '正常')}`">
    <div class="selp-ui-bridge-main">
      <span>操作引导 · {{ firstText(uiBridge.state, '运行时') }}</span>
      <strong>{{ firstText(uiBridge.title, '操作引导状态') }}</strong>
      <small>{{ firstText(uiBridge.detail, '后端正在统一员工空间、排班和循环的展示。') }}</small>
      <div class="selp-ui-bridge-actions">
        <router-link v-if="uiBridgeDutyRosterLocation" :to="uiBridgeDutyRosterLocation">去排班管理</router-link>
        <router-link v-if="uiBridgeEmployeeSpaceLocation" :to="uiBridgeEmployeeSpaceLocation">去员工空间</router-link>
        <button
          v-if="canReviewGovernanceAudit || governanceReviewBusy"
          type="button"
          :disabled="governanceReviewBusy"
          @click="onReviewGovernanceAudit"
        >
          {{ governanceReviewBusy ? '复核中...' : '人工复核审计' }}
        </button>
      </div>
      <small v-if="governanceReviewResult" class="selp-ui-bridge-review selp-ui-bridge-review--ok">
        审计已复核：{{ asRecord(governanceReviewResult.summary).health || '正常' }}
      </small>
      <small v-if="governanceReviewError" class="selp-ui-bridge-review selp-ui-bridge-review--bad">
        {{ governanceReviewError }}
      </small>
    </div>
    <div class="selp-ui-bridge-surfaces" role="list" aria-label="三端职责">
      <div role="listitem">
        <span>员工空间</span>
        <strong>{{ firstText(employeeSpaceBridge.role, '执行区') }}</strong>
        <small>{{ firstText(employeeSpaceBridge.cta, '查看执行情况') }}</small>
      </div>
      <div role="listitem">
        <span>排班管理</span>
        <strong>{{ firstText(dutyRosterBridge.role, '管理区') }}</strong>
        <small>{{ firstText(dutyRosterBridge.cta, '查看排班要求') }}</small>
      </div>
      <div role="listitem">
        <span>当前操作</span>
        <strong>{{ firstText(uiBridgeGovernanceAction.label, uiBridge.primary_action, '观察') }}</strong>
        <small
          >{{ firstText(uiBridgeGovernanceAction.status, uiBridge.primary_surface, '自进化循环') }} ·
          {{ firstText(uiBridgeGovernanceAction.view, uiBridge.primary_view, '部门') }}</small
        >
      </div>
      <div role="listitem">
        <span>目标员工</span>
        <strong>{{ firstText(uiBridge.primary_employee_id, uiBridgeTargets[0], '—') }}</strong>
        <small>{{ uiBridgeTargets.length ? `目标 ${uiBridgeTargets.length}` : '无定向目标' }}</small>
      </div>
    </div>
    <div v-if="uiBridgeActions.length || uiBridgeTargets.length" class="selp-ui-bridge-foot">
      <span v-if="uiBridgePath.length">路径: {{ uiBridgePath.join(' -> ') }}</span>
      <span v-if="uiBridgeGovernanceAction.id"
        >治理: {{ uiBridgeGovernanceAction.id }} ·
        {{
          uiBridgeGovernanceAction.requires_admin === true
            ? '仅管理员'
            : uiBridgeGovernanceAction.executable === false
              ? '仅查看'
              : '可执行'
        }}</span
      >
      <span v-if="uiBridgeActions.length">{{ uiBridgeActions.slice(0, 4).join(' / ') }}</span>
      <small v-if="uiBridgeBlockedIds.length">已隔离: {{ uiBridgeBlockedIds.slice(0, 8).join(' / ') }}</small>
      <small v-if="uiBridgeTargets.length">目标: {{ uiBridgeTargets.slice(0, 8).join(' / ') }}</small>
      <small v-if="governanceAuditLast.action">
        最近治理: {{ governanceAuditLast.action }} · {{ governanceAuditLast.status || (governanceAuditLast.ok === false ? '失败' : '成功')
        }}<template v-if="governanceAuditLastSummary"> · {{ governanceAuditLastSummary }}</template
        ><template v-if="governanceAuditLastTargets.length"> · {{ governanceAuditLastTargets.slice(0, 4).join(' / ') }}</template>
      </small>
    </div>
  </div>
</template>

<style scoped>
.selp-ui-bridge {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.35fr);
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid #bae6fd;
  border-radius: 12px;
  background:
    radial-gradient(circle at 0% 0%, rgba(14, 165, 233, 0.12), transparent 36%),
    linear-gradient(135deg, rgba(240, 249, 255, 0.96), rgba(248, 250, 252, 0.88));
}

.selp-ui-bridge--run {
  border-color: #99f6e4;
  background: linear-gradient(135deg, #ecfeff, #f8fafc);
}

.selp-ui-bridge--ok {
  border-color: #bbf7d0;
  background: linear-gradient(135deg, #f0fdf4, #f8fafc);
}

.selp-ui-bridge--warn {
  border-color: #fde68a;
  background: linear-gradient(135deg, #fffbeb, #f8fafc);
}

.selp-ui-bridge--bad {
  border-color: #fecaca;
  background: linear-gradient(135deg, #fef2f2, #f8fafc);
}

.selp-ui-bridge-main {
  min-width: 0;
}

.selp-ui-bridge-main span,
.selp-ui-bridge-main small,
.selp-ui-bridge-surfaces span,
.selp-ui-bridge-surfaces small,
.selp-ui-bridge-foot {
  color: var(--selp-muted);
  font-size: 11px;
}

.selp-ui-bridge-main span {
  display: block;
  font-weight: 900;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.selp-ui-bridge-main strong {
  display: block;
  margin: 3px 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
}

.selp-ui-bridge-main small {
  display: block;
  line-height: 1.45;
}

.selp-ui-bridge-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.selp-ui-bridge-actions a,
.selp-ui-bridge-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.selp-ui-bridge-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.selp-ui-bridge-review {
  display: block;
  margin-top: 6px;
  font-weight: 900;
}

.selp-ui-bridge-review--ok {
  color: #047857 !important;
}

.selp-ui-bridge-review--bad {
  color: #b91c1c !important;
}

.selp-ui-bridge-surfaces {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-ui-bridge-surfaces div {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-ui-bridge-surfaces span,
.selp-ui-bridge-surfaces strong,
.selp-ui-bridge-surfaces small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-ui-bridge-surfaces strong {
  margin: 2px 0;
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.selp-ui-bridge-foot {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 2px;
  font-weight: 800;
}

@media (max-width: 760px) {
  .selp-ui-bridge {
    grid-template-columns: 1fr;
  }

  .selp-ui-bridge-surfaces {
    grid-template-columns: 1fr;
  }
}
</style>
