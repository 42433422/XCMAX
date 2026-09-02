<script setup lang="ts">
import { proactiveCandidateMeta, proactiveCandidateTitle, type AnyRecord } from './runtimeHelpers'

// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 proactive 信号区块）；模板逐字迁移，行为不变。
defineProps<{
  proactiveCards: Array<{ key: string; label: string; value: string; sub: string; tone: string }>
  proactiveCandidates: AnyRecord[]
}>()
</script>

<template>
    <div class="selp-proactive" aria-label="主动优化任务信号">
      <div class="selp-proactive-cards" role="list">
        <div v-for="card in proactiveCards" :key="card.key" class="selp-proactive-card" :class="`selp-proactive-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="proactiveCandidates.length" class="selp-proactive-list">
        <li v-for="item in proactiveCandidates" :key="`${proactiveCandidateTitle(item)}-${proactiveCandidateMeta(item)}`">
          <strong>{{ proactiveCandidateTitle(item) }}</strong>
          <span>{{ proactiveCandidateMeta(item) }}</span>
        </li>
      </ul>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
