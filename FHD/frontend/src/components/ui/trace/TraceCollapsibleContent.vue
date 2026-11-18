<script setup lang="ts">
import type { CollapsibleContentProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { CollapsibleContent } from 'reka-ui'
import { computed } from 'vue'

const props = defineProps<CollapsibleContentProps & { class?: HTMLAttributes['class'] }>()
const delegatedProps = computed(() => {
  const delegated = { ...props }
  delete delegated.class
  return delegated
})
</script>

<template>
  <CollapsibleContent data-slot="trace-collapsible-content" v-bind="delegatedProps">
    <div data-slot="trace-collapsible-content-inner" :class="props.class">
      <slot />
    </div>
  </CollapsibleContent>
</template>
