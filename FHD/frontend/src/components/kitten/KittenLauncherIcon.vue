<template>
  <img
    class="kitten-launcher-svg"
    :class="{ 'kitten-launcher-svg--sm': size === 'sm' }"
    :src="smartAnalysisIcon"
    alt=""
    aria-hidden="true"
    draggable="false"
  />
</template>

<script setup lang="ts">
import smartAnalysisIcon from '@/assets/icons/smart-analysis.png'

withDefaults(
  defineProps<{
    size?: 'md' | 'sm'
  }>(),
  { size: 'md' },
)
</script>

<style scoped>
.kitten-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
  object-fit: cover;
  border-radius: 12px;
}
.kitten-launcher-svg--sm {
  width: 28px;
  height: 28px;
  border-radius: 7px;
}
</style>
