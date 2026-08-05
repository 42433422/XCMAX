<script setup lang="ts">
import { asArray, asString, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  items: AnyRecord[]
  activeGates: AnyRecord
}>()
</script>

<template>
  <div v-if="items.length" class="selp-active-gates" aria-label="检查项总览">
    <div class="selp-active-gates-head">
      <span>检查项</span>
      <strong>{{ activeGates.ok === false ? '异常' : '正常' }}</strong>
      <small>{{ activeGates.blocking_count ?? 0 }} 阻断 · {{ asArray(activeGates.blocking_keys).map((k) => asString(k)).join(' / ') || '无' }}</small>
    </div>
    <div class="selp-active-gates-grid" role="list">
      <div
        v-for="gateItem in items"
        :key="firstText(gateItem.key, gateItem.label)"
        class="selp-active-gate"
        :class="gateItem.blocking ? 'selp-active-gate--bad' : 'selp-active-gate--ok'"
        role="listitem"
      >
        <span>{{ gateItem.label || gateItem.key }}</span>
        <strong>{{ gateItem.status || (gateItem.ok === false ? '异常' : '允许') }}</strong>
        <small>{{ firstText(gateItem.reason, gateItem.detail, '就绪') }}</small>
      </div>
    </div>
  </div>
</template>

<style scoped>
.selp-active-gates {
  display: grid;
  grid-template-columns: minmax(160px, 0.36fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: rgba(238, 242, 255, 0.78);
}

.selp-active-gates-head,
.selp-active-gate {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-active-gates-head span,
.selp-active-gates-head small,
.selp-active-gate span,
.selp-active-gate small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-active-gates-head strong,
.selp-active-gate strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-active-gates-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.selp-active-gate--ok {
  background: rgba(240, 253, 244, 0.86);
}

.selp-active-gate--bad {
  background: rgba(254, 242, 242, 0.92);
}

@media (max-width: 760px) {
  .selp-active-gates {
    grid-template-columns: 1fr;
  }

  .selp-active-gates-grid {
    grid-template-columns: 1fr;
  }
}
</style>