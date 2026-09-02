<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import { asArray, asString, firstText, type AnyRecord } from './runtimeHelpers'
import type { ActiveGateItem } from './useRuntimeContract'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 Runtime contract / active gates / surface incidents 区块）；模板逐字迁移，行为不变。
defineProps<{
  runtimeContractOk: boolean
  runtimeSchemaVersion: string
  runtimeContractValidation: AnyRecord
  runtimeContractRequiredFields: string[]
  runtimeContractMissingFields: string[]
  runtimeSurfaceMissing: string[]
  runtimeContractStatus: AnyRecord
  runtimeSurfaceIncidentSummary: AnyRecord
  runtimeContractPrimaryRoute: AnyRecord
  runtimeSurfaceReadiness: AnyRecord
  runtimeContractDutyRosterLocation: RouteLocationRaw | null
  runtimeContractEmployeeSpaceLocation: RouteLocationRaw | null
  runtimeContractSurfaces: string[]
  runtimeContractGateDependencies: string[]
  runtimeSurfaceReadinessOk: boolean
  runtimeSurfaceKey: string
  runtimeSurfaceIncidents: AnyRecord[]
  runtimeAllSurfaceIncidents: AnyRecord[]
  runtimeSurfaceIncident: AnyRecord
  runtimeContractMissingNested: string[]
  activeGates: AnyRecord
  activeGateItems: ActiveGateItem[]
}>()
</script>

