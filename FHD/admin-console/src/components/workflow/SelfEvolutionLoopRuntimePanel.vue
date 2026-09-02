<script setup lang="ts">
// 入口 façade：逻辑拆至 ./self-evolution-loop-runtime/ 下的 composables 与子组件，对外 props/行为不变。
import { useSelfEvolutionRuntime } from './self-evolution-loop-runtime/useSelfEvolutionRuntime'
import { useRuntimeContract } from './self-evolution-loop-runtime/useRuntimeContract'
import RuntimeMetaCards from './self-evolution-loop-runtime/RuntimeMetaCards.vue'
import RuntimeUiBridge from './self-evolution-loop-runtime/RuntimeUiBridge.vue'
import RuntimeContractPanel from './self-evolution-loop-runtime/RuntimeContractPanel.vue'
import RuntimeGovernanceAudit from './self-evolution-loop-runtime/RuntimeGovernanceAudit.vue'
import RuntimeOpenItems from './self-evolution-loop-runtime/RuntimeOpenItems.vue'
import RuntimeLoopFlow from './self-evolution-loop-runtime/RuntimeLoopFlow.vue'
import RuntimeKbSection from './self-evolution-loop-runtime/RuntimeKbSection.vue'
import RuntimeProactiveSection from './self-evolution-loop-runtime/RuntimeProactiveSection.vue'
import RuntimeMetricsSection from './self-evolution-loop-runtime/RuntimeMetricsSection.vue'
import RuntimeRosterSection from './self-evolution-loop-runtime/RuntimeRosterSection.vue'
import RuntimeTeamSection from './self-evolution-loop-runtime/RuntimeTeamSection.vue'
import RuntimeTimeline from './self-evolution-loop-runtime/RuntimeTimeline.vue'

const props = withDefaults(defineProps<{
  compact?: boolean
  surface?: 'employee-space' | 'duty-roster'
}>(), {
  compact: false,
  surface: 'duty-roster',
})

const runtime = useSelfEvolutionRuntime(props)
const contract = useRuntimeContract(props, runtime)

const {
  statusTone, statusLabel, loading, error, refresh,
  cronLine, evidenceCards, paraTaskId, paraCopied, copyParaTaskId,
  loopStages, decisionCards, policy, branchName, actionLabel,
  kbCards, kbHitLines, kbFixHitDetails, kbPatternHitDetails,
  proactiveCards, proactiveCandidates,
  evolutionMetricCards, metricWindows,
  rosterAlignmentCards, rosterRemediation, rosterCoverage,
  teamLanes, runTimeline, openApprovalItems,
  uiBridge, governanceAuditRecent, governanceAuditSummary, governanceAuditLast,
} = runtime

const {
  reviewGovernanceAudit,
  canReviewGovernanceAudit, governanceReviewBusy, governanceReviewResult, governanceReviewError,
  activeGates, activeGateItems,
  runtimeContractOk, runtimeSchemaVersion, runtimeContractValidation,
  runtimeContractRequiredFields, runtimeContractMissingFields, runtimeContractMissingNested,
  runtimeSurfaceKey, runtimeSurfaceReadiness, runtimeSurfaceReadinessOk, runtimeSurfaceMissing,
  runtimeAllSurfaceIncidents, runtimeSurfaceIncidentSummary, runtimeSurfaceIncidents, runtimeSurfaceIncident,
  runtimeContractStatus, runtimeContractPrimaryRoute,
  runtimeContractDutyRosterLocation, runtimeContractEmployeeSpaceLocation,
  runtimeContractSurfaces, runtimeContractGateDependencies,
  uiBridgeVisible, uiBridgeGovernanceAction,
  uiBridgeDutyRosterLocation, uiBridgeEmployeeSpaceLocation,
  uiBridgeTargets, uiBridgeActions, uiBridgePath, uiBridgeBlockedIds,
  employeeSpaceBridge, dutyRosterBridge,
  governanceAuditLastSummary, governanceAuditLastTargets,
} = contract
</script>

