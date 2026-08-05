<script setup lang="ts">
import type { AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  policy: AnyRecord
  branchName: string
  actionLabel: string
}>()
</script>

<template>
  <div class="selp-bottom">
    <div class="selp-policy">
      <span>自动合并</span>
      <strong>{{ policy.auto_merge_low_risk === false ? '关闭' : '低风险开启' }}</strong>
      <small>最大风险 {{ policy.auto_merge_max_risk_score ?? '—' }} · 最小安全 {{ policy.auto_merge_min_safety_score_v2 ?? '—' }}</small>
    </div>
    <div class="selp-policy">
      <span>最近分支</span>
      <strong>{{ branchName || '无' }}</strong>
      <small>{{ actionLabel }}</small>
    </div>
  </div>
</template>

<style scoped>
.selp-bottom {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}

.selp-policy {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}

.selp-policy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 11px 12px;
}

.selp-policy span,
.selp-policy small {
  color: var(--selp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.selp-policy strong {
  overflow: hidden;
  color: var(--selp-text);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 980px) {
  .selp-bottom {
    grid-template-columns: 1fr;
  }
}
</style>