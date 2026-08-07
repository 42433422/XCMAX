<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import { asArray, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  ok: boolean
  schemaVersion: string
  validation: AnyRecord
  requiredFields: string[]
  missingFields: string[]
  surfaceMissing: string[]
  contractStatus: AnyRecord
  surfaceIncidentSummary: AnyRecord
  primaryRoute: AnyRecord
  dutyRosterLocation: RouteLocationRaw | null
  employeeSpaceLocation: RouteLocationRaw | null
  surfaces: string[]
  gateDependencies: string[]
  surfaceReadiness: AnyRecord
  surfaceReadinessOk: boolean
  surfaceKey: string
  surfaceIncidents: AnyRecord[]
  surfaceIncident: AnyRecord
  allSurfaceIncidents: AnyRecord[]
  missingNested: string[]
}>()
</script>

<template>
  <div class="selp-contract" :class="ok ? 'selp-contract--ok' : 'selp-contract--bad'" aria-label="系统状态检查">
    <div class="selp-contract-head">
      <span>系统状态检查</span>
      <strong>{{ ok ? '正常' : '异常' }} · {{ schemaVersion }}</strong>
      <small>
        必需 {{ validation.required_count ?? requiredFields.length }} · 缺失 {{ missingFields.length + surfaceMissing.length }}
        <template v-if="missingFields.length"> · {{ missingFields.slice(0, 5).join(' / ') }}</template>
        <template v-else-if="surfaceMissing.length"> · {{ surfaceMissing.slice(0, 5).join(' / ') }}</template>
      </small>
    </div>
    <div class="selp-contract-grid">
      <div class="selp-contract-primary">
        <span>当前状态</span>
        <strong>{{ firstText(contractStatus.state, surfaceIncidentSummary.status, ok ? '正常' : '异常') }}</strong>
        <small>{{ firstText(primaryRoute.action, contractStatus.primary_action, surfaceIncidentSummary.primary_action, surfaceReadiness.action, ok ? '全部正常' : '检查问题') }} -> {{ firstText(primaryRoute.surface, contractStatus.primary_target_surface, '系统运行时') }}</small>
        <small v-if="firstText(primaryRoute.employee_id, asArray(primaryRoute.target_employee_ids)[0])">目标员工 · {{ firstText(primaryRoute.employee_id, asArray(primaryRoute.target_employee_ids)[0]) }}</small>
        <small>全局={{ contractStatus.global_ok === false ? '异常' : '正常' }} · 所有模块={{ contractStatus.all_surfaces_ok === false ? '异常' : '正常' }}</small>
        <small>{{ primaryRoute.requires_admin ? '仅管理员' : '操作员' }} · {{ primaryRoute.executable ? '可执行' : '仅导航' }} · {{ firstText(primaryRoute.detail, '由后端提供') }}</small>
        <router-link
          v-if="primaryRoute.surface === 'duty_roster_graph' && dutyRosterLocation"
          :to="dutyRosterLocation"
        >
          {{ firstText(primaryRoute.label, '打开目标面') }}
        </router-link>
        <router-link
          v-else-if="primaryRoute.surface === 'employee_space' && employeeSpaceLocation"
          :to="employeeSpaceLocation"
        >
          {{ firstText(primaryRoute.label, '打开目标面') }}
        </router-link>
        <small v-else>默认路由 · {{ firstText(primaryRoute.view, '部门') }}</small>
      </div>
      <div>
        <span>功能模块</span>
        <strong>{{ surfaces.length || 0 }}</strong>
        <small>{{ surfaces.join(' / ') || '模块信息缺失' }}</small>
      </div>
      <div>
        <span>前置检查</span>
        <strong>{{ gateDependencies.length || 0 }}</strong>
        <small>{{ gateDependencies.slice(0, 4).join(' / ') || '检查项信息缺失' }}</small>
      </div>
      <div>
        <span>策略</span>
        <strong>{{ ok ? '可查看' : '不可信' }}</strong>
        <small>完整面板与员工空间、排班管理共用同一状态检查。</small>
      </div>
      <div>
        <span>模块就绪</span>
        <strong>{{ surfaceReadinessOk ? '就绪' : '异常' }}</strong>
        <small>{{ surfaceMissing.length ? `${surfaceReadiness.action || '修复'} · ${surfaceMissing.slice(0, 3).join(' / ')}` : (surfaceReadiness.title || surfaceKey) }}</small>
      </div>
      <div>
        <span>模块异常</span>
        <strong>{{ surfaceIncidents.length }} / {{ allSurfaceIncidents.length }}</strong>
        <small>{{ surfaceIncidents.length ? `${firstText(surfaceIncident.action, surfaceIncident.title, '检查系统状态')} -> ${firstText(surfaceIncident.target_surface, surfaceKey)} · ${asArray(surfaceIncident.missing).slice(0, 3).join(' / ') || surfaceKey}` : '当前模块正常' }}</small>
      </div>
      <div>
        <span>异常汇总</span>
        <strong>{{ firstText(surfaceIncidentSummary.status, surfaceIncidentSummary.total ?? 0) }}</strong>
        <small>{{ firstText(surfaceIncidentSummary.primary_action) ? `${surfaceIncidentSummary.primary_action} -> ${firstText(surfaceIncidentSummary.primary_target_surface, surfaceIncidentSummary.primary_surface, '未知')} · 总计 ${surfaceIncidentSummary.total ?? 0}` : (asArray(surfaceIncidentSummary.actions).slice(0, 3).join(' / ') || '所有模块正常') }}</small>
      </div>
      <div>
        <span>审计记录</span>
        <strong>{{ missingNested.length ? `缺失 ${missingNested.length}` : '正常' }}</strong>
        <small>{{ missingNested.length ? missingNested.slice(0, 4).join(' / ') : `全局=${validation.global_ok === false ? '异常' : '正常'} · 所有模块=${validation.all_surfaces_ok === false ? '异常' : '正常'}` }}</small>
      </div>
    </div>
  </div>
</template>

<style scoped>
.selp-contract {
  display: grid;
  grid-template-columns: minmax(190px, 0.45fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.82);
}

.selp-contract--ok {
  border-color: #bbf7d0;
  background: rgba(240, 253, 244, 0.82);
}

.selp-contract--bad {
  border-color: #fecaca;
  background: rgba(254, 242, 242, 0.9);
}

.selp-contract-head,
.selp-contract-grid > div {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
}

.selp-contract-grid > .selp-contract-primary {
  grid-column: span 2;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 34%),
    rgba(255, 255, 255, 0.86);
}

.selp-contract-head span,
.selp-contract-head small,
.selp-contract-grid span,
.selp-contract-grid small {
  display: block;
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-grid a {
  display: inline-flex;
  width: fit-content;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
}

.selp-contract-head strong,
.selp-contract-grid strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 6px;
}

@media (max-width: 760px) {
  .selp-contract {
    grid-template-columns: 1fr;
  }

  .selp-contract-grid {
    grid-template-columns: 1fr;
  }
}
</style>