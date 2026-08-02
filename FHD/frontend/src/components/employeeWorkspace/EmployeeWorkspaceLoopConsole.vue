<script setup lang="ts">
import type { LoopRuntimeConsole } from '@/composables/useLoopRuntimeConsole'

const props = defineProps<{
  loop: LoopRuntimeConsole
  routeFocusedEmployeeId: string
  routeFocusedEmployeeInWorkspace: boolean
  showManagementLoopPanels: boolean
}>()

const {
  loopStatusLabel,
  loopAlignedInDeployedCount,
  loopAlignedPlannedCount,
  loopActiveGates,
  loopActiveGateBlockingKeys,
  loopFirstText,
  loopArray,
  loopString,
  loopNumber,
  loopRuntimeContractPrimaryRoute,
  loopFocusedEmployeeId,
  loopOpenRunCount,
  loopNotDeployedCount,
  loopOutOfRosterCount,
  loopRuntimeContractStatus,
  loopRuntimeSurfaceIncidentSummary,
  loopRuntimeSurfaceReadiness,
  loopRuntimeContractOk,
  loopRuntimePrimaryRouteLocation,
  loopRuntimePrimaryRouteLabel,
  loopRuntimeSurfaceReadinessCards,
  loopRuntimeSchemaVersion,
  loopRuntimeSurfaceIncidents,
  loopRuntimeTruthCards,
  loopRuntimeFreshnessCards,
  refreshLoopRuntime,
  dutyRosterLoopLocation,
  dutyRosterDepartmentLocation,
  dutyRosterGovernanceLocation,
  dutyRosterEmployeeLocation,
  loopRuntimeCards,
  loopWorkspaceActionCards,
  loopFocusedWorkerTaskCard,
  loopPipelineStages,
  loopActiveGateCards,
  loopParticipantIds,
  loopParticipantDisplay,
  loopWorkerTaskCards,
  loopWorkOrderCards,
  loopEmployeeSeparationMatrix,
  loopRoleGroups,
  loopIsolationCards,
  loopDiagnosis,
  loopGovernanceBridge,
  loopGovernanceAuditLast,
  loopGovernanceAuditLastSummary,
  loopGovernanceAuditLastTargets,
  loopGovernanceAuditSummary,
  loopBridgeBlockedEmployeeIds,
} = props.loop
</script>

