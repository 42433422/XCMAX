<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import { asRecord, firstText, type AnyRecord } from './runtimeHelpers'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 UI Bridge 区块）；模板逐字迁移，行为不变。
defineProps<{
  uiBridgeVisible: boolean
  uiBridge: AnyRecord
  uiBridgeDutyRosterLocation: RouteLocationRaw | null
  uiBridgeEmployeeSpaceLocation: RouteLocationRaw | null
  canReviewGovernanceAudit: boolean
  governanceReviewBusy: boolean
  governanceReviewResult: AnyRecord | null
  governanceReviewError: string
  employeeSpaceBridge: AnyRecord
  dutyRosterBridge: AnyRecord
  uiBridgeGovernanceAction: AnyRecord
  uiBridgeTargets: string[]
  uiBridgeActions: string[]
  uiBridgePath: string[]
  uiBridgeBlockedIds: string[]
  governanceAuditLast: AnyRecord
  governanceAuditLastSummary: string
  governanceAuditLastTargets: string[]
}>()

defineEmits<{ review: [] }>()
</script>

<template>
    <div v-if="uiBridgeVisible" class="selp-ui-bridge" :class="`selp-ui-bridge--${firstText(uiBridge.tone, 'ok')}`">
      <div class="selp-ui-bridge-main">
        <span>UI Bridge · {{ firstText(uiBridge.state, 'runtime') }}</span>
        <strong>{{ firstText(uiBridge.title, 'Loop 桥接状态') }}</strong>
        <small>{{ firstText(uiBridge.detail, '后端 runtime 正在统一员工空间、编制图谱和完整 Loop 的展示意图。') }}</small>
        <div class="selp-ui-bridge-actions">
          <router-link v-if="uiBridgeDutyRosterLocation" :to="uiBridgeDutyRosterLocation">去编制图谱</router-link>
          <router-link v-if="uiBridgeEmployeeSpaceLocation" :to="uiBridgeEmployeeSpaceLocation">去员工空间</router-link>
          <button
            v-if="canReviewGovernanceAudit || governanceReviewBusy"
            type="button"
            :disabled="governanceReviewBusy"
            @click="$emit('review')"
          >
            {{ governanceReviewBusy ? '复核中...' : '人工复核治理审计' }}
          </button>
        </div>
        <small v-if="governanceReviewResult" class="selp-ui-bridge-review selp-ui-bridge-review--ok">
          治理审计已复核：{{ asRecord(governanceReviewResult.summary).health || 'ok' }}
        </small>
        <small v-if="governanceReviewError" class="selp-ui-bridge-review selp-ui-bridge-review--bad">
          {{ governanceReviewError }}
        </small>
      </div>
      <div class="selp-ui-bridge-surfaces" role="list" aria-label="三端职责">
        <div role="listitem">
          <span>员工空间</span>
          <strong>{{ firstText(employeeSpaceBridge.role, 'execution_surface') }}</strong>
          <small>{{ firstText(employeeSpaceBridge.cta, '看执行现场') }}</small>
        </div>
        <div role="listitem">
          <span>编制图谱</span>
          <strong>{{ firstText(dutyRosterBridge.role, 'governance_surface') }}</strong>
          <small>{{ firstText(dutyRosterBridge.cta, '查看编制准入') }}</small>
        </div>
        <div role="listitem">
          <span>主动作</span>
          <strong>{{ firstText(uiBridgeGovernanceAction.label, uiBridge.primary_action, 'observe') }}</strong>
          <small>{{ firstText(uiBridgeGovernanceAction.status, uiBridge.primary_surface, 'self_evolution_loop') }} · {{ firstText(uiBridgeGovernanceAction.view, uiBridge.primary_view, 'department') }}</small>
        </div>
        <div role="listitem">
          <span>目标员工</span>
          <strong>{{ firstText(uiBridge.primary_employee_id, uiBridgeTargets[0], '—') }}</strong>
          <small>{{ uiBridgeTargets.length ? `targets ${uiBridgeTargets.length}` : '无定向目标' }}</small>
        </div>
      </div>
      <div v-if="uiBridgeActions.length || uiBridgeTargets.length" class="selp-ui-bridge-foot">
        <span v-if="uiBridgePath.length">path: {{ uiBridgePath.join(' -> ') }}</span>
        <span v-if="uiBridgeGovernanceAction.id">governance: {{ uiBridgeGovernanceAction.id }} · {{ uiBridgeGovernanceAction.requires_admin === true ? 'admin-only' : (uiBridgeGovernanceAction.executable === false ? 'view-only' : 'executable') }}</span>
        <span v-if="uiBridgeActions.length">{{ uiBridgeActions.slice(0, 4).join(' / ') }}</span>
        <small v-if="uiBridgeBlockedIds.length">isolated: {{ uiBridgeBlockedIds.slice(0, 8).join(' / ') }}</small>
        <small v-if="uiBridgeTargets.length">targets: {{ uiBridgeTargets.slice(0, 8).join(' / ') }}</small>
        <small v-if="governanceAuditLast.action">
          last governance: {{ governanceAuditLast.action }} · {{ governanceAuditLast.status || (governanceAuditLast.ok === false ? 'failed' : 'success') }}<template v-if="governanceAuditLastSummary"> · {{ governanceAuditLastSummary }}</template><template v-if="governanceAuditLastTargets.length"> · {{ governanceAuditLastTargets.slice(0, 4).join(' / ') }}</template>
        </small>
      </div>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
