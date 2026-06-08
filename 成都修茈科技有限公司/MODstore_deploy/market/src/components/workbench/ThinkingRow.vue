<template>
  <div class="wb-thinking-row" role="status" aria-live="polite">
    <span class="wb-thinking-row__shimmer" aria-hidden="true" />
    <span class="wb-thinking-row__text">{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
  }>(),
  { label: '正在思考…' },
)
</script>

<style scoped>
.wb-thinking-row {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0;
  color: rgba(203, 213, 225, 0.75);
  font-size: 0.9rem;
}

.wb-thinking-row__shimmer {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: rgba(129, 140, 248, 0.85);
  animation: wb-thinking-pulse 1.1s ease-in-out infinite;
}

.wb-thinking-row__text {
  opacity: 0.92;
}

@keyframes wb-thinking-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
