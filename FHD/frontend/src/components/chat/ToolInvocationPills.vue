<template>
  <div v-if="chips.length" class="context-summary tool-invocation-summary">
    <span class="context-summary__label" aria-hidden="true">
      <svg class="context-summary__icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M4.5 2.75h7a1.25 1.25 0 0 1 1.25 1.25v8a1.25 1.25 0 0 1-1.25 1.25h-7A1.25 1.25 0 0 1 3.25 12V4A1.25 1.25 0 0 1 4.5 2.75Z"
          stroke="currentColor"
          stroke-width="1.2"
        />
        <path d="M6 5.5h4M6 8h4M6 10.5h2.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
      </svg>
      工具
    </span>
    <span v-for="(chip, idx) in chips" :key="idx" class="context-summary__chip" :title="chip.detail || chip.label">
      {{ chip.detail ? `${chip.label} · ${chip.detail}` : chip.label }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { extractToolInvocationChips } from '@/utils/chatBubbleDisplay'

const props = defineProps<{
  content?: string
}>()

const chips = computed(() => extractToolInvocationChips(props.content))
</script>
