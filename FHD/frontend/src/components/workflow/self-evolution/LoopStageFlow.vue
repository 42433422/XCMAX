<script setup lang="ts">
defineProps<{
  stages: Array<{ key: string; title: string; value: string; meta: string; tone: string }>
}>()
</script>

<template>
  <div class="selp-flow" role="list" aria-label="自进化循环阶段">
    <div v-for="stage in stages" :key="stage.key" class="selp-stage" :class="`selp-stage--${stage.tone}`" role="listitem">
      <span class="selp-stage-dot" aria-hidden="true" />
      <span class="selp-stage-title">{{ stage.title }}</span>
      <strong class="selp-stage-value">{{ stage.value }}</strong>
      <span class="selp-stage-meta">{{ stage.meta }}</span>
    </div>
  </div>
</template>

<style scoped>
.selp-flow {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 9px;
}

.selp-stage {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px;
  overflow: hidden;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}

.selp-stage::after {
  content: '';
  position: absolute;
  inset: auto -18px -28px auto;
  width: 70px;
  height: 70px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--stage-color, #64748b) 14%, transparent);
}

.selp-stage--ok {
  --stage-color: #16a34a;
}
.selp-stage--warn {
  --stage-color: #f59e0b;
}
.selp-stage--bad {
  --stage-color: #ef4444;
}
.selp-stage--running {
  --stage-color: #2563eb;
}
.selp-stage--idle {
  --stage-color: #64748b;
}

.selp-stage-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--stage-color, #64748b);
  box-shadow: 0 0 10px color-mix(in srgb, var(--stage-color, #64748b) 50%, transparent);
}

.selp-stage-title {
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-stage-value {
  position: relative;
  z-index: 1;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-stage-meta {
  color: var(--selp-muted);
  font-size: 12px;
  line-height: 1.35;
}

@media (max-width: 980px) {
  .selp-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .selp-flow {
    grid-template-columns: 1fr;
  }
}
</style>
