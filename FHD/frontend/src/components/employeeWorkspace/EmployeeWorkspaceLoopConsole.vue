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

<style scoped>
/* —— 自进化 Loop 控制台：让后端员工调度在工位页可见 —— */
.ews-loop-console {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 13px 14px;
  border: 1px solid #dbe3ef;
  border-left: 4px solid #0f766e;
  border-radius: 12px;
  background:
    radial-gradient(circle at 8% 0%, rgba(20, 184, 166, 0.13), transparent 34%),
    linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.ews-loop-console-head,
.ews-loop-workers-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ews-loop-console-head {
  justify-content: space-between;
}

.ews-loop-console-head > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.ews-loop-workers-k {
  color: #0f766e;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.ews-loop-console-head strong {
  color: #0f172a;
  font-size: 14px;
}

.ews-loop-console-status {
  flex: 0 0 auto;
  border: 1px solid rgba(15, 118, 110, 0.22);
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 900;
  padding: 6px 10px;
}

.ews-loop-console-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ews-loop-console-link {
  flex: 0 0 auto;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
}

.ews-loop-card--run {
  background: #ecfeff;
  border-color: rgba(20, 184, 166, 0.20);
}

.ews-loop-card--ok {
  background: #f0fdf4;
}

.ews-loop-card--warn {
  background: #fffbeb;
}

.ews-loop-card--bad {
  background: #fef2f2;
}

.ews-loop-card span,
.ews-loop-card small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 16px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-worker-chip {
  max-width: 220px;
  overflow: hidden;
  padding: 6px 9px;
  border-radius: 999px;
  background: #ccfbf1;
  color: #134e4a;
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-worker-chip--link {
  text-decoration: none;
}

.ews-loop-worker-chip--link:hover {
  background: #99f6e4;
}

.ews-loop-workers-list--empty {
  align-items: flex-start;
}

.ews-loop-role-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-role-group {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  border: 1px dashed rgba(15, 118, 110, 0.20);
  background: rgba(240, 253, 250, 0.70);
}

.ews-loop-role-group span,
.ews-loop-role-group small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-role-group span {
  color: #0f766e;
  font-weight: 900;
}

.ews-loop-role-group strong {
  color: #0f172a;
  font-size: 14px;
}

.ews-loop-role-group small {
  grid-column: 1 / -1;
}

.ews-loop-isolation {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-isolation-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.70);
}

.ews-loop-isolation-card--run {
  border-color: rgba(20, 184, 166, 0.18);
  background: #ecfeff;
}

.ews-loop-isolation-card--ok {
  background: #f0fdf4;
}

.ews-loop-isolation-card--warn {
  background: #fffbeb;
}

.ews-loop-isolation-card--bad {
  background: #fef2f2;
}

.ews-loop-isolation-card span,
.ews-loop-isolation-card small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-isolation-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-console,
.ews-loop-console > * {
  --loop-compact-card-min: 145px;
  --loop-detail-card-min: 220px;
  min-width: 0;
}

.ews-loop-cockpit {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, 160px) minmax(120px, 160px);
  gap: 10px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.18), transparent 32%),
    radial-gradient(circle at 100% 0%, rgba(14, 165, 233, 0.14), transparent 34%),
    linear-gradient(135deg, rgba(248, 250, 252, 0.94), rgba(255, 255, 255, 0.82));
}

.ews-loop-cockpit-copy {
  min-width: 0;
}

.ews-loop-cockpit-copy span,
.ews-loop-cockpit-meter span {
  display: block;
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-cockpit-copy strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 17px;
  font-weight: 950;
  letter-spacing: -0.02em;
}

.ews-loop-cockpit-copy p {
  max-width: 760px;
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.ews-loop-cockpit-meter {
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 14px;
  background: rgba(236, 254, 255, 0.82);
}

.ews-loop-cockpit-meter--gate {
  border-color: rgba(99, 102, 241, 0.18);
  background: rgba(238, 242, 255, 0.82);
}

.ews-loop-cockpit-meter strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 22px;
  font-weight: 950;
  letter-spacing: -0.04em;
}

.ews-loop-cockpit-meter small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
}

.ews-loop-role-map {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 8% 20%, rgba(20, 184, 166, 0.14), transparent 26%),
    radial-gradient(circle at 92% 10%, rgba(14, 165, 233, 0.12), transparent 30%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.04), rgba(255, 255, 255, 0.84));
}

.ews-loop-role-map-node {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
}

