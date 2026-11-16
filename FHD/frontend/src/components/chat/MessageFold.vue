<template>
  <CollapsibleRoot :open="false" @update:open="onOpenChange">
    <div :id="bodyId" ref="outerRef" class="msg-fold__body is-clamped">
      <div ref="innerRef" class="msg-fold__inner">
        <slot />
      </div>
      <span v-if="overflowing" class="msg-fold__fade" aria-hidden="true"></span>
    </div>
    <CollapsibleTrigger
      v-if="overflowing"
      class="msg-fold__trigger"
      :aria-label="expandLabel"
      :aria-controls="bodyId"
    >
      <span>{{ expandLabel }}</span>
      <svg class="msg-fold__chevron" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
    </CollapsibleTrigger>
  </CollapsibleRoot>
</template>

<script setup lang="ts">
/**
 * 长消息折叠块。
 *
 * 结构复用 Reka UI 的 Collapsible（原 Radix Vue）：触发按钮自带 aria-expanded /
 * aria-controls 与键盘行为。截断用标准 `line-clamp`，并真实检测内容是否溢出——
 * 短文不显示「展开全文」，避免以前「历史消息一律折叠」造成的割裂。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'

const props = withDefaults(
  defineProps<{
    expandLabel?: string
  }>(),
  {
    expandLabel: '展开全文',
  },
)

const emit = defineEmits<{
  expand: []
}>()

const overflowing = ref(false)
const bodyId = `msg-fold-${useId()}`
const outerRef = ref<HTMLElement | null>(null)
const innerRef = ref<HTMLElement | null>(null)
let observer: ResizeObserver | null = null

/** 三行大致能显示的字符数；无布局信息（SSR / jsdom）时作为兜底判断。 */
const FALLBACK_OVERFLOW_CHARS = 120

/** 折叠态下内层保留自然高度、外层被 line-clamp 截断，比较两者即可判断是否溢出。 */
function measure(): void {
  const outer = outerRef.value
  const inner = innerRef.value
  if (!outer || !inner) return
  if (!outer.clientHeight) {
    // 没有布局信息时退化成文本长度判断，保证短文依旧不出现「展开全文」。
    overflowing.value = (inner.textContent || '').trim().length > FALLBACK_OVERFLOW_CHARS
    return
  }
  overflowing.value = inner.scrollHeight > outer.clientHeight + 1
}

function onOpenChange(open: boolean): void {
  if (open) emit('expand')
}

onMounted(async () => {
  await nextTick()
  measure()
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(() => measure())
  if (outerRef.value) observer.observe(outerRef.value)
  if (innerRef.value) observer.observe(innerRef.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})
</script>

<style scoped>
.msg-fold__body {
  position: relative;
  max-width: 100%;
  font-size: 13px;
  line-height: 1.55;
  color: #4b5563;
}

.msg-fold__body.is-clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.msg-fold__inner {
  display: block;
}

/* 截断处渐隐，提示还有内容 */
.msg-fold__fade {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 20px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0), rgba(255, 255, 255, 0.92));
  pointer-events: none;
}

.msg-fold__trigger {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: 6px 0 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--xc-color-primary, #0b72d9);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  white-space: nowrap;
}

.msg-fold__trigger:hover {
  color: var(--xc-color-primary-dark, #0956a8);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.msg-fold__trigger:focus-visible {
  outline: 2px solid rgba(11, 114, 217, 0.35);
  outline-offset: 2px;
  border-radius: 2px;
}

.msg-fold__chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
</style>