<template>
  <section class="selp" :class="[`selp--${statusTone}`, { 'selp--compact': compact }]" aria-label="自进化 loop 运行状态">
    <div class="selp-head">
      <div>
        <p class="selp-kicker">Self-Evolution Loop</p>
        <h3 class="selp-title">自维护 / 自进化真实运行线</h3>
        <p class="selp-desc">
          读取后端 self-maintenance ledger、gate、policy 与 memory；不是静态演示。
        </p>
      </div>
      <div class="selp-state">
        <span class="selp-state-dot" aria-hidden="true" />
        <strong>{{ statusLabel }}</strong>
        <button type="button" class="selp-refresh" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="selp-error">{{ error }}</p>

    <RuntimeMetaCards
      :cron-line="cronLine"
      :evidence-cards="evidenceCards"
      :para-task-id="paraTaskId"
      :para-copied="paraCopied"
      @copy="copyParaTaskId"
    />

    <RuntimeUiBridge
      :ui-bridge-visible="uiBridgeVisible"
      :ui-bridge="uiBridge"
      :ui-bridge-duty-roster-location="uiBridgeDutyRosterLocation"
      :ui-bridge-employee-space-location="uiBridgeEmployeeSpaceLocation"
      :can-review-governance-audit="canReviewGovernanceAudit"
      :governance-review-busy="governanceReviewBusy"
      :governance-review-result="governanceReviewResult"
      :governance-review-error="governanceReviewError"
      :employee-space-bridge="employeeSpaceBridge"
      :duty-roster-bridge="dutyRosterBridge"
      :ui-bridge-governance-action="uiBridgeGovernanceAction"
      :ui-bridge-targets="uiBridgeTargets"
      :ui-bridge-actions="uiBridgeActions"
      :ui-bridge-path="uiBridgePath"
      :ui-bridge-blocked-ids="uiBridgeBlockedIds"
      :governance-audit-last="governanceAuditLast"
      :governance-audit-last-summary="governanceAuditLastSummary"
      :governance-audit-last-targets="governanceAuditLastTargets"
      @review="reviewGovernanceAudit"
    />

    <RuntimeContractPanel
      :runtime-contract-ok="runtimeContractOk"
      :runtime-schema-version="runtimeSchemaVersion"
      :runtime-contract-validation="runtimeContractValidation"
      :runtime-contract-required-fields="runtimeContractRequiredFields"
      :runtime-contract-missing-fields="runtimeContractMissingFields"
      :runtime-surface-missing="runtimeSurfaceMissing"
      :runtime-contract-status="runtimeContractStatus"
      :runtime-surface-incident-summary="runtimeSurfaceIncidentSummary"
      :runtime-contract-primary-route="runtimeContractPrimaryRoute"
      :runtime-surface-readiness="runtimeSurfaceReadiness"
      :runtime-contract-duty-roster-location="runtimeContractDutyRosterLocation"
      :runtime-contract-employee-space-location="runtimeContractEmployeeSpaceLocation"
      :runtime-contract-surfaces="runtimeContractSurfaces"
      :runtime-contract-gate-dependencies="runtimeContractGateDependencies"
      :runtime-surface-readiness-ok="runtimeSurfaceReadinessOk"
      :runtime-surface-key="runtimeSurfaceKey"
      :runtime-surface-incidents="runtimeSurfaceIncidents"
      :runtime-all-surface-incidents="runtimeAllSurfaceIncidents"
      :runtime-surface-incident="runtimeSurfaceIncident"
      :runtime-contract-missing-nested="runtimeContractMissingNested"
      :active-gates="activeGates"
      :active-gate-items="activeGateItems"
    />

    <RuntimeGovernanceAudit
      :governance-audit-recent="governanceAuditRecent"
      :governance-audit-summary="governanceAuditSummary"
    />

    <RuntimeOpenItems :open-approval-items="openApprovalItems" />

    <RuntimeLoopFlow :loop-stages="loopStages" :decision-cards="decisionCards" />

    <RuntimeKbSection
      :kb-cards="kbCards"
      :kb-hit-lines="kbHitLines"
      :kb-fix-hit-details="kbFixHitDetails"
      :kb-pattern-hit-details="kbPatternHitDetails"
    />

    <RuntimeProactiveSection
      :proactive-cards="proactiveCards"
      :proactive-candidates="proactiveCandidates"
    />

    <RuntimeMetricsSection
      :evolution-metric-cards="evolutionMetricCards"
      :metric-windows="metricWindows"
    />

    <RuntimeRosterSection
      :roster-alignment-cards="rosterAlignmentCards"
      :roster-remediation="rosterRemediation"
      :roster-coverage="rosterCoverage"
    />

    <RuntimeTeamSection :team-lanes="teamLanes" />

    <RuntimeTimeline :run-timeline="runTimeline" />

    <div v-if="!compact" class="selp-bottom">
      <div class="selp-policy">
        <span>Auto merge</span>
        <strong>{{ policy.auto_merge_low_risk === false ? '关闭' : '低风险开启' }}</strong>
        <small>max risk {{ policy.auto_merge_max_risk_score ?? '—' }} · min safety {{ policy.auto_merge_min_safety_score_v2 ?? '—' }}</small>
      </div>
      <div class="selp-policy">
        <span>最近分支</span>
        <strong>{{ branchName || '无' }}</strong>
        <small>{{ actionLabel }}</small>
      </div>
    </div>
  </section>
</template>

<style scoped src="./self-evolution-loop-runtime/self-evolution-loop-runtime.css"></style>