.ews-loop-role-map-node--active {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.92), rgba(240, 253, 250, 0.76));
}

.ews-loop-role-map-node--route {
  border-color: rgba(14, 165, 233, 0.38);
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.1), 0 14px 32px rgba(14, 165, 233, 0.1);
}

.ews-loop-role-map-node span,
.ews-loop-role-map-node strong,
.ews-loop-role-map-node small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-role-map-node span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-role-map-node strong {
  margin-top: 4px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 950;
}

.ews-loop-role-map-node small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.35;
}

.ews-loop-role-map-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  color: rgba(15, 118, 110, 0.78);
  font-size: 18px;
  font-weight: 950;
}

.ews-loop-directive {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.7fr) max-content;
  gap: 10px;
  align-items: center;
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 0% 0%, rgba(45, 212, 191, 0.22), transparent 30%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(15, 118, 110, 0.84));
  color: #f8fafc;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.16);
}

.ews-loop-directive--ok {
  background:
    radial-gradient(circle at 0% 0%, rgba(16, 185, 129, 0.24), transparent 30%),
    linear-gradient(135deg, rgba(6, 78, 59, 0.94), rgba(15, 118, 110, 0.86));
}

.ews-loop-directive--warn {
  background:
    radial-gradient(circle at 0% 0%, rgba(251, 191, 36, 0.22), transparent 30%),
    linear-gradient(135deg, rgba(120, 53, 15, 0.94), rgba(180, 83, 9, 0.84));
}

.ews-loop-directive--bad {
  background:
    radial-gradient(circle at 0% 0%, rgba(248, 113, 113, 0.24), transparent 30%),
    linear-gradient(135deg, rgba(127, 29, 29, 0.96), rgba(185, 28, 28, 0.84));
}

.ews-loop-directive-copy,
.ews-loop-directive-meta {
  min-width: 0;
}

.ews-loop-directive-copy span,
.ews-loop-directive-meta span {
  display: block;
  color: rgba(240, 253, 250, 0.78);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-directive-copy strong,
.ews-loop-directive-meta strong {
  display: block;
  margin-top: 4px;
  color: #ffffff;
  font-size: 15px;
  font-weight: 950;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-directive-copy small,
.ews-loop-directive-meta small {
  display: block;
  margin-top: 4px;
  color: rgba(241, 245, 249, 0.78);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.45;
}

.ews-loop-directive-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: end;
  min-width: 0;
  max-width: 100%;
  min-height: 32px;
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
  font-size: 12px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-directive-link:hover {
  background: rgba(255, 255, 255, 0.22);
}

.ews-loop-section-head {
  display: grid;
  grid-template-columns: minmax(0, 0.32fr) minmax(0, 0.68fr);
  gap: 6px 10px;
  align-items: baseline;
  min-width: 0;
  padding: 2px 2px 0;
}

.ews-loop-section-head span,
.ews-loop-section-head strong,
.ews-loop-section-head small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-section-head span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-section-head strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-section-head small {
  grid-column: 1 / -1;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  white-space: normal;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.ews-loop-section-legend {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.ews-loop-section-dot {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 3px 7px;
  border-radius: 999px;
  color: #475569;
  font-size: 10px;
  font-weight: 950;
  line-height: 1;
  white-space: nowrap;
}

.ews-loop-section-dot::before {
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 999px;
  background: currentColor;
  content: '';
}

.ews-loop-section-dot--ok {
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
}

.ews-loop-section-dot--bad {
  background: rgba(239, 68, 68, 0.1);
  color: #b91c1c;
}

.ews-loop-section-dot--warn {
  background: rgba(245, 158, 11, 0.12);
  color: #92400e;
}

.ews-loop-surface-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-surface-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
  isolation: isolate;
}

.ews-loop-surface-card--ok {
  border-color: rgba(16, 185, 129, 0.22);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.92), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.96), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card--bad {
  border-color: rgba(239, 68, 68, 0.24);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.98), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card span,
.ews-loop-surface-card strong,
.ews-loop-surface-card small,
.ews-loop-surface-card em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-surface-card span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-surface-card strong {
  margin-top: 4px;
  color: #0f172a;
  font-size: 16px;
  font-weight: 950;
}

.ews-loop-surface-card small,
.ews-loop-surface-card em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.ews-loop-surface-card a,
.ews-loop-surface-wait {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 8px;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.1);
  color: #0f766e;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-surface-card a:hover {
  background: rgba(15, 118, 110, 0.16);
}

.ews-loop-surface-route-note {
  color: #94a3b8;
}

.ews-loop-surface-source-note {
  color: #94a3b8;
  font-size: 10px;
}

.ews-loop-surface-wait {
  background: rgba(100, 116, 139, 0.1);
  color: #64748b;
  cursor: default;
}

.ews-loop-surface-card a:focus-visible,
.ews-loop-directive-link:focus-visible,
.ews-loop-truth-card a:focus-visible,
.ews-loop-incident a:focus-visible {
  outline: 2px solid rgba(14, 165, 233, 0.72);
  outline-offset: 2px;
}

.ews-loop-directive-copy small,
.ews-loop-surface-card em {
  display: -webkit-box;
  overflow: hidden;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

@media (max-width: 1180px) {
  .ews-loop-cockpit {
    grid-template-columns: 1fr;
  }

  .ews-loop-cockpit-copy p {
    max-width: none;
  }

  .ews-loop-role-map {
    grid-template-columns: 1fr;
  }

  .ews-loop-role-map-arrow {
    min-height: 18px;
    transform: rotate(90deg);
  }

  .ews-loop-directive {
    grid-template-columns: 1fr;
  }

  .ews-loop-directive-link {
    justify-self: start;
  }

  .ews-loop-section-head {
    grid-template-columns: 1fr;
  }

  .ews-loop-surface-grid {
    grid-template-columns: 1fr;
  }

  .ews-loop-truth-card--primary {
    grid-column: auto;
  }

  .ews-loop-freshness-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.ews-loop-truth-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-truth-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.9);
}

.ews-loop-truth-card span,
.ews-loop-truth-card strong,
.ews-loop-truth-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-truth-card span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-truth-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-truth-card small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-truth-card a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-truth-card--run {
  border-color: rgba(14, 165, 233, 0.22);
  background: rgba(240, 249, 255, 0.9);
}

.ews-loop-truth-card--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-truth-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-truth-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(254, 242, 242, 0.9);
}

