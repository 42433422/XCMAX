<script setup lang="ts">
import { asRecord, firstText, type AnyRecord } from '@/composables/useLoopRuntimePanel'

defineProps<{
  cards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  hitLines: string[]
  fixHitDetails: AnyRecord[]
  patternHitDetails: AnyRecord[]
}>()
</script>

<template>
  <div class="selp-kb" aria-label="修复知识库与 RedisVL">
    <div class="selp-kb-cards" role="list">
      <div v-for="card in cards" :key="card.key" class="selp-kb-card" :class="`selp-kb-card--${card.tone}`" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>
    <ul v-if="hitLines.length" class="selp-kb-hits">
      <li v-for="line in hitLines" :key="line">{{ line }}</li>
    </ul>
    <div v-if="fixHitDetails.length || patternHitDetails.length" class="selp-kb-detail-list">
      <details v-for="hit in fixHitDetails" :key="`fix-${hit.path || hit.symptom}`" class="selp-kb-detail">
        <summary>{{ hit.symptom || hit.path || '修复知识命中' }}</summary>
        <dl>
          <dt>症状</dt>
          <dd>{{ hit.symptom || '—' }}</dd>
          <dt>根因</dt>
          <dd>{{ hit.root_cause || '—' }}</dd>
          <dt>修复 diff</dt>
          <dd><code>{{ hit.fix_diff || '—' }}</code></dd>
          <dt>必需测试</dt>
          <dd>{{ Array.isArray(hit.required_tests) && hit.required_tests.length ? hit.required_tests.join(' / ') : '—' }}</dd>
          <dt>回滚方案</dt>
          <dd>{{ firstText(hit.rollback_plan, asRecord(hit.executable_template).rollback_plan, '—') }}</dd>
        </dl>
      </details>
      <details v-for="hit in patternHitDetails" :key="`pattern-${hit.path || hit.pattern}`" class="selp-kb-detail">
        <summary>{{ hit.summary || hit.pattern || '代码模式命中' }}</summary>
        <dl>
          <dt>模式</dt>
          <dd>{{ hit.pattern || '—' }}</dd>
          <dt>摘要</dt>
          <dd>{{ hit.summary || '—' }}</dd>
          <dt>适用性</dt>
          <dd>{{ hit.applicability || '—' }}</dd>
          <dt>补丁策略</dt>
          <dd>{{ hit.patch_strategy || '—' }}</dd>
        </dl>
      </details>
    </div>
  </div>
</template>

<style scoped>
.selp-kb {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(59, 130, 246, 0.11), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-kb-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.selp-kb-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-kb-card--ok {
  background: #ecfdf5;
}

.selp-kb-card--warn {
  background: #fffbeb;
}

.selp-kb-card span,
.selp-kb-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-hits {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-kb-hits li {
  overflow: hidden;
  color: #475569;
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-detail-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selp-kb-detail {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
  padding: 8px 9px;
}

.selp-kb-detail summary {
  cursor: pointer;
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.selp-kb-detail dl {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 5px 8px;
  margin: 8px 0 0;
}

.selp-kb-detail dt {
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
}

.selp-kb-detail dd {
  min-width: 0;
  margin: 0;
  color: #334155;
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.selp-kb-detail code {
  white-space: pre-wrap;
}

@media (max-width: 980px) {
  .selp-kb-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selp-kb-cards {
    grid-template-columns: 1fr;
  }
}
</style>