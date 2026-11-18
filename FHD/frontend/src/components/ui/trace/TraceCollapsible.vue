<script setup lang="ts">
import type { CollapsibleRootEmits, CollapsibleRootProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { CollapsibleRoot, useForwardPropsEmits } from 'reka-ui'

const props = defineProps<CollapsibleRootProps & { class?: HTMLAttributes['class'] }>()
const emits = defineEmits<CollapsibleRootEmits>()
const forwarded = useForwardPropsEmits(() => {
  const delegated = { ...props }
  delete delegated.class
  return delegated
}, emits)
</script>

<template>
  <CollapsibleRoot v-slot="slotProps" data-slot="trace-collapsible" v-bind="forwarded" :class="props.class">
    <slot v-bind="slotProps" />
  </CollapsibleRoot>
</template>