.ews-loop-truth-card--primary {
  grid-column: span 2;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.16), transparent 34%),
    rgba(255, 255, 255, 0.94);
}

.ews-loop-incident-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-detail-card-min), 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-incident {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 14px;
  background:
    radial-gradient(circle at 0% 0%, rgba(239, 68, 68, 0.12), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-incident--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background:
    radial-gradient(circle at 0% 0%, rgba(245, 158, 11, 0.12), transparent 34%),
    rgba(255, 251, 235, 0.9);
}

.ews-loop-incident span,
.ews-loop-incident strong,
.ews-loop-incident small,
.ews-loop-incident em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-incident span {
  color: #991b1b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-incident strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-incident small,
.ews-loop-incident em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-incident a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-freshness-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  min-width: 0;
  gap: 8px;
}

.ews-loop-freshness-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.88);
}

.ews-loop-freshness-card span,
.ews-loop-freshness-card strong,
.ews-loop-freshness-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-freshness-card span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-freshness-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-freshness-card small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-freshness-card--run {
  border-color: rgba(14, 165, 233, 0.22);
  background: rgba(240, 249, 255, 0.9);
}

.ews-loop-freshness-card--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-freshness-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-next-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-next-action {
  display: block;
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  color: inherit;
  text-decoration: none;
}

.ews-loop-next-action span,
.ews-loop-next-action strong,
.ews-loop-next-action small,
.ews-loop-next-action em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-next-action span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-next-action strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-next-action small,
.ews-loop-next-action em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-next-action em {
  color: #0f766e;
  font-weight: 950;
}

.ews-loop-next-action--run {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.92), rgba(255, 255, 255, 0.88));
}

.ews-loop-next-action--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-next-action--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.92), rgba(255, 255, 255, 0.88));
}

.ews-loop-next-action--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.94), rgba(255, 255, 255, 0.88));
}

.ews-loop-focus-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 15px;
  background:
    radial-gradient(circle at 0% 0%, rgba(14, 165, 233, 0.12), transparent 30%),
    rgba(255, 255, 255, 0.9);
}