<template>
  <div v-if="showManagementLoopPanels" class="ews-loop-console" role="region" aria-label="当前自进化循环员工">
    <div class="ews-loop-cockpit">
      <div class="ews-loop-cockpit-copy">
        <span>循环驾驶舱</span>
        <strong>上岗员工正在执行自进化/自维护流程线</strong>
        <p>
          员工空间只展示真实上岗工位的执行现场；补登记、隔离、治理审计这些高风险动作统一回到编制图谱处理。
        </p>
      </div>
      <div class="ews-loop-cockpit-meter" aria-label="循环总体状态">
        <span>{{ loopStatusLabel }}</span>
        <strong>{{ loopAlignedInDeployedCount }}/{{ loopAlignedPlannedCount }}</strong>
        <small>on-duty coverage</small>
      </div>
      <div class="ews-loop-cockpit-meter ews-loop-cockpit-meter--gate" aria-label="Loop 门禁状态">
        <span>{{ loopActiveGates.ok === false ? '异常' : '正常' }}</span>
        <strong>{{ loopActiveGates.blocking_count ?? 0 }}</strong>
        <small>阻断中</small>
      </div>
    </div>

    <div class="ews-loop-role-map" aria-label="员工空间、编制图谱与完整 Loop 分工">
      <div
        class="ews-loop-role-map-node ews-loop-role-map-node--active"
        :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface) === 'employee_space' }"
      >
        <span>员工空间</span>
        <strong>执行现场</strong>
        <small>看上岗员工、任务 step、证据回写</small>
        <small>{{ loopFocusedEmployeeId ? `focus ${loopFocusedEmployeeId}` : `${loopOpenRunCount} open runs` }}</small>
      </div>
      <div class="ews-loop-role-map-arrow">↔</div>
      <div
        class="ews-loop-role-map-node"
        :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface) === 'duty_roster_graph' }"
      >
        <span>排班图谱</span>
        <strong>治理闸门</strong>
        <small>补登记、隔离非编制、审计复核</small>
        <small>{{ loopNotDeployedCount }} pending deploy · {{ loopOutOfRosterCount }} isolated risk</small>
      </div>
      <div class="ews-loop-role-map-arrow">→</div>
      <div
        class="ews-loop-role-map-node"
        :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface) === 'self_evolution_loop_runtime' }"
      >
        <span>运行时面板</span>
        <strong>完整链路</strong>
        <small>状态检查、模块异常、时间线</small>
        <small>{{ loopFirstText(loopRuntimeContractPrimaryRoute.view, '运行时') }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }}</small>
      </div>
    </div>

    <div
      class="ews-loop-directive"
      :class="loopRuntimeContractStatus.tone === 'bad' ? 'ews-loop-directive--bad' : (loopNumber(loopRuntimeSurfaceIncidentSummary.total) ? 'ews-loop-directive--warn' : 'ews-loop-directive--ok')"
      aria-label="Loop 下一步动作"
    >
      <div class="ews-loop-directive-copy">
        <span>下一步操作</span>
        <strong>{{ loopFirstText(loopRuntimeContractStatus.label, loopRuntimeSurfaceReadiness.title, loopRuntimeContractOk ? 'Loop 可继续观察' : '需要处理运行契约') }}</strong>
        <small>{{ loopFirstText(loopRuntimeContractStatus.detail, loopRuntimeContractPrimaryRoute.detail, loopRuntimeSurfaceReadiness.detail, '后端 runtime 会给出下一步 surface 和 action') }}</small>
      </div>
      <div class="ews-loop-directive-meta">
        <span>{{ loopFirstText(loopRuntimeContractPrimaryRoute.action, loopRuntimeContractStatus.primary_action, 'watch_loop') }}</span>
        <strong>{{ loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface, 'employee_space') }}</strong>
        <small>{{ loopRuntimeContractPrimaryRoute.requires_admin ? '仅管理员' : '操作员' }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }}</small>
        <small v-if="loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0])">target {{ loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
      </div>
      <router-link :to="loopRuntimePrimaryRouteLocation" class="ews-loop-directive-link">{{ loopRuntimePrimaryRouteLabel }}</router-link>
    </div>

    <div class="ews-loop-section-head" aria-label="三端健康对照说明">
      <span>模块就绪</span>
      <strong>三端对照，断点不混在员工卡里</strong>
      <small>员工空间 / 排班图谱 / 运行时面板 同源读取状态检查；未知不当作故障。</small>
      <div class="ews-loop-section-legend" aria-label="就绪三态图例">
        <span class="ews-loop-section-dot ews-loop-section-dot--ok">就绪</span>
        <span class="ews-loop-section-dot ews-loop-section-dot--bad">异常</span>
        <span class="ews-loop-section-dot ews-loop-section-dot--warn">未知</span>
      </div>
    </div>

    <div class="ews-loop-surface-grid" aria-label="三端模块就绪">
      <div
        v-for="surface in loopRuntimeSurfaceReadinessCards"
        :key="surface.key"
        class="ews-loop-surface-card"
        :class="`ews-loop-surface-card--${surface.tone}`"
      >
        <span>{{ surface.label }}</span>
        <strong>{{ surface.stateLabel }}</strong>
        <small>{{ surface.role }} · {{ surface.action }}</small>
        <small>{{ surface.target }} / {{ surface.view }}</small>
        <em>{{ surface.missing.length ? surface.missing.slice(0, 4).join(' / ') : surface.detail }}</em>
        <router-link
          v-if="surface.known"
          :to="loopRuntimePrimaryRouteLocation"
          :aria-label="`${surface.label} ${surface.ctaLabel}：${surface.detail}`"
          :title="`${surface.label} · ${surface.target} / ${surface.view}`"
        >{{ surface.ctaLabel }}</router-link>
        <span
          v-else
          class="ews-loop-surface-wait"
          :aria-label="`${surface.label} 等待状态：${surface.detail}`"
          :title="`${surface.label} · ${surface.target} / ${surface.view}`"
        >{{ surface.ctaLabel }}</span>
        <small v-if="surface.known" class="ews-loop-surface-route-note">统一入口 · {{ loopRuntimePrimaryRouteLabel }}</small>
        <small class="ews-loop-surface-source-note">{{ surface.sourceLabel }}</small>
      </div>
    </div>

    <div class="ews-loop-truth-strip" aria-label="Loop 真实数据来源">
      <div
        class="ews-loop-truth-card ews-loop-truth-card--primary"
        :class="loopRuntimeContractStatus.tone === 'bad' ? 'ews-loop-truth-card--bad' : (loopNumber(loopRuntimeSurfaceIncidentSummary.total) ? 'ews-loop-truth-card--warn' : 'ews-loop-truth-card--ok')"
      >
        <span>主状态</span>
        <strong>{{ loopFirstText(loopRuntimeContractStatus.state, loopRuntimeSurfaceIncidentSummary.status, loopRuntimeContractOk ? '正常' : '异常') }}</strong>
        <small>{{ loopFirstText(loopRuntimeContractPrimaryRoute.action, loopRuntimeContractStatus.primary_action, loopRuntimeSurfaceIncidentSummary.primary_action, loopRuntimeSurfaceReadiness.action, loopRuntimeContractOk ? 'all clear' : 'inspect contract') }} -> {{ loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface, 'self_evolution_loop_runtime') }}</small>
        <small v-if="loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0])">target employee · {{ loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
        <small>全局={{ loopRuntimeContractStatus.global_ok === false ? '异常' : '正常' }} · 所有模块={{ loopRuntimeContractStatus.all_surfaces_ok === false ? '异常' : '正常' }}</small>
        <small>view={{ loopFirstText(loopRuntimeContractPrimaryRoute.view, 'runtime') }} · label={{ loopFirstText(loopRuntimeContractPrimaryRoute.label, loopRuntimePrimaryRouteLabel) }}</small>
        <small>{{ loopRuntimeContractPrimaryRoute.requires_admin ? '仅管理员' : '操作员' }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }} · {{ loopFirstText(loopRuntimeContractPrimaryRoute.detail, '按后端路由跳转') }}</small>
        <router-link :to="loopRuntimePrimaryRouteLocation">{{ loopRuntimePrimaryRouteLabel }}</router-link>
      </div>
      <div
        v-for="item in loopRuntimeTruthCards"
        :key="item.key"
        class="ews-loop-truth-card"
        :class="`ews-loop-truth-card--${item.tone}`"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </div>
    </div>

    <div v-if="loopRuntimeSurfaceIncidents.length" class="ews-loop-incident-list" aria-label="员工空间 contract incidents">
      <div
        v-for="incident in loopRuntimeSurfaceIncidents"
        :key="loopFirstText(incident.id, incident.action, incident.surface)"
        class="ews-loop-incident"
        :class="`ews-loop-incident--${loopFirstText(incident.severity, 'bad')}`"
      >
        <span>{{ loopFirstText(incident.surface, 'employee_space') }} · {{ loopFirstText(incident.severity, 'bad') }}</span>
        <strong>{{ loopFirstText(incident.title, 'Surface contract incident') }}</strong>
        <small>{{ loopFirstText(incident.action, 'inspect_runtime_contract') }} -> {{ loopFirstText(incident.target_surface, 'self_evolution_loop_runtime') }}</small>
        <small>target view · {{ loopFirstText(incident.target_view, loopRuntimeContractPrimaryRoute.view, 'runtime') }}</small>
        <small>{{ incident.requires_admin ? '仅管理员' : '操作员' }} · {{ incident.executable ? '可执行' : '仅导航' }} · {{ loopFirstText(incident.id, '状态:员工空间') }}</small>
        <small>{{ loopFirstText(incident.source, 'contract_validation') }} · {{ loopFirstText(incident.schema_version, loopRuntimeSchemaVersion) }} · {{ loopFirstText(incident.created_at, 'time unknown') }}</small>
        <em>{{ loopArray(incident.missing).map((item) => loopString(item)).filter(Boolean).slice(0, 5).join(' / ') || loopFirstText(incident.detail, 'missing dependencies') }}</em>
        <router-link :to="loopRuntimePrimaryRouteLocation">{{ loopRuntimePrimaryRouteLabel }}</router-link>
      </div>
    </div>

    <div class="ews-loop-freshness-strip" aria-label="Loop 数据新鲜度">
      <div
        v-for="item in loopRuntimeFreshnessCards"
        :key="item.key"
        class="ews-loop-freshness-card"
        :class="`ews-loop-freshness-card--${item.tone}`"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </div>
    </div>

    <div class="ews-loop-console-head">
      <div>
        <span class="ews-loop-workers-k">自进化桥接</span>
        <strong>自维护 Loop 正在把后端员工调度映射到工位</strong>
      </div>
      <div class="ews-loop-console-actions">
        <button type="button" class="ews-loop-console-status" @click="refreshLoopRuntime">
          {{ loopStatusLabel }}
        </button>
        <router-link :to="dutyRosterLoopLocation" class="ews-loop-console-link">完整 Loop</router-link>
        <router-link :to="dutyRosterDepartmentLocation" class="ews-loop-console-link">编制图谱</router-link>
      </div>
    </div>

    <div class="ews-loop-cards" role="list" aria-label="自维护 loop 摘要">
      <div
        v-for="card in loopRuntimeCards"
        :key="card.key"
        class="ews-loop-card"
        :class="`ews-loop-card--${card.tone}`"
        role="listitem"
      >
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>

    <div class="ews-loop-next-actions" aria-label="员工空间下一步建议">
      <router-link
        v-for="action in loopWorkspaceActionCards"
        :key="action.key"
        :to="action.to"
        class="ews-loop-next-action"
        :class="`ews-loop-next-action--${action.tone}`"
      >
        <span>{{ action.label }}</span>
        <strong>{{ action.title }}</strong>
        <small>{{ action.detail }}</small>
        <em>{{ action.cta }} →</em>
      </router-link>
    </div>

    <div
      v-if="loopFocusedWorkerTaskCard"
      class="ews-loop-focus-card"
      :class="`ews-loop-focus-card--${loopFocusedWorkerTaskCard.tone}`"
      aria-label="当前聚焦员工 loop 状态"
    >
      <span>关注员工</span>
      <strong>{{ loopFocusedWorkerTaskCard.id }} · {{ loopFocusedWorkerTaskCard.role }}</strong>
      <small>{{ loopFocusedWorkerTaskCard.department }} · {{ loopFocusedWorkerTaskCard.rosterLabel }} · {{ loopFocusedWorkerTaskCard.dutyLabel }}</small>
      <em>{{ loopFocusedWorkerTaskCard.eventCount }} steps · {{ loopFocusedWorkerTaskCard.latestStatus }}</em>
      <router-link :to="dutyRosterEmployeeLocation(loopFocusedWorkerTaskCard.id)">回编制图谱定位治理状态</router-link>
    </div>
    <div
      v-else-if="loopFocusedEmployeeId"
      class="ews-loop-focus-card ews-loop-focus-card--warn"
      aria-label="当前聚焦员工没有 loop 工单"
    >
      <span>关注员工</span>
      <strong>{{ loopFocusedEmployeeId }}</strong>
      <small>该员工当前没有 runtime/ledger 工单回写；页面不伪造任务。</small>
      <em>如果它应该参与 loop，请检查后端 participants 或 run_timelines 是否写 employee_id。</em>
      <router-link :to="dutyRosterEmployeeLocation(loopFocusedEmployeeId)">回编制图谱查编制状态</router-link>
    </div>

    <div class="ews-loop-pipeline" role="list" aria-label="自进化 loop 流水线">
      <div
        v-for="stage in loopPipelineStages"
        :key="stage.key"
        class="ews-loop-stage"
        :class="`ews-loop-stage--${stage.tone}`"
        role="listitem"
      >
        <span>{{ stage.label }}</span>
        <strong>{{ stage.count || (stage.tone === 'idle' ? '待命' : '进行中') }}</strong>
        <small>{{ stage.latest || stage.hint }}</small>
        <em v-if="stage.workers.length">{{ stage.workers.slice(0, 3).join(' / ') }}</em>
      </div>
    </div>

    <div v-if="loopActiveGateCards.length" class="ews-loop-gate-board" role="list" aria-label="当前 loop 门禁">
      <div
        v-for="gate in loopActiveGateCards"
        :key="gate.key"
        class="ews-loop-gate"
        :class="`ews-loop-gate--${gate.tone}`"
        role="listitem"
      >
        <span>{{ gate.label }}</span>
        <strong>{{ gate.value }}</strong>
        <small>{{ gate.sub }}</small>
      </div>
    </div>

    <div class="ews-loop-workers-list" :class="{ 'ews-loop-workers-list--empty': !loopParticipantIds.length }">
      <router-link
        v-for="id in loopParticipantIds"
        :key="id"
        :to="dutyRosterEmployeeLocation(id)"
        class="ews-loop-worker-chip ews-loop-worker-chip--link"
      >
        {{ loopParticipantDisplay(id) }}
      </router-link>
      <p v-if="!loopParticipantIds.length" class="ews-loop-workers-empty">
        当前 ledger 未暴露参与员工，等待后端 employee_id / actor 回写。
      </p>
    </div>

    <div v-if="loopWorkerTaskCards.length" class="ews-loop-task-board" aria-label="上岗员工 loop 任务工作台">
      <router-link
        v-for="worker in loopWorkerTaskCards"
        :key="worker.id"
        :to="dutyRosterEmployeeLocation(worker.id)"
        class="ews-loop-task-card"
        :class="`ews-loop-task-card--${worker.tone}`"
      >
        <span>{{ worker.role }}</span>
        <strong>{{ worker.id }}</strong>
        <small>{{ worker.department }} · {{ worker.rosterLabel }} · {{ worker.dutyLabel }}</small>
        <em>{{ worker.eventCount }} steps · {{ worker.latestStatus }}</em>
        <b v-if="worker.latestLabel">{{ worker.latestLabel }}</b>
      </router-link>
    </div>

    <div v-if="loopWorkOrderCards.length" class="ews-loop-work-orders" aria-label="本轮员工工作单">
      <router-link
        v-for="order in loopWorkOrderCards"
        :key="order.key"
        :to="order.to"
        class="ews-loop-work-order"
        :class="`ews-loop-work-order--${order.tone}`"
      >
        <span>{{ order.stage }}</span>
        <strong>{{ order.title }}</strong>
        <small>{{ order.status }} · {{ order.stepCount }} steps</small>
        <em v-if="order.workers.length">{{ order.workers.slice(0, 4).join(' / ') }}</em>
        <b>{{ order.runId }}</b>
      </router-link>
    </div>
    <div v-else class="ews-loop-work-orders-empty" aria-label="本轮没有员工工作单">
      <span>循环工单</span>
      <strong>没有记录工单</strong>
      <small>当前运行时间线没有可聚合的员工任务；等待后端写入运行 ID / 员工 ID / 步骤。</small>
    </div>

    <div class="ews-loop-separation-matrix" aria-label="员工身份隔离矩阵">
      <div
        v-for="item in loopEmployeeSeparationMatrix"
        :key="item.key"
        class="ews-loop-separation-cell"
        :class="`ews-loop-separation-cell--${item.tone}`"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.sub }}</small>
      </div>
    </div>

    <div v-if="loopRoleGroups.length" class="ews-loop-role-board" aria-label="自进化 loop 角色分组">
      <div v-for="group in loopRoleGroups" :key="group.key" class="ews-loop-role-group">
        <span>{{ group.label }}</span>
        <strong>{{ group.workers.length }}</strong>
        <small>{{ group.workers.slice(0, 3).join(' / ') }}</small>
      </div>
    </div>

    <div class="ews-loop-isolation" aria-label="员工隔离状态">
      <div
        v-for="card in loopIsolationCards"
        :key="card.key"
        class="ews-loop-isolation-card"
        :class="`ews-loop-isolation-card--${card.tone}`"
      >
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>

    <div class="ews-loop-diagnosis" :class="`ews-loop-diagnosis--${loopDiagnosis.tone}`">
      <div>
        <span>诊断</span>
        <strong>{{ loopDiagnosis.title }}</strong>
        <p>{{ loopDiagnosis.detail }}</p>
        <div class="ews-loop-governance-bridge" :class="`ews-loop-governance-bridge--${loopGovernanceBridge.tone}`">
          <span>{{ loopGovernanceBridge.label }}</span>
          <strong>{{ loopGovernanceBridge.title }}</strong>
          <small>{{ loopGovernanceBridge.detail }}</small>
          <small class="ews-loop-governance-action">
            {{ loopGovernanceBridge.actionLabel }} · {{ loopGovernanceBridge.actionStatus }} · {{ loopGovernanceBridge.actionRequiresAdmin ? '仅管理员' : (loopGovernanceBridge.actionExecutable ? '可执行' : '仅查看') }}
          </small>
          <small v-if="loopGovernanceAuditLast.action" class="ews-loop-governance-audit">
            最近治理：{{ loopGovernanceAuditLast.action }} · {{ loopGovernanceAuditLast.status || (loopGovernanceAuditLast.ok === false ? 'failed' : 'success') }}<template v-if="loopGovernanceAuditLastSummary"> · {{ loopGovernanceAuditLastSummary }}</template><template v-if="loopGovernanceAuditLastTargets.length"> · {{ loopGovernanceAuditLastTargets.slice(0, 4).join(' / ') }}</template>
          </small>
          <small v-if="loopGovernanceAuditSummary.recent_count != null" class="ews-loop-governance-health">
            治理健康：{{ loopGovernanceAuditSummary.health || 'ok' }} · {{ loopGovernanceAuditSummary.success_count ?? 0 }} ok · {{ loopGovernanceAuditSummary.failure_count ?? 0 }} failed · 连续失败 {{ loopGovernanceAuditSummary.consecutive_failures ?? 0 }}
          </small>
          <small v-if="loopActiveGates.blocking_count != null" class="ews-loop-governance-gates">
            当前检查：{{ loopActiveGates.ok === false ? '异常' : '正常' }} · {{ loopActiveGates.blocking_count ?? 0 }} 阻断中<template v-if="loopActiveGateBlockingKeys.length"> · {{ loopActiveGateBlockingKeys.join(' / ') }}</template>
          </small>
          <small v-if="loopBridgeBlockedEmployeeIds.length" class="ews-loop-governance-isolation">
            隔离非编制：{{ loopBridgeBlockedEmployeeIds.slice(0, 5).join(' / ') }}
          </small>
          <router-link :to="dutyRosterGovernanceLocation">{{ loopGovernanceBridge.cta }}</router-link>
        </div>
        <div class="ews-loop-diagnosis-links">
          <router-link :to="dutyRosterLoopLocation">打开完整 Loop</router-link>
          <router-link :to="dutyRosterDepartmentLocation">查看编制覆盖</router-link>
        </div>
      </div>
      <ul>
        <li v-for="action in loopDiagnosis.actions" :key="action">{{ action }}</li>
      </ul>
    </div>

    <div v-if="showManagementLoopPanels && routeFocusedEmployeeId && !routeFocusedEmployeeInWorkspace" class="ews-route-focus-warning">
      <strong>当前定位员工不在员工空间工位里</strong>
      <span>{{ routeFocusedEmployeeId }} 属于编制/管理图谱上下文，但没有出现在企业 Mod 栈工位集合；这说明它不是当前工作空间的上岗工位。</span>
      <router-link :to="dutyRosterEmployeeLocation(routeFocusedEmployeeId)">回编制图谱定位</router-link>
    </div>
  </div>
</template>

<style scoped src="./EmployeeWorkspaceLoopConsole.css"></style>
