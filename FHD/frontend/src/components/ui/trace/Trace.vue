<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div data-slot="trace" :class="['xc-trace', props.class]">
    <slot />
  </div>
</template>

<style src="./trace.css"></style>
