<script setup lang="ts">
import { computed } from 'vue'
import type { DirectGeneratedFile } from '../../../utils/directGeneratedFiles'
import { directFileKind, directFileKindLabel } from '../../../utils/directAttachments'

const props = withDefaults(
  defineProps<{
    files: DirectGeneratedFile[]
    maxVisible?: number
    /** 为 true 时不渲染「+N」更多卡片（溢出由 AI 管家收纳） */
    hideMoreCard?: boolean
    disabled?: boolean
    /** deck：底栏叠卡；chip：顶栏单行胶囊 */
    layout?: 'deck' | 'chip'
  }>(),
  { layout: 'deck' },
)

const emit = defineEmits<{
  download: [file: DirectGeneratedFile]
  remove: [id: string]
}>()

const isChip = computed(() => props.layout === 'chip')

const maxVisible = computed(() => {
  if (props.maxVisible != null) return Math.max(0, props.maxVisible)
  return 3
})
const visible = computed(() => {
  const limit = maxVisible.value
  if (limit <= 0) return []
  if (isChip.value) return props.files.slice(Math.max(0, props.files.length - limit))
  return props.files.slice(0, limit)
})
const hiddenCount = computed(() => Math.max(0, props.files.length - maxVisible.value))

function kind(f: DirectGeneratedFile) {
  return directFileKind(f.name || f.filename)
}

function kindLabel(f: DirectGeneratedFile) {
  return directFileKindLabel(kind(f))
}

function displayName(f: DirectGeneratedFile) {
  return String(f.name || f.filename || '未命名').trim() || '未命名'
}

function onCardClick(f: DirectGeneratedFile) {
  if (props.disabled) return
  emit('download', f)
}

function onCardKeydown(e: KeyboardEvent, f: DirectGeneratedFile) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    onCardClick(f)
  }
}
</script>

<template>
  <TransitionGroup
    v-if="files.length"
    :name="isChip ? 'wb-file-chip' : 'wb-direct-file-card'"
    tag="div"
    class="wb-direct-file-stack"
    :class="{ 'wb-direct-file-stack--generated': true, 'wb-direct-file-stack--chip': isChip }"
    aria-label="已生成文件"
  >
    <template v-if="isChip">
      <article
        v-for="f in visible"
        :key="f.id"
        class="wb-file-chip wb-file-chip--generated"
        :class="[`wb-file-chip--${f.status}`, `wb-file-chip--${kind(f)}`]"
        :title="`${displayName(f)}：点击下载`"
        role="button"
        tabindex="0"
        @click="onCardClick(f)"
        @keydown="onCardKeydown($event, f)"
      >
        <span class="wb-file-chip__badge">{{ kindLabel(f) }}</span>
        <span class="wb-file-chip__name">{{ displayName(f) }}</span>
        <span class="wb-file-chip__tag" title="由办公生成员真实生成">已生成</span>
        <button
          type="button"
          class="wb-file-chip__remove"
          :aria-label="`移除 ${displayName(f)}`"
          :disabled="disabled"
          @click.stop="emit('remove', f.id)"
        >
          ×
        </button>
      </article>
    </template>
    <template v-else>
      <article
        v-for="(f, i) in visible"
        :key="f.id"
        class="wb-direct-file-card wb-direct-file-card--generated"
        :class="[`wb-direct-file-card--${f.status}`, `wb-direct-file-card--${kind(f)}`]"
        :style="{ '--att-index': i }"
        :title="`${displayName(f)}：点击下载`"
        role="button"
        tabindex="0"
        @click="onCardClick(f)"
        @keydown="onCardKeydown($event, f)"
      >
        <span class="wb-direct-file-card__deck" aria-hidden="true">
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--back" />
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--mid" />
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--front">
            <span class="wb-direct-file-card__deck-label">{{ kindLabel(f) }}</span>
          </span>
        </span>
        <span class="wb-direct-file-card__state" aria-hidden="true">
          <span class="wb-direct-file-card__check">✓</span>
        </span>
        <div class="wb-direct-file-card__purpose" @click.stop>
          <span class="wb-direct-file-card__purpose-tag" title="由办公生成员真实生成，点击卡片下载">已生成</span>
        </div>
        <button
          type="button"
          class="wb-direct-file-card__remove"
          :aria-label="`移除 ${displayName(f)}`"
          :disabled="disabled"
          @click.stop="emit('remove', f.id)"
        >
          ×
        </button>
      </article>
      <div
        v-if="hiddenCount && !props.hideMoreCard"
        key="__gen-more"
        class="wb-direct-file-card wb-direct-file-card--more"
        aria-label="更多已生成文件"
      >
        <span class="wb-direct-file-card__deck" aria-hidden="true">
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--back" />
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--mid" />
          <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--front">
            <span class="wb-direct-file-card__deck-plus">+{{ hiddenCount }}</span>
          </span>
        </span>
      </div>
    </template>
  </TransitionGroup>
</template>
