<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

const props = defineProps<{
  status?: 'running' | 'error' | 'pending'
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <span data-slot="trace-line" :data-status="status" :class="props.class"><slot /></span>
</template>
