<script setup lang="ts">
import type { KbHitDetail } from './useSelfEvolutionRuntime'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 KB 区块）；模板逐字迁移，行为不变。
defineProps<{
  kbCards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  kbHitLines: string[]
  kbFixHitDetails: KbHitDetail[]
  kbPatternHitDetails: KbHitDetail[]
}>()
</script>

<template>
    <div class="selp-kb" aria-label="修复知识库与 RedisVL">
      <div class="selp-kb-cards" role="list">
        <div v-for="card in kbCards" :key="card.key" class="selp-kb-card" :class="`selp-kb-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="kbHitLines.length" class="selp-kb-hits">
        <li v-for="line in kbHitLines" :key="line">{{ line }}</li>
      </ul>
      <div v-if="kbFixHitDetails.length || kbPatternHitDetails.length" class="selp-kb-detail-list">
        <details v-for="hit in kbFixHitDetails" :key="`fix-${hit.path || hit.symptom}`" class="selp-kb-detail">
          <summary>{{ hit.symptom || hit.path || '修复知识命中' }}</summary>
          <dl>
            <dt>症状</dt>
            <dd>{{ hit.symptom || '—' }}</dd>
            <dt>根因</dt>
            <dd>{{ hit.root_cause || '—' }}</dd>
            <dt>修复 diff</dt>
            <dd><code>{{ hit.fix_diff || '—' }}</code></dd>
            <dt>required tests</dt>
            <dd>{{ Array.isArray(hit.required_tests) && hit.required_tests.length ? hit.required_tests.join(' / ') : '—' }}</dd>
            <dt>rollback plan</dt>
            <dd>{{ hit.rollback_plan || hit.executable_template?.rollback_plan || '—' }}</dd>
          </dl>
        </details>
        <details v-for="hit in kbPatternHitDetails" :key="`pattern-${hit.path || hit.pattern}`" class="selp-kb-detail">
          <summary>{{ hit.pattern || hit.summary || '代码模式命中' }}</summary>
          <dl>
            <dt>模式</dt>
            <dd>{{ hit.pattern || '—' }}</dd>
            <dt>摘要</dt>
            <dd>{{ hit.summary || '—' }}</dd>
            <dt>适用性</dt>
            <dd>{{ hit.applicability || '—' }}</dd>
            <dt>patch strategy</dt>
            <dd>{{ hit.patch_strategy || '—' }}</dd>
          </dl>
        </details>
      </div>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
