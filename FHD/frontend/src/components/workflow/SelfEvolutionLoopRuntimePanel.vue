<script setup lang="ts">
import { reactive } from 'vue'
import { useSelfEvolutionRuntimePanelState } from '@/composables/useSelfEvolutionRuntimePanelState'
import { useSelfEvolutionRuntimePresenters } from '@/composables/useSelfEvolutionRuntimePresenters'
import {
  gapTone,
  governanceSummaryText,
  proactiveCandidateMeta,
  proactiveCandidateTitle,
  reviewDimFailed,
  reviewDimStatus,
} from '@/composables/selfEvolutionRuntimeValues'
import PanelHeaderSection from './self-evolution/PanelHeaderSection.vue'
import L4ReadinessSection from './self-evolution/L4ReadinessSection.vue'
import MetaEvidenceSection from './self-evolution/MetaEvidenceSection.vue'
import UiBridgeSection from './self-evolution/UiBridgeSection.vue'
import ContractSection from './self-evolution/ContractSection.vue'
import ActiveGatesSection from './self-evolution/ActiveGatesSection.vue'
import ContractIncidentsSection from './self-evolution/ContractIncidentsSection.vue'
import GovernanceAuditSection from './self-evolution/GovernanceAuditSection.vue'
import OpenItemsSection from './self-evolution/OpenItemsSection.vue'
import KbSection from './self-evolution/KbSection.vue'
import ProactiveSection from './self-evolution/ProactiveSection.vue'
import MetricsSection from './self-evolution/MetricsSection.vue'
import RosterSection from './self-evolution/RosterSection.vue'
import TimelineSection from './self-evolution/TimelineSection.vue'
import BottomSection from './self-evolution/BottomSection.vue'
import LoopStageFlow from './self-evolution/LoopStageFlow.vue'
import LoopDecisionGrid from './self-evolution/LoopDecisionGrid.vue'
import LoopTeamLanes from './self-evolution/LoopTeamLanes.vue'

const props = withDefaults(defineProps<{
  compact?: boolean
  surface?: 'employee-space' | 'duty-roster'
}>(), {
  compact: false,
  surface: 'employee-space',
})

const state = useSelfEvolutionRuntimePanelState(props.surface, props.compact)
const presenters = useSelfEvolutionRuntimePresenters(state)
</script>