.ews-loop-focus-card span,
.ews-loop-focus-card strong,
.ews-loop-focus-card small,
.ews-loop-focus-card em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-focus-card span {
  color: #0369a1;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-focus-card strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-focus-card small,
.ews-loop-focus-card em {
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-focus-card a {
  grid-column: 2;
  grid-row: 1 / span 4;
  padding: 7px 10px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  white-space: nowrap;
}

.ews-loop-focus-card--run {
  border-color: rgba(14, 165, 233, 0.22);
}

.ews-loop-focus-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 0% 0%, rgba(239, 68, 68, 0.12), transparent 30%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-focus-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background:
    radial-gradient(circle at 0% 0%, rgba(245, 158, 11, 0.12), transparent 30%),
    rgba(255, 251, 235, 0.9);
}

.ews-loop-pipeline,
.ews-loop-gate-board {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-gate-board {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.ews-loop-stage,
.ews-loop-gate {
  position: relative;
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.88);
}

.ews-loop-stage::before {
  content: "";
  position: absolute;
  top: 13px;
  right: -18px;
  width: 42px;
  height: 2px;
  background: linear-gradient(90deg, rgba(20, 184, 166, 0.6), rgba(59, 130, 246, 0));
}

.ews-loop-stage:last-child::before {
  display: none;
}

.ews-loop-stage span,
.ews-loop-gate span {
  display: block;
  color: #64748b;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-stage strong,
.ews-loop-gate strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-stage small,
.ews-loop-gate small,
.ews-loop-stage em {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-stage--run,
.ews-loop-gate--ok {
  border-color: rgba(20, 184, 166, 0.2);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.95), rgba(240, 253, 244, 0.92));
}

.ews-loop-stage--bad,
.ews-loop-gate--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.95), rgba(255, 247, 237, 0.92));
}

.ews-loop-stage--idle {
  opacity: 0.72;
}

.ews-loop-task-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-task-card {
  display: block;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    radial-gradient(circle at 12% 0%, rgba(20, 184, 166, 0.14), transparent 34%),
    rgba(255, 255, 255, 0.88);
  color: inherit;
  text-decoration: none;
}

.ews-loop-task-card span,
.ews-loop-task-card strong,
.ews-loop-task-card small,
.ews-loop-task-card em,
.ews-loop-task-card b {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-task-card span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-task-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-task-card small,
.ews-loop-task-card em,
.ews-loop-task-card b {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-task-card b {
  color: #334155;
  font-weight: 900;
}

.ews-loop-task-card--run {
  border-color: rgba(20, 184, 166, 0.24);
  box-shadow: 0 10px 24px rgba(20, 184, 166, 0.08);
}

.ews-loop-task-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 12% 0%, rgba(239, 68, 68, 0.14), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-task-card--idle {
  opacity: 0.76;
}

.ews-loop-work-orders {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-work-order {
  display: block;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    radial-gradient(circle at 100% 0%, rgba(14, 165, 233, 0.12), transparent 34%),
    rgba(248, 250, 252, 0.9);
  color: inherit;
  text-decoration: none;
}

.ews-loop-work-order span,
.ews-loop-work-order strong,
.ews-loop-work-order small,
.ews-loop-work-order em,
.ews-loop-work-order b {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-work-order span {
  color: #0369a1;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-work-order strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-work-order small,
.ews-loop-work-order em,
.ews-loop-work-order b {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-work-order b {
  color: #334155;
  font-weight: 850;
}

.ews-loop-work-order--run {
  border-color: rgba(14, 165, 233, 0.22);
}

.ews-loop-work-order--ok {
  border-color: rgba(34, 197, 94, 0.18);
  background:
    radial-gradient(circle at 100% 0%, rgba(34, 197, 94, 0.12), transparent 34%),
    rgba(240, 253, 244, 0.9);
}

.ews-loop-work-order--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 100% 0%, rgba(239, 68, 68, 0.14), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-work-orders-empty {
  padding: 11px;
  border: 1px dashed rgba(245, 158, 11, 0.38);
  border-radius: 14px;
  background: rgba(255, 251, 235, 0.88);
}

.ews-loop-work-orders-empty span,
.ews-loop-work-orders-empty strong,
.ews-loop-work-orders-empty small {
  display: block;
}

.ews-loop-work-orders-empty span {
  color: #92400e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-work-orders-empty strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-work-orders-empty small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.ews-loop-separation-matrix {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-separation-cell {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.03), rgba(20, 184, 166, 0.05)),
    rgba(255, 255, 255, 0.9);
}

.ews-loop-separation-cell span,
.ews-loop-separation-cell strong,
.ews-loop-separation-cell small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-separation-cell span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-separation-cell strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 950;
}

.ews-loop-separation-cell small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-separation-cell--run {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.95), rgba(255, 255, 255, 0.9));
}

.ews-loop-separation-cell--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-separation-cell--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.95), rgba(255, 255, 255, 0.9));
}

.ews-loop-separation-cell--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.95), rgba(255, 255, 255, 0.9));
}

