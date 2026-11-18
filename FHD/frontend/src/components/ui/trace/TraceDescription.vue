<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <span data-slot="trace-description" :class="props.class"><slot /></span>
</template>
