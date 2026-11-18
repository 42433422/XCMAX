<script setup lang="ts">
import type { CollapsibleTriggerProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { CollapsibleTrigger } from 'reka-ui'
import { computed } from 'vue'
import TraceIcon from './TraceIcon.vue'

const props = defineProps<CollapsibleTriggerProps & { class?: HTMLAttributes['class'] }>()
const delegatedProps = computed(() => {
  const delegated = { ...props }
  delete delegated.class
  return delegated
})
</script>

<template>
  <CollapsibleTrigger data-slot="trace-collapsible-trigger" v-bind="delegatedProps" :class="props.class">
    <slot />
    <TraceIcon class="xc-trace-chevron"><i class="fa fa-chevron-right"></i></TraceIcon>
  </CollapsibleTrigger>
</template>
