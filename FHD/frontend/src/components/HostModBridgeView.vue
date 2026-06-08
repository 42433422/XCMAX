<template>
  <component :is="View" v-bind="bindProps" />
</template>

<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { useAdminModHostView } from '@/composables/useAdminModHostView'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modId: string
  view: string
  title?: string
}>()

const attrs = useAttrs()
const { View, modProps } = useAdminModHostView(
  props.modId,
  props.view,
  props.title || props.view.replace(/View$/, ''),
)

const bindProps = computed(() => ({ ...modProps, ...attrs }))
</script>