<template>
  <section
    class="selp"
    :class="[`selp--${presenters.statusTone}`, { 'selp--compact': compact }]"
    aria-label="自进化循环运行状态"
  >
    <PanelHeaderSection
      :status-label="presenters.statusLabel"
      :loading="state.loading"
      :error="state.error"
      :on-refresh="state.refresh"
    />

    <L4ReadinessSection
      v-if="!compact"
      :gaps="state.l4Gaps"
      :p0-count="state.l4P0Count"
      :blocked-count="state.l4BlockedCount"
      :auto-dispatch-deploy="state.autoDispatchDeploy"
      :gap-tone="gapTone"
    />

    <MetaEvidenceSection
      :cron-line="presenters.cronLine"
      :cards="presenters.evidenceCards"
      :para-task-id="state.paraTaskId"
      :para-copied="state.paraCopied"
      @copy="state.copyParaTaskId"
    />

    <UiBridgeSection
      :visible="state.uiBridgeVisible"
      :ui-bridge="state.uiBridge"
      :employee-space-bridge="state.employeeSpaceBridge"
      :duty-roster-bridge="state.dutyRosterBridge"
      :ui-bridge-governance-action="state.uiBridgeGovernanceAction"
      :governance-audit-last="state.governanceAuditLast"
      :ui-bridge-duty-roster-location="state.uiBridgeDutyRosterLocation"
      :ui-bridge-employee-space-location="state.uiBridgeEmployeeSpaceLocation"
      :can-review-governance-audit="state.canReviewGovernanceAudit"
      :governance-review-busy="state.governanceReviewBusy"
      :governance-review-error="state.governanceReviewError"
      :governance-review-result="state.governanceReviewResult"
      :ui-bridge-targets="state.uiBridgeTargets"
      :ui-bridge-path="state.uiBridgePath"
      :ui-bridge-actions="state.uiBridgeActions"
      :ui-bridge-blocked-ids="state.uiBridgeBlockedIds"
      :governance-audit-last-summary="state.governanceAuditLastSummary"
      :governance-audit-last-targets="state.governanceAuditLastTargets"
      :on-review-governance-audit="state.reviewGovernanceAudit"
    />

    <ContractSection
      :ok="state.runtimeContractOk"
      :schema-version="state.runtimeSchemaVersion"
      :validation="state.runtimeContractValidation"
      :required-fields="state.runtimeContractRequiredFields"
      :missing-fields="state.runtimeContractMissingFields"
      :surface-missing="state.runtimeSurfaceMissing"
      :contract-status="state.runtimeContractStatus"
      :surface-incident-summary="state.runtimeSurfaceIncidentSummary"
      :primary-route="state.runtimeContractPrimaryRoute"
      :duty-roster-location="state.runtimeContractDutyRosterLocation"
      :employee-space-location="state.runtimeContractEmployeeSpaceLocation"
      :surfaces="state.runtimeContractSurfaces"
      :gate-dependencies="state.runtimeContractGateDependencies"
      :surface-readiness="state.runtimeSurfaceReadiness"
      :surface-readiness-ok="state.runtimeSurfaceReadinessOk"
      :surface-key="state.runtimeSurfaceKey"
      :surface-incidents="state.runtimeSurfaceIncidents"
      :surface-incident="state.runtimeSurfaceIncident"
      :all-surface-incidents="state.runtimeAllSurfaceIncidents"
      :missing-nested="state.runtimeContractMissingNested"
    />

    <ActiveGatesSection
      :items="state.activeGateItems"
      :active-gates="state.activeGates"
    />

    <ContractIncidentsSection
      :all-surface-incidents="state.runtimeAllSurfaceIncidents"
      :surface-incident-summary="state.runtimeSurfaceIncidentSummary"
      :schema-version="state.runtimeSchemaVersion"
    />

    <GovernanceAuditSection
      :recent="state.governanceAuditRecent"
      :summary="state.governanceAuditSummary"
      :summary-text="governanceSummaryText"
    />

    <OpenItemsSection :items="presenters.openApprovalItems" />

    <LoopStageFlow :stages="presenters.loopStages" />

    <LoopDecisionGrid :cards="presenters.decisionCards" />

    <KbSection
      :cards="presenters.kbCards"
      :hit-lines="presenters.kbHitLines"
      :fix-hit-details="presenters.kbFixHitDetails"
      :pattern-hit-details="presenters.kbPatternHitDetails"
    />

    <ProactiveSection
      :cards="presenters.proactiveCards"
      :candidates="presenters.proactiveCandidates"
      :candidate-title="proactiveCandidateTitle"
      :candidate-meta="proactiveCandidateMeta"
    />

    <MetricsSection
      :cards="presenters.evolutionMetricCards"
      :windows="presenters.metricWindows"
    />

    <RosterSection
      :cards="presenters.rosterAlignmentCards"
      :remediation="presenters.rosterRemediation"
      :coverage="presenters.rosterCoverage"
    />

    <LoopTeamLanes :lanes="state.teamLanes" />

    <TimelineSection
      :timeline="presenters.runTimeline"
      :review-dim-status="reviewDimStatus"
      :review-dim-failed="reviewDimFailed"
    />

    <BottomSection
      v-if="!compact"
      :policy="state.policy"
      :branch-name="state.branchName"
      :action-label="state.actionLabel"
    />
  </section>
</template>

<style scoped>
.selp {
  --selp-accent: #2563eb;
  --selp-bg: #ffffff;
  --selp-border: #dbe3ef;
  --selp-text: #0f172a;
  --selp-muted: #64748b;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--selp-border);
  border-left: 4px solid var(--selp-accent);
  border-radius: 14px;
  background:
    radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.10), transparent 34%),
    linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  color: var(--selp-text);
}

.selp--running { --selp-accent: #2563eb; }
.selp--ok { --selp-accent: #16a34a; }
.selp--warn { --selp-accent: #f59e0b; }
.selp--bad { --selp-accent: #ef4444; }
.selp--idle { --selp-accent: #64748b; }

.selp--compact {
  padding: 14px;
}

.selp--compact :deep(.selp-title) {
  font-size: 16px;
}
</style>