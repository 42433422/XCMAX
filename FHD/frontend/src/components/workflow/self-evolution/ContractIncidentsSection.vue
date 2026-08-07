<script setup lang="ts">
import { asArray, asString, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  allSurfaceIncidents: AnyRecord[]
  surfaceIncidentSummary: AnyRecord
  schemaVersion: string
}>()
</script>

<template>
  <div v-if="allSurfaceIncidents.length" class="selp-contract-incidents" aria-label="模块异常事件">
    <div class="selp-contract-incidents-head">
      <span>模块异常</span>
      <strong>{{ allSurfaceIncidents.length }}</strong>
      <small>{{ asArray(surfaceIncidentSummary.surfaces).map((s) => asString(s)).slice(0, 4).join(' / ') || '异常事件' }}</small>
    </div>
    <div class="selp-contract-incidents-grid" role="list">
      <div
        v-for="incident in allSurfaceIncidents"
        :key="firstText(incident.id, incident.surface, incident.action)"
        class="selp-contract-incident"
        :class="`selp-contract-incident--${firstText(incident.severity, '严重')}`"
        role="listitem"
      >
        <span>{{ firstText(incident.surface, '模块') }} · {{ firstText(incident.severity, '严重') }}</span>
        <strong>{{ firstText(incident.title, '模块异常事件') }}</strong>
        <small>{{ firstText(incident.action, '检查系统状态') }} -> {{ firstText(incident.target_surface, '系统运行时') }}</small>
        <small>{{ incident.requires_admin ? '仅管理员' : '操作员' }} · {{ incident.executable ? '可执行' : '仅导航' }} · {{ firstText(incident.id, '状态:模块') }}</small>
        <small>{{ firstText(incident.source, '状态校验') }} · {{ firstText(incident.schema_version, schemaVersion) }} · {{ firstText(incident.created_at, '时间未知') }}</small>
        <em>{{ asArray(incident.missing).map((item) => asString(item)).filter(Boolean).slice(0, 5).join(' / ') || firstText(incident.detail, '缺少依赖') }}</em>
      </div>
    </div>
  </div>
</template>

<style scoped>
.selp-contract-incidents {
  display: grid;
  grid-template-columns: minmax(190px, 0.34fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 12px;
  background: rgba(254, 242, 242, 0.88);
}

.selp-contract-incidents-head,
.selp-contract-incident {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-contract-incidents-head span,
.selp-contract-incidents-head small,
.selp-contract-incident span,
.selp-contract-incident small,
.selp-contract-incident em {
  display: block;
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-incidents-head strong,
.selp-contract-incident strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-incidents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px;
}

.selp-contract-incident--warn {
  background: rgba(255, 251, 235, 0.9);
}

@media (max-width: 760px) {
  .selp-contract-incidents {
    grid-template-columns: 1fr;
  }

  .selp-contract-incidents-grid {
    grid-template-columns: 1fr;
  }
}
</style>