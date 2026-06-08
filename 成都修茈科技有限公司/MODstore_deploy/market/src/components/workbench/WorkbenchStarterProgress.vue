<template>
  <div v-if="labels.length" class="wb-sp" role="status" aria-live="polite">
    <div class="wb-sp__track">
      <span
        v-for="(_, i) in labels"
        :key="i"
        class="wb-sp__pip"
        :class="{
          'wb-sp__pip--done': i < boundedActive,
          'wb-sp__pip--current': i === boundedActive,
          'wb-sp__pip--todo': i > boundedActive,
        }"
        :title="labels[i]"
      />
    </div>
    <p class="wb-sp__caption">{{ labels[boundedActive] || '' }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  labels: string[]
  activeIndex: number
}>()

const boundedActive = computed(() => {
  const n = props.labels.length
  if (n <= 0) return 0
  return Math.min(Math.max(0, props.activeIndex), n - 1)
})
</script>

<style scoped>
.wb-sp {
  margin-top: 0.35rem;
  width: 100%;
  min-width: 0;
}

.wb-sp__track {
  display: flex;
  gap: 4px;
  align-items: center;
}

.wb-sp__pip {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: var(--wb-border-muted, rgba(255, 255, 255, 0.12));
  transition:
    background 0.2s ease,
    opacity 0.2s ease;
}

.wb-sp__pip--done {
  background: var(--wb-status-success, #4ade80);
}

.wb-sp__pip--current {
  background: var(--wb-accent-primary, #818cf8);
  box-shadow: 0 0 8px rgba(129, 140, 248, 0.35);
}

.wb-sp__pip--todo {
  opacity: 0.45;
}

.wb-sp__caption {
  margin: 0.28rem 0 0;
  font-size: 0.68rem;
  line-height: 1.3;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.45));
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
