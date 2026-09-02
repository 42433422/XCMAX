<script setup lang="ts">
// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 loop 阶段 + 决策卡区块）；模板逐字迁移，行为不变。
defineProps<{
  loopStages: Array<{ key: string; title: string; value: string; meta: string; tone: string }>
  decisionCards: Array<{ key: string; label: string; value: string; sub: string }>
}>()
</script>

<template>
    <div class="selp-flow" role="list" aria-label="自进化 loop 阶段">
      <div
        v-for="stage in loopStages"
        :key="stage.key"
        class="selp-stage"
        :class="`selp-stage--${stage.tone}`"
        role="listitem"
      >
        <span class="selp-stage-dot" aria-hidden="true" />
        <span class="selp-stage-title">{{ stage.title }}</span>
        <strong class="selp-stage-value">{{ stage.value }}</strong>
        <span class="selp-stage-meta">{{ stage.meta }}</span>
      </div>
    </div>

    <div class="selp-decision" role="list" aria-label="auto merge 决策">
      <div v-for="card in decisionCards" :key="card.key" class="selp-decision-card" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