<template>
    <div class="selp-contract" :class="runtimeContractOk ? 'selp-contract--ok' : 'selp-contract--bad'" aria-label="Runtime contract">
      <div class="selp-contract-head">
        <span>Runtime contract</span>
        <strong>{{ runtimeContractOk ? 'trusted' : 'blocked' }} · {{ runtimeSchemaVersion }}</strong>
        <small>
          required {{ runtimeContractValidation.required_count ?? runtimeContractRequiredFields.length }} · missing {{ runtimeContractMissingFields.length + runtimeSurfaceMissing.length }}
          <template v-if="runtimeContractMissingFields.length"> · {{ runtimeContractMissingFields.slice(0, 5).join(' / ') }}</template>
          <template v-else-if="runtimeSurfaceMissing.length"> · {{ runtimeSurfaceMissing.slice(0, 5).join(' / ') }}</template>
        </small>
      </div>
      <div class="selp-contract-grid">
        <div class="selp-contract-primary">
          <span>Primary state</span>
          <strong>{{ firstText(runtimeContractStatus.state, runtimeSurfaceIncidentSummary.status, runtimeContractOk ? 'trusted' : 'blocked') }}</strong>
          <small>{{ firstText(runtimeContractPrimaryRoute.action, runtimeContractStatus.primary_action, runtimeSurfaceIncidentSummary.primary_action, runtimeSurfaceReadiness.action, runtimeContractOk ? 'all clear' : 'inspect contract') }} -> {{ firstText(runtimeContractPrimaryRoute.surface, runtimeContractStatus.primary_target_surface, 'self_evolution_loop_runtime') }}</small>
          <small v-if="firstText(runtimeContractPrimaryRoute.employee_id, asArray(runtimeContractPrimaryRoute.target_employee_ids)[0])">target employee · {{ firstText(runtimeContractPrimaryRoute.employee_id, asArray(runtimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
          <small>global={{ runtimeContractStatus.global_ok === false ? 'blocked' : 'ok' }} · all_surfaces={{ runtimeContractStatus.all_surfaces_ok === false ? 'blocked' : 'ok' }}</small>
          <small>{{ runtimeContractPrimaryRoute.requires_admin ? 'admin-only' : 'operator' }} · {{ runtimeContractPrimaryRoute.executable ? 'executable' : 'navigate-only' }} · {{ firstText(runtimeContractPrimaryRoute.detail, 'route supplied by backend contract_status') }}</small>
          <router-link
            v-if="runtimeContractPrimaryRoute.surface === 'duty_roster_graph' && runtimeContractDutyRosterLocation"
            :to="runtimeContractDutyRosterLocation"
          >
            {{ firstText(runtimeContractPrimaryRoute.label, '打开目标面') }}
          </router-link>
          <router-link
            v-else-if="runtimeContractPrimaryRoute.surface === 'employee_space' && runtimeContractEmployeeSpaceLocation"
            :to="runtimeContractEmployeeSpaceLocation"
          >
            {{ firstText(runtimeContractPrimaryRoute.label, '打开目标面') }}
          </router-link>
          <small v-else>route fallback · {{ firstText(runtimeContractPrimaryRoute.view, 'department') }}</small>
        </div>
        <div>
          <span>Surfaces</span>
          <strong>{{ runtimeContractSurfaces.length || 0 }}</strong>
          <small>{{ runtimeContractSurfaces.join(' / ') || 'contract.surfaces missing' }}</small>
        </div>
        <div>
          <span>Gate deps</span>
          <strong>{{ runtimeContractGateDependencies.length || 0 }}</strong>
          <small>{{ runtimeContractGateDependencies.slice(0, 4).join(' / ') || 'contract.gate_dependencies missing' }}</small>
        </div>
        <div>
          <span>Policy</span>
          <strong>{{ runtimeContractOk ? 'allow view' : 'do not trust' }}</strong>
          <small>完整 Loop 面板与员工空间、编制图谱共用同一 contract guard。</small>
        </div>
        <div>
          <span>Surface ready</span>
          <strong>{{ runtimeSurfaceReadinessOk ? 'ready' : 'blocked' }}</strong>
          <small>{{ runtimeSurfaceMissing.length ? `${runtimeSurfaceReadiness.action || 'repair'} · ${runtimeSurfaceMissing.slice(0, 3).join(' / ')}` : (runtimeSurfaceReadiness.title || runtimeSurfaceKey) }}</small>
        </div>
        <div>
          <span>Surface incidents</span>
          <strong>{{ runtimeSurfaceIncidents.length }} / {{ runtimeAllSurfaceIncidents.length }}</strong>
          <small>{{ runtimeSurfaceIncidents.length ? `${firstText(runtimeSurfaceIncident.action, runtimeSurfaceIncident.title, 'inspect_runtime_contract')} -> ${firstText(runtimeSurfaceIncident.target_surface, runtimeSurfaceKey)} · ${asArray(runtimeSurfaceIncident.missing).slice(0, 3).join(' / ') || runtimeSurfaceKey}` : 'current surface clear' }}</small>
        </div>
        <div>
          <span>Incident summary</span>
          <strong>{{ firstText(runtimeSurfaceIncidentSummary.status, runtimeSurfaceIncidentSummary.total ?? 0) }}</strong>
          <small>{{ firstText(runtimeSurfaceIncidentSummary.primary_action) ? `${runtimeSurfaceIncidentSummary.primary_action} -> ${firstText(runtimeSurfaceIncidentSummary.primary_target_surface, runtimeSurfaceIncidentSummary.primary_surface, 'unknown')} · total ${runtimeSurfaceIncidentSummary.total ?? 0}` : (asArray(runtimeSurfaceIncidentSummary.actions).slice(0, 3).join(' / ') || 'all surfaces clear') }}</small>
        </div>
        <div>
          <span>Global nested audit</span>
          <strong>{{ runtimeContractMissingNested.length ? `missing ${runtimeContractMissingNested.length}` : 'clear' }}</strong>
          <small>{{ runtimeContractMissingNested.length ? runtimeContractMissingNested.slice(0, 4).join(' / ') : `global=${runtimeContractValidation.global_ok === false ? 'blocked' : 'ok'} · all_surfaces=${runtimeContractValidation.all_surfaces_ok === false ? 'blocked' : 'ok'}` }}</small>
        </div>
      </div>
    </div>

    <div v-if="activeGateItems.length" class="selp-active-gates" aria-label="当前门禁总览">
      <div class="selp-active-gates-head">
        <span>Active gates</span>
        <strong>{{ activeGates.ok === false ? 'blocked' : 'clear' }}</strong>
        <small>{{ activeGates.blocking_count ?? 0 }} blocking · {{ asArray(activeGates.blocking_keys).join(' / ') || 'none' }}</small>
      </div>
      <div class="selp-active-gates-grid" role="list">
        <div
          v-for="gateItem in activeGateItems"
          :key="gateItem.key || gateItem.label"
          class="selp-active-gate"
          :class="gateItem.blocking ? 'selp-active-gate--bad' : 'selp-active-gate--ok'"
          role="listitem"
        >
          <span>{{ gateItem.label || gateItem.key }}</span>
          <strong>{{ gateItem.status || (gateItem.ok === false ? 'blocked' : 'allow') }}</strong>
          <small>{{ firstText(gateItem.reason, gateItem.detail, 'ready') }}</small>
        </div>
      </div>
    </div>

    <div v-if="runtimeAllSurfaceIncidents.length" class="selp-contract-incidents" aria-label="Surface contract incidents">
      <div class="selp-contract-incidents-head">
        <span>Surface incidents</span>
        <strong>{{ runtimeAllSurfaceIncidents.length }}</strong>
        <small>{{ asArray(runtimeSurfaceIncidentSummary.surfaces).slice(0, 4).join(' / ') || 'contract incidents' }}</small>
      </div>
      <div class="selp-contract-incidents-grid" role="list">
        <div
          v-for="incident in runtimeAllSurfaceIncidents"
          :key="firstText(incident.id, incident.surface, incident.action)"
          class="selp-contract-incident"
          :class="`selp-contract-incident--${firstText(incident.severity, 'bad')}`"
          role="listitem"
        >
          <span>{{ firstText(incident.surface, 'surface') }} · {{ firstText(incident.severity, 'bad') }}</span>
          <strong>{{ firstText(incident.title, 'Surface contract incident') }}</strong>
          <small>{{ firstText(incident.action, 'inspect_runtime_contract') }} -> {{ firstText(incident.target_surface, 'self_evolution_loop_runtime') }}</small>
          <small>{{ incident.requires_admin ? 'admin-only' : 'operator' }} · {{ incident.executable ? 'executable' : 'navigate-only' }} · {{ firstText(incident.id, 'contract:surface') }}</small>
          <small>{{ firstText(incident.source, 'contract_validation') }} · {{ firstText(incident.schema_version, runtimeSchemaVersion) }} · {{ firstText(incident.created_at, 'time unknown') }}</small>
          <em>{{ asArray(incident.missing).map((item) => asString(item)).filter(Boolean).slice(0, 5).join(' / ') || firstText(incident.detail, 'missing dependencies') }}</em>
        </div>
      </div>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
