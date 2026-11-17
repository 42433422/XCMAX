<template>
  <nav class="admin-section-nav" :aria-label="label">
    <button v-for="item in items" :key="item.value" type="button"
      :aria-pressed="modelValue === item.value" @click="select(item.value)">{{ item.label }}</button>
  </nav>
</template>
<script setup lang="ts">
import { nextTick } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  items: Array<{ value: string; label: string }>
  label: string
  /** 分区内容区已声明 view-transition-name 时开启原生视图过渡；默认直接切换。 */
  viewTransition?: boolean
}>(), { viewTransition: false })

const emit = defineEmits<{ (event: 'update:modelValue', value: string): void }>()

type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => Promise<void> | void) => { finished: Promise<void> }
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function apply(value: string) {
  emit('update:modelValue', value)
}

function select(value: string) {
  if (props.modelValue === value) return
  const doc = typeof document === 'undefined' ? null : (document as ViewTransitionDocument)
  if (!props.viewTransition || !doc?.startViewTransition || prefersReducedMotion()) {
    apply(value)
    return
  }
  doc.startViewTransition(async () => {
    apply(value)
    await nextTick()
  })
}
</script>