@media (max-width: 760px) {
  .ews-loop-cockpit {
    grid-template-columns: minmax(0, 1fr);
  }

  .ews-loop-focus-card {
    grid-template-columns: minmax(0, 1fr);
  }

  .ews-loop-focus-card a {
    grid-column: 1;
    grid-row: auto;
    width: fit-content;
  }

  .ews-loop-truth-strip,
  .ews-loop-freshness-strip,
  .ews-loop-next-actions,
  .ews-loop-pipeline,
  .ews-loop-gate-board,
  .ews-loop-task-board,
  .ews-loop-work-orders,
  .ews-loop-separation-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .ews-loop-truth-strip,
  .ews-loop-freshness-strip,
  .ews-loop-next-actions,
  .ews-loop-pipeline,
  .ews-loop-gate-board,
  .ews-loop-task-board,
  .ews-loop-work-orders,
  .ews-loop-separation-matrix {
    grid-template-columns: minmax(0, 1fr);
  }
}

.ews-loop-diagnosis {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 280px);
  gap: 10px;
  align-items: stretch;
  padding: 10px 11px;
  border-radius: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.72);
}

.ews-loop-diagnosis--run {
  border-color: rgba(20, 184, 166, 0.22);
  background: #ecfeff;
}

.ews-loop-diagnosis--ok {
  background: #f0fdf4;
}

.ews-loop-diagnosis--warn {
  background: #fffbeb;
}

.ews-loop-diagnosis--bad {
  background: #fef2f2;
}

.ews-loop-diagnosis div {
  min-width: 0;
}

.ews-loop-diagnosis span {
  display: block;
  margin-bottom: 2px;
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.05em;
}

.ews-loop-diagnosis strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.ews-loop-diagnosis p {
  margin: 4px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.ews-loop-diagnosis-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.ews-loop-governance-bridge {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 3px 8px;
  align-items: center;
  margin-top: 9px;
  padding: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.82);
}

.ews-loop-governance-bridge--run {
  border-color: rgba(20, 184, 166, 0.22);
  background: rgba(236, 254, 255, 0.9);
}

.ews-loop-governance-bridge--ok {
  border-color: rgba(34, 197, 94, 0.18);
  background: rgba(240, 253, 244, 0.9);
}

.ews-loop-governance-bridge--warn {
  border-color: rgba(245, 158, 11, 0.22);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-governance-bridge--bad {
  border-color: rgba(239, 68, 68, 0.18);
  background: rgba(254, 242, 242, 0.9);
}

.ews-loop-governance-bridge span,
.ews-loop-governance-bridge strong,
.ews-loop-governance-bridge small {
  min-width: 0;
}

.ews-loop-governance-bridge span {
  grid-column: 1;
  margin: 0;
  color: #0f766e;
}

.ews-loop-governance-bridge strong {
  grid-column: 1;
  font-size: 12px;
}

.ews-loop-governance-bridge small {
  grid-column: 1 / -1;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.ews-loop-governance-bridge .ews-loop-governance-isolation {
  color: #b91c1c;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-action {
  color: #0f766e;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-audit {
  color: #0369a1;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-health {
  color: #854d0e;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-gates {
  color: #4338ca;
  font-weight: 900;
}

.ews-loop-governance-bridge a {
  grid-column: 2;
  grid-row: 1 / span 2;
  padding: 6px 9px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
  white-space: nowrap;
}

.ews-loop-diagnosis-links a {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.07);
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-diagnosis ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ews-loop-diagnosis li {
  overflow: hidden;
  padding: 4px 7px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-route-focus-warning {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  padding: 10px 11px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: 11px;
  background: #fffbeb;
}

.ews-route-focus-warning strong {
  color: #92400e;
  font-size: 13px;
  font-weight: 900;
}

.ews-route-focus-warning span {
  grid-column: 1 / -1;
  color: #78350f;
  font-size: 12px;
  line-height: 1.45;
}

.ews-route-focus-warning a {
  grid-row: 1;
  grid-column: 2;
  padding: 5px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-workers-empty {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}

@media (max-width: 1040px) {
  .ews-loop-cards,
  .ews-loop-role-board,
  .ews-loop-isolation {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .ews-loop-console-head {
    align-items: flex-start;
  }

  .ews-loop-cards,
  .ews-loop-role-board,
  .ews-loop-isolation {
    grid-template-columns: 1fr;
  }

  .ews-loop-diagnosis {
    grid-template-columns: 1fr;
  }
}
</style>
